"""Scheduler — 장 운영시간 인지 주기 작업 (NFR-04, FR-17, 설계 §2·§11.5).

작업: 장전 브리핑(08:30) / 장중 스캔(설정 주기) / scalp 실시간 동기화(1분, §5.4)
/ 마감 후 배치(15:40) / 백업(03:00).
휴장일은 setting `market.holidays`(YYYY-MM-DD 쉼표 목록)로 관리한다.
"""

import logging
from datetime import date, datetime, time as dtime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

log = logging.getLogger(__name__)

MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)


def holidays(session) -> set[date]:
    from ..db import get_setting

    raw = get_setting(session, "market.holidays", "") or ""
    out = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok:
            try:
                out.add(date.fromisoformat(tok))
            except ValueError:
                pass
    return out


def is_trading_day(d: date, holiday_set: set[date]) -> bool:
    return d.weekday() < 5 and d not in holiday_set


def is_market_hours(dt: datetime, holiday_set: set[date]) -> bool:
    return is_trading_day(dt.date(), holiday_set) and MARKET_OPEN <= dt.time() <= MARKET_CLOSE


async def sync_scalp_realtime(state, now: datetime | None = None) -> None:
    """§5.4 배선 (FR-13): 장중엔 scalp 조건식 실시간 등록(멱등), 장외엔 구독 종료."""
    with state.sf() as s:
        hs = holidays(s)
    if is_market_hours(now or datetime.now(), hs):
        for seq in state.realtime.scalp_condition_seqs():
            await state.realtime.register_realtime_condition(seq)
    else:
        await state.realtime.stop()


def build_scheduler(state) -> AsyncIOScheduler:
    """app.state의 서비스로 주기 작업 구성."""
    sched = AsyncIOScheduler()

    async def intraday_scan():
        with state.sf() as s:
            hs = holidays(s)
        if not is_market_hours(datetime.now(), hs):
            return  # 장외에는 스캔·구독 중지 (설계 §6)
        try:
            await state.collector.update_regime()
            await state.recommendations.run_scan()
        except Exception as e:
            log.exception("장중 스캔 실패: %s", e)

    async def morning_briefing():
        with state.sf() as s:
            hs = holidays(s)
        if not is_trading_day(date.today(), hs):
            return
        try:
            label, _ = await state.collector.update_regime()
            text = build_morning_briefing(state, label)
            await state.notifier.send_event("morning_briefing", {"text": text})
        except Exception as e:
            log.exception("장전 브리핑 실패: %s", e)

    async def evening_batch():
        with state.sf() as s:
            hs = holidays(s)
        if not is_trading_day(date.today(), hs):
            return
        try:
            await state.orders.reconcile()
            saved = state.recommendations.evaluate_performance()
            text = await build_evening_briefing(state, saved)
            await state.notifier.send_event("evening_briefing", {"text": text})
        except Exception as e:
            log.exception("마감 배치 실패: %s", e)

    async def nightly_backup():
        from .backup import run_backup

        try:
            run_backup(state.settings)
        except Exception as e:
            log.exception("백업 실패: %s", e)
            await state.notifier.send_event("backup_failed", {"error": str(e)})

    async def scalp_realtime_job():
        try:
            await sync_scalp_realtime(state)
        except Exception as e:
            log.exception("scalp 실시간 동기화 실패: %s", e)

    interval = state.settings.scan_interval_min
    sched.add_job(intraday_scan, "interval", minutes=interval, id="intraday_scan")
    sched.add_job(scalp_realtime_job, "interval", minutes=1, id="scalp_realtime")
    sched.add_job(morning_briefing, CronTrigger(hour=8, minute=30), id="morning_briefing")
    sched.add_job(evening_batch, CronTrigger(hour=15, minute=40), id="evening_batch")
    sched.add_job(nightly_backup, CronTrigger(hour=3, minute=0), id="nightly_backup")
    return sched


def build_morning_briefing(state, regime_label: str) -> str:
    """장전 브리핑 (FR-17): 전일 요약 + 오늘의 시장 국면.

    예상체결 기반 갭 상위는 TR 미매핑으로 v1 제외 (작업 기록의 남은 사항 참조).
    """
    from ..models import MarketRegime, Recommendation

    lines = [f"🌅 장전 브리핑 {date.today().isoformat()}", f"시장 국면: {regime_label}"]
    with state.sf() as s:
        prev = s.scalars(
            select(MarketRegime).order_by(MarketRegime.date.desc()).offset(1).limit(1)
        ).first()
        if prev:
            lines.append(f"전일 국면: {prev.label}")
        latest_ts = s.scalar(
            select(Recommendation.ts).order_by(Recommendation.ts.desc()).limit(1)
        )
        if latest_ts:
            n = len(s.scalars(
                select(Recommendation).where(Recommendation.ts == latest_ts)
            ).all())
            lines.append(f"직전 스캔 추천: {n}건")
    return "\n".join(lines)


async def build_evening_briefing(state, perf_saved: int) -> str:
    """마감 브리핑 (FR-17): 계좌 손익 + 추천 성과 + 보유 종목 의견."""
    lines = [f"🌇 마감 브리핑 {date.today().isoformat()}"]
    try:
        pf = await state.orders.portfolio()
        lines.append(
            f"계좌: 평가 {pf['total_eval']:,.0f}원 "
            f"({pf['total_pnl_pct']:+.2f}%, {pf['total_pnl']:+,.0f}원)"
        )
    except Exception as e:
        lines.append(f"계좌 조회 실패: {e}")
    report = state.recommendations.performance_report()
    for profile, horizons in report.items():
        h1 = horizons.get(1)
        if h1:
            lines.append(
                f"[{profile}] 1일 적중률 {h1['hit_rate']}% (평균 {h1['avg_return']:+.2f}%)"
            )
    lines.append(f"성과 평가 신규 {perf_saved}건")
    return "\n".join(lines)

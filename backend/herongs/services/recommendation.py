"""RecommendationService — 추천 생성·개별 의견·성과 추적 (FR-04~07, FR-16, 설계 §5.2·§5.5)."""

import logging
from datetime import date, datetime

from sqlalchemy import select

from ..config import Settings
from ..db import get_setting_float
from ..models import (
    DailyPrice,
    MarketRegime,
    Opinion,
    Recommendation,
    RecommendationPerf,
)
from ..scoring import PROFILES, Candidate, decide_stance
from ..scoring.opinion import Holding
from .collector import Collector

log = logging.getLogger(__name__)

HORIZONS = (1, 5, 20)  # 경과 수익률 평가 시점 (영업일)
DEFAULT_MIN_SCORE = 60.0


class RecommendationService:
    def __init__(
        self,
        collector: Collector,
        session_factory,
        settings: Settings,
        notify=None,  # async (kind:str, payload:dict) — Notifier (FR-11)
    ):
        self._collector = collector
        self._sf = session_factory
        self._settings = settings
        self._notify = notify

    def current_regime(self) -> str:
        with self._sf() as s:
            row = s.scalars(
                select(MarketRegime).order_by(MarketRegime.date.desc()).limit(1)
            ).first()
        return row.label if row else "sideways"

    # ── 시장 스캔 → 추천 (설계 §5.1 5~6단계) ─────────────────────

    async def run_scan(self) -> dict[str, list[dict]]:
        candidates = await self._collector.scan()
        regime = self.current_regime()
        now = datetime.now()
        results: dict[str, list[dict]] = {}

        with self._sf() as s:
            profiles = PROFILES(s)
            min_score = get_setting_float(s, "recommend.min_score", DEFAULT_MIN_SCORE)

        for key, profile in profiles.items():
            top_n = self._settings.recommend_top_n
            threshold = min_score
            # 국면 보정: 하락장에서는 스윙·단타 추천을 줄이고 기준을 높인다 (FR-14)
            if regime == "bear" and key in ("swing", "scalp"):
                top_n = max(1, top_n // 2)
                threshold += 10.0

            scored = [(c, profile.score(c)) for c in candidates]
            scored = [x for x in scored if x[1].total >= threshold]
            scored.sort(key=lambda x: x[1].total, reverse=True)
            scored = scored[:top_n]

            with self._sf() as s:
                prev_codes = set(
                    s.scalars(
                        select(Recommendation.code)
                        .where(Recommendation.profile == key)
                        .order_by(Recommendation.ts.desc())
                        .limit(top_n)
                    ).all()
                )
                entries = []
                for rank, (c, score) in enumerate(scored, start=1):
                    rec = Recommendation(
                        ts=now, profile=key, code=c.code, score=score.total,
                        score_breakdown=score.breakdown, rank=rank, regime=regime,
                        base_price=c.closes[-1] if c.closes else 0.0,
                    )
                    s.add(rec)
                    entries.append(
                        {"code": c.code, "name": c.name, "rank": rank,
                         "score": score.total, "breakdown": score.breakdown}
                    )
                s.commit()
            results[key] = entries

            # 직전 스캔 대비 신규 진입 종목 알림 (FR-11)
            new_codes = [e for e in entries if e["code"] not in prev_codes]
            if new_codes and self._notify:
                await self._notify(
                    "new_recommendation",
                    {"profile": key, "regime": regime, "stocks": new_codes},
                )
        return results

    # ── 개별 종목 분석 (설계 §5.2) ────────────────────────────────

    async def analyze_stock(
        self, code: str, holdings: dict[str, Holding] | None = None
    ) -> list[dict]:
        supply_map = await self._collector.fetch_supply_map()
        candidate = await self._collector.build_candidate(code, {"name": ""}, supply_map)
        return self.opinions_for(candidate, holdings or {})

    def opinions_for(self, candidate: Candidate, holdings: dict[str, Holding]) -> list[dict]:
        regime = self.current_regime()
        now = datetime.now()
        current_price = candidate.closes[-1] if candidate.closes else 0.0
        base_holding = holdings.get(candidate.code)
        out = []
        with self._sf() as s:
            profiles = PROFILES(s)
            from ..models import Instrument

            inst = s.get(Instrument, candidate.code)
            for key, profile in profiles.items():
                prev = s.scalars(
                    select(Opinion)
                    .where(Opinion.code == candidate.code, Opinion.profile == key)
                    .order_by(Opinion.ts.desc()).limit(1)
                ).first()
                prev_band = (prev.rationale or {}).get("band") if prev else None
                # 보유 종목: 전략별 손절/목표 기본값 적용 (FR-07/15)
                holding = None
                if base_holding:
                    from ..scoring.opinion import RISK_PARAMS

                    stop_rate, target_rate = RISK_PARAMS.get(key, RISK_PARAMS["swing"])
                    holding = Holding(
                        avg_price=base_holding.avg_price,
                        qty=base_holding.qty,
                        stop_price=base_holding.stop_price
                        or round(base_holding.avg_price * (1 - stop_rate), 0),
                        target_price=base_holding.target_price
                        or round(base_holding.avg_price * (1 + target_rate), 0),
                    )
                score = profile.score(candidate)
                rationale = decide_stance(
                    key, score, current_price,
                    holding=holding, prev_band=prev_band, regime=regime,
                    is_managed=bool(inst and inst.is_managed),
                    is_halted=bool(inst and inst.is_halted),
                )
                # 보유 종목: 매입가 대비 위치를 근거에 추가 (FR-07)
                if holding and holding.avg_price:
                    rationale["holding"] = {
                        "avg_price": holding.avg_price,
                        "qty": holding.qty,
                        "pnl_pct": round((current_price / holding.avg_price - 1) * 100, 2),
                        "stop_price": holding.stop_price,
                        "target_price": holding.target_price,
                    }
                s.add(Opinion(ts=now, code=candidate.code, profile=key,
                              stance=rationale["stance"], rationale=rationale))
                out.append({"profile": key, "code": candidate.code,
                            "name": candidate.name, **rationale})
            s.commit()
        return out

    # ── 성과 추적 배치 (설계 §5.5, FR-16) ─────────────────────────

    def evaluate_performance(self) -> int:
        """마감 후 실행: 1/5/20 영업일 경과 추천의 수익률 계산·저장. 저장 건수 반환."""
        saved = 0
        with self._sf() as s:
            recs = s.scalars(select(Recommendation)).all()
            for rec in recs:
                if not rec.base_price:
                    continue
                done = {
                    p.horizon
                    for p in s.scalars(
                        select(RecommendationPerf).where(RecommendationPerf.rec_id == rec.id)
                    ).all()
                }
                pending = [h for h in HORIZONS if h not in done]
                if not pending:
                    continue
                # 추천일 이후 영업일 = daily_price에 존재하는 일자
                after = s.scalars(
                    select(DailyPrice)
                    .where(DailyPrice.code == rec.code, DailyPrice.date > rec.ts.date())
                    .order_by(DailyPrice.date.asc())
                ).all()
                for h in pending:
                    if len(after) >= h:
                        ret = (after[h - 1].close / rec.base_price - 1) * 100
                        s.add(RecommendationPerf(
                            rec_id=rec.id, horizon=h,
                            return_pct=round(ret, 2), evaluated_at=datetime.now(),
                        ))
                        saved += 1
            s.commit()
        return saved

    def performance_report(self) -> dict:
        """전략별 적중률(수익>0 비율)·평균 수익률 (FR-16, AC-09)."""
        report: dict = {}
        with self._sf() as s:
            rows = s.execute(
                select(Recommendation.profile, RecommendationPerf.horizon,
                       RecommendationPerf.return_pct)
                .join(RecommendationPerf, RecommendationPerf.rec_id == Recommendation.id)
            ).all()
        for profile, horizon, ret in rows:
            bucket = report.setdefault(profile, {}).setdefault(
                horizon, {"n": 0, "hits": 0, "sum": 0.0}
            )
            bucket["n"] += 1
            bucket["hits"] += 1 if ret > 0 else 0
            bucket["sum"] += ret
        for profile in report:
            for horizon, b in report[profile].items():
                report[profile][horizon] = {
                    "count": b["n"],
                    "hit_rate": round(b["hits"] / b["n"] * 100, 1) if b["n"] else 0.0,
                    "avg_return": round(b["sum"] / b["n"], 2) if b["n"] else 0.0,
                }
        return report

    def history(self, profile: str | None = None, limit: int = 100) -> list[dict]:
        """추천 이력 + 경과 수익률 (AC-09)."""
        with self._sf() as s:
            q = select(Recommendation).order_by(Recommendation.ts.desc()).limit(limit)
            if profile:
                q = q.where(Recommendation.profile == profile)
            recs = s.scalars(q).all()
            out = []
            for r in recs:
                perfs = {
                    p.horizon: p.return_pct
                    for p in s.scalars(
                        select(RecommendationPerf).where(RecommendationPerf.rec_id == r.id)
                    ).all()
                }
                out.append({
                    "id": r.id, "ts": r.ts.isoformat(), "profile": r.profile,
                    "code": r.code, "score": r.score, "rank": r.rank,
                    "regime": r.regime, "returns": perfs,
                })
        return out

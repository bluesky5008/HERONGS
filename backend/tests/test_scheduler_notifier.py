"""WU-10 — 장 운영시간 판정, 알림 발송·이력, 백업."""

from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from herongs.config import Settings
from herongs.models import AlertLog
from herongs.services.backup import run_backup
from herongs.services.notifier import Notifier
from herongs.services.scheduler import is_market_hours, is_trading_day


def test_trading_day_and_market_hours():
    hs = {date(2026, 7, 27)}  # 임시 휴장일 (월요일)
    assert is_trading_day(date(2026, 7, 24), hs)  # 금요일
    assert not is_trading_day(date(2026, 7, 25), hs)  # 토요일
    assert not is_trading_day(date(2026, 7, 27), hs)  # 휴장일
    assert is_market_hours(datetime(2026, 7, 24, 10, 0), hs)
    assert not is_market_hours(datetime(2026, 7, 24, 8, 59), hs)  # 장전
    assert not is_market_hours(datetime(2026, 7, 24, 15, 31), hs)  # 장후


async def test_intraday_scan_survives_regime_failure(sf, settings, monkeypatch):
    """국면 조회가 유량 초과로 실패해도 스캔은 수행된다 (2026-08-04 운영 이슈)."""
    from types import SimpleNamespace

    import herongs.services.scheduler as sch

    monkeypatch.setattr(
        sch, "datetime",
        type("DT", (), {"now": staticmethod(lambda: datetime(2026, 8, 5, 10, 0))}),
    )
    ran = []

    async def failing_regime():
        raise RuntimeError("[ka20006] 5: 허용된 요청 개수를 초과하였습니다")

    async def run_scan():
        ran.append("scan")
        return {}

    state = SimpleNamespace(
        sf=sf, settings=settings,
        collector=SimpleNamespace(update_regime=failing_regime),
        recommendations=SimpleNamespace(run_scan=run_scan),
    )
    await sch.build_scheduler(state).get_job("intraday_scan").func()
    assert ran == ["scan"]  # 국면 실패가 스캔 주기를 통째로 날리지 않는다


async def test_notifier_sends_and_logs(sf):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    settings = Settings(telegram_bot_token="BOT", telegram_chat_id="42", _env_file=None)
    n = Notifier(settings, sf, transport=httpx.MockTransport(handler))
    ok = await n.send_event("new_recommendation", {
        "profile": "swing", "regime": "bull",
        "stocks": [{"rank": 1, "code": "005930", "name": "삼성전자", "score": 85.0}],
    })
    assert ok
    assert "botBOT/sendMessage" in captured["url"]
    with sf() as s:
        row = s.scalars(select(AlertLog)).one()
        assert row.sent and row.kind == "new_recommendation"


async def test_notifier_disabled_still_logs(sf):
    n = Notifier(Settings(_env_file=None), sf)
    ok = await n.send_text("테스트")
    assert not ok
    with sf() as s:
        assert s.query(AlertLog).count() == 1  # 이력은 남는다 (NFR-05)


def test_backup_creates_snapshot_and_prunes(tmp_path):
    import sqlite3

    db = tmp_path / "herongs.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()

    dest = tmp_path / "nas"
    dest.mkdir()
    (dest / "herongs-20200101.db").write_bytes(b"old")  # 보관 기한 초과분

    settings = Settings(db_path=db, backup_dir=str(dest), backup_keep_days=14,
                        _env_file=None)
    out = run_backup(settings, today=datetime(2026, 7, 25))
    assert out == dest / "herongs-20260725.db"
    assert out.exists()  # AC-12 단위 검증
    assert not (dest / "herongs-20200101.db").exists()  # 14일 초과 삭제
    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    con.close()

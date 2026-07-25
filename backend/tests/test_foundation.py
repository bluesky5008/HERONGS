"""WU-01/02 — 설정, 로깅 마스킹, DB 모델."""

import logging

from sqlalchemy import inspect

from herongs import logsetup
from herongs.config import Settings
from herongs.db import get_setting, init_db, set_setting
from herongs.logsetup import SecretMaskFilter, register_secret


def test_settings_domain_switch():
    s = Settings(trading_mode="mock", _env_file=None)
    assert s.api_base == "https://mockapi.kiwoom.com"
    assert "mockapi" in s.ws_url
    s = Settings(trading_mode="real", _env_file=None)
    assert s.api_base == "https://api.kiwoom.com"


def test_settings_default_is_mock():
    # 실계좌는 명시적 전환으로만 (NFR-02)
    assert Settings(_env_file=None).trading_mode == "mock"


def test_secret_masking():
    register_secret("SUPERSECRETKEY")
    rec = logging.LogRecord(
        "t", logging.INFO, "", 0, "token=SUPERSECRETKEY 발급", (), None
    )
    SecretMaskFilter().filter(rec)
    assert "SUPERSECRETKEY" not in rec.getMessage()
    assert "***" in rec.getMessage()
    logsetup._SECRETS.clear()


def test_db_tables_created():
    engine = init_db(":memory:")
    tables = set(inspect(engine).get_table_names())
    assert tables == {
        "instrument", "daily_price", "recommendation", "recommendation_perf",
        "opinion", "order_log", "condition_map", "market_regime",
        "watchlist", "alert_log", "setting",
    }


def test_setting_roundtrip():
    init_db(":memory:")
    from herongs.db import SessionLocal

    with SessionLocal() as s:
        assert get_setting(s, "k", "d") == "d"
        set_setting(s, "k", "v1")
        assert get_setting(s, "k") == "v1"
        set_setting(s, "k", "v2")
        assert get_setting(s, "k") == "v2"

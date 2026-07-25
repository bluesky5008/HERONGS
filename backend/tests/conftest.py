"""공용 픽스처 — 인메모리 DB + 키움 목 서버."""

import httpx
import pytest

import herongs.db as dbmod
from herongs.config import Settings
from herongs.db import init_db
from herongs.kiwoom import KiwoomClient

TOKEN_RESP = {
    "return_code": 0,
    "token": "TESTTOKEN",
    "token_type": "bearer",
    "expires_dt": "20991231235959",
}


@pytest.fixture
def sf():
    """테스트마다 새 인메모리 DB의 session factory."""
    init_db(":memory:")
    return dbmod.SessionLocal


@pytest.fixture
def settings():
    return Settings(kiwoom_appkey="AK", kiwoom_secretkey="SK", _env_file=None)


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self):
        return self.now

    async def sleep(self, d):
        self.sleeps.append(d)
        self.now += d


def make_kiwoom_client(routes: dict, settings: Settings) -> KiwoomClient:
    """routes: {tr_id: dict | callable(request)->dict} — return_code 0 자동 부여."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json=TOKEN_RESP)
        tr = request.headers.get("api-id", "")
        body = routes.get(tr)
        if body is None:
            return httpx.Response(200, json={"return_code": 0})
        if callable(body):
            body = body(request)
        return httpx.Response(200, json={"return_code": 0, **body})

    ft = FakeTime()
    return KiwoomClient(
        settings, transport=httpx.MockTransport(handler),
        clock=ft.clock, sleep=ft.sleep,
    )

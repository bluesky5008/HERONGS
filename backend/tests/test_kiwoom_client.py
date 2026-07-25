"""WU-03 — KiwoomClient: 인증, 스로틀, 연속조회, 백오프."""

import json

import httpx
import pytest

from herongs.config import Settings
from herongs.kiwoom import KiwoomClient, KiwoomError
from herongs.kiwoom.throttle import RateGate

TOKEN_RESP = {
    "return_code": 0,
    "token": "TESTTOKEN",
    "token_type": "bearer",
    "expires_dt": "20991231235959",
}


def make_settings(**kw):
    return Settings(
        kiwoom_appkey="AK", kiwoom_secretkey="SK", _env_file=None, **kw
    )


class FakeTime:
    """가짜 클록·슬립 — 실제 대기 없이 시간 진행을 기록한다."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self):
        return self.now

    async def sleep(self, d):
        self.sleeps.append(d)
        self.now += d


def make_client(handler, **kw):
    ft = FakeTime()
    client = KiwoomClient(
        make_settings(**kw),
        transport=httpx.MockTransport(handler),
        clock=ft.clock,
        sleep=ft.sleep,
    )
    return client, ft


async def test_token_issued_and_header_sent():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json=TOKEN_RESP)
        calls.append(dict(request.headers))
        return httpx.Response(200, json={"return_code": 0, "rows": []})

    client, _ = make_client(handler)
    data, headers = await client.call("ka10001", {"stk_cd": "005930"})
    assert data["return_code"] == 0
    assert calls[0]["authorization"] == "Bearer TESTTOKEN"
    assert calls[0]["api-id"] == "ka10001"


async def test_continuous_query_merges_pages():
    page = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json=TOKEN_RESP)
        page["n"] += 1
        if page["n"] < 3:
            assert request.headers["next-key"] == ("" if page["n"] == 1 else f"K{page['n']-1}")
            return httpx.Response(
                200,
                json={"return_code": 0, "rows": [{"i": page["n"]}]},
                headers={"cont-yn": "Y", "next-key": f"K{page['n']}"},
            )
        return httpx.Response(
            200, json={"return_code": 0, "rows": [{"i": 3}]}, headers={"cont-yn": "N"}
        )

    client, _ = make_client(handler)
    rows = await client.call_all("ka10081", {"stk_cd": "005930"}, "rows")
    assert [r["i"] for r in rows] == [1, 2, 3]


async def test_rate_limit_1700_backoff_then_success():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json=TOKEN_RESP)
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(200, json={"return_code": 1700, "return_msg": "유량"})
        return httpx.Response(200, json={"return_code": 0})

    client, ft = make_client(handler)
    data, _ = await client.call("ka10023", {})
    assert data["return_code"] == 0
    assert 1.0 in ft.sleeps and 2.0 in ft.sleeps  # 지수 백오프 1s→2s


async def test_rate_limit_1701_sets_global_penalty():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json=TOKEN_RESP)
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(200, json={"return_code": 1701, "return_msg": "전체 유량"})
        return httpx.Response(200, json={"return_code": 0})

    client, ft = make_client(handler)
    await client.call("ka10023", {})
    assert client._global_penalty_until > 0  # 전역 백오프 적용됨


async def test_recursion_1687_raises_without_retry():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json=TOKEN_RESP)
        attempts["n"] += 1
        return httpx.Response(200, json={"return_code": 1687, "return_msg": "재귀"})

    client, _ = make_client(handler)
    with pytest.raises(KiwoomError):
        await client.call("ka10001", {})
    assert attempts["n"] == 1  # 재시도 없음


async def test_401_reissues_token_once():
    state = {"tokens": 0, "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            state["tokens"] += 1
            return httpx.Response(200, json=TOKEN_RESP)
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(401)
        return httpx.Response(200, json={"return_code": 0})

    client, _ = make_client(handler)
    data, _ = await client.call("ka10001", {})
    assert data["return_code"] == 0
    assert state["tokens"] == 2


async def test_rate_gate_spacing():
    ft = FakeTime()
    gate = RateGate(0.2, clock=ft.clock, sleep=ft.sleep)
    await gate.wait()  # 즉시
    await gate.wait()  # +0.2
    await gate.wait()  # +0.2
    assert ft.sleeps == [pytest.approx(0.2), pytest.approx(0.2)]

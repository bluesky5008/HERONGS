"""WU-11 — WebSocket 게이트웨이: 로그인, 조건검색, 단타 신호 (§5.4)."""

import asyncio
import json

from sqlalchemy import select

from herongs.models import ConditionMap
from herongs.services.realtime import RealtimeGateway, ScalpSignalHandler

from .conftest import make_kiwoom_client


class FakeWS:
    """키움 WS 프로토콜 목: send 내용에 따라 응답을 큐에 넣는다."""

    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []

    async def send(self, raw: str):
        msg = json.loads(raw)
        self.sent.append(msg)
        t = msg.get("trnm")
        if t == "LOGIN":
            await self.q.put(json.dumps({"trnm": "LOGIN", "return_code": 0}))
        elif t == "CNSRLST":
            await self.q.put(json.dumps({
                "trnm": "CNSRLST",
                "data": [["0", "HERONGS_SWING"], ["1", "HERONGS_SCALP"]],
            }))
        elif t == "CNSRREQ" and msg.get("search_type") == "0":
            await self.q.put(json.dumps({
                "trnm": "CNSRREQ",
                "data": [{"9001": "A005930"}, {"9001": "A000660"}],
            }))

    async def recv(self) -> str:
        return await self.q.get()

    async def close(self):
        pass


def make_gateway(sf, settings):
    ws = FakeWS()

    async def ws_connect(url):
        return ws

    client = make_kiwoom_client({}, settings)
    gw = RealtimeGateway(client, settings, sf, ws_connect=ws_connect)
    return gw, ws


async def test_refresh_conditions_upserts_preserving_mapping(sf, settings):
    with sf() as s:  # 기존 매핑 보존 확인
        s.add(ConditionMap(seq="0", name="OLD", profile="swing", enabled=True))
        s.commit()
    gw, _ = make_gateway(sf, settings)
    items = await gw.refresh_conditions()
    assert {i["seq"] for i in items} == {"0", "1"}  # AC-08: 목록 표시
    with sf() as s:
        rows = {r.seq: r for r in s.scalars(select(ConditionMap)).all()}
        assert rows["0"].name == "HERONGS_SWING"  # 이름 갱신
        assert rows["0"].profile == "swing"  # 매핑 보존
        assert rows["1"].profile == ""  # 신규는 미매핑
    await gw.close()


async def test_run_condition_returns_codes(sf, settings):
    gw, ws = make_gateway(sf, settings)
    codes = await gw.run_condition("1")
    assert codes == ["005930", "000660"]  # A 접두사 제거
    req = next(m for m in ws.sent if m.get("trnm") == "CNSRREQ")
    assert req["search_type"] == "0"  # 일반 실행 (ka10172)
    await gw.close()


async def test_ping_echo(sf, settings):
    gw, ws = make_gateway(sf, settings)
    await gw.connect()
    await ws.q.put(json.dumps({"trnm": "PING", "seq": "7"}))
    await asyncio.sleep(0.05)
    assert {"trnm": "PING", "seq": "7"} in ws.sent  # 에코
    await gw.close()


async def test_scalp_handler_subscribe_evaluate_release(sf, settings):
    gw, ws = make_gateway(sf, settings)
    await gw.connect()
    alerts = []

    async def notify(kind, payload):
        alerts.append((kind, payload))

    handler = ScalpSignalHandler(gw, sf, notify=notify, min_score=50.0)

    # 1) 조건 편입 이벤트 → 0B/0D 구독
    await handler.on_real({"data": [{
        "type": "02", "item": "A005930", "values": {"841": "1", "843": "I"},
    }]})
    reg = next(m for m in ws.sent if m.get("trnm") == "REG")
    assert reg["data"][0]["item"] == ["005930"]

    # 2) 호가(0D) → 매수 우위, 체결(0B) → 판정
    await handler.on_real({"data": [{
        "type": "0D", "item": "005930",
        "values": {"121": "1000", "125": "3000"},
    }]})
    await handler.on_real({"data": [{
        "type": "0B", "item": "005930",
        "values": {"10": "+5000", "12": "7.0", "228": "150"},
    }]})

    # 3) 판정 후 즉시 해제 (Q-02 한도 관리) + 신호 알림
    assert any(m.get("trnm") == "REMOVE" for m in ws.sent)
    assert handler._watching == {}
    assert alerts and alerts[0][0] == "scalp_signal"
    await gw.close()

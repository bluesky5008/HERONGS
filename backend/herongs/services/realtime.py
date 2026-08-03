"""RealtimeGateway — WebSocket 구독·조건검색·재접속 (FR-13, 설계 §2·§5.4·§6).

키움 WS 프로토콜(trnm): LOGIN / PING / CNSRLST(조건 목록) / CNSRREQ(조건 실행)
/ CNSRCLR(실시간 조건 해제) / REG·REMOVE(실시간 TR) / REAL(실시간 데이터).
"""

import asyncio
import json
import logging

from sqlalchemy import select

from ..config import Settings
from ..kiwoom import KiwoomClient
from ..models import ConditionMap
from ..utils import pnum

log = logging.getLogger(__name__)

_REQ_TIMEOUT = 10.0
_RECONNECT_BACKOFFS = [1.0, 2.0, 4.0, 8.0, 16.0]


class RealtimeGateway:
    def __init__(
        self,
        client: KiwoomClient,
        settings: Settings,
        session_factory,
        ws_connect=None,  # 테스트 주입용: async (url) -> ws(send/recv/close)
    ):
        self._client = client
        self._settings = settings
        self._sf = session_factory
        if ws_connect is None:
            import websockets

            ws_connect = websockets.connect
        self._ws_connect = ws_connect
        self._ws = None
        self._recv_task: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._registered: list[dict] = []  # 재접속 시 재등록용 REG payload (설계 §6)
        self._rt_conditions: list[str] = []  # 실시간 등록된 조건식 seq
        self.on_real = None  # async (data: dict) — REAL 수신 콜백

    # ── 접속·수신 루프 ────────────────────────────────────────────

    async def connect(self) -> None:
        async with self._lock:
            if self._ws is not None:
                return
            token = await self._client.token()
            self._ws = await self._ws_connect(self._settings.ws_url)
            await self._send({"trnm": "LOGIN", "token": token})
            resp = json.loads(await self._ws.recv())
            if resp.get("return_code", 0) != 0:
                raise ConnectionError(f"WS 로그인 실패: {resp.get('return_msg')}")
            self._recv_task = asyncio.create_task(self._recv_loop())
            log.info("WebSocket 접속·로그인 완료")

    async def _send(self, payload: dict) -> None:
        await self._ws.send(json.dumps(payload))

    async def _recv_loop(self) -> None:
        try:
            while True:
                raw = await self._ws.recv()
                msg = json.loads(raw)
                trnm = msg.get("trnm", "")
                if trnm == "PING":
                    await self._send(msg)  # 에코
                elif trnm == "REAL":
                    if self.on_real:
                        try:
                            await self.on_real(msg)
                        except Exception:
                            log.exception("REAL 처리 실패")
                else:
                    fut = self._pending.pop(trnm, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("WS 수신 종료: %s — 재접속 시도", e)
            self._ws = None
            asyncio.get_running_loop().create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """지수 백오프 재접속 + 실시간 TR·조건검색 자동 재등록 (설계 §6)."""
        for delay in _RECONNECT_BACKOFFS:
            await asyncio.sleep(delay)
            try:
                await self.connect()
                for payload in self._registered:
                    await self._send(payload)
                for seq in self._rt_conditions:
                    await self._send(_cnsr_req(seq, realtime=True))
                log.info("WS 재접속·재등록 완료")
                return
            except Exception as e:
                log.warning("재접속 실패: %s", e)
        log.error("WS 재접속 포기 (백오프 소진)")

    async def _request(self, trnm: str, payload: dict) -> dict:
        await self.connect()
        fut = asyncio.get_running_loop().create_future()
        self._pending[trnm] = fut
        await self._send(payload)
        return await asyncio.wait_for(fut, _REQ_TIMEOUT)

    # ── 조건검색 (FR-13, D-07) ───────────────────────────────────

    async def refresh_conditions(self) -> list[dict]:
        """HTS 등록 조건식 목록(CNSRLST) → condition_map 동기화 (AC-08)."""
        resp = await self._request("CNSRLST", {"trnm": "CNSRLST"})
        items = resp.get("data") or []
        with self._sf() as s:
            for entry in items:
                seq, name = str(entry[0]), str(entry[1])
                row = s.get(ConditionMap, seq)
                if row is None:
                    s.add(ConditionMap(seq=seq, name=name, profile="", enabled=True))
                else:
                    row.name = name  # 매핑(profile)은 보존
            s.commit()
        return [{"seq": str(e[0]), "name": str(e[1])} for e in items]

    async def run_condition(self, seq: str) -> list[str]:
        """조건검색 일반 실행(CNSRREQ, ka10172) → 종목코드 목록."""
        resp = await self._request("CNSRREQ", _cnsr_req(seq, realtime=False))
        codes = []
        for row in resp.get("data") or []:
            code = row.get("9001") or row.get("jmcode") or ""
            code = str(code).strip().removeprefix("A")
            if code:
                codes.append(code)
        return codes

    async def register_realtime_condition(self, seq: str) -> None:
        """조건검색 실시간 등록 (ka10173). 이미 등록된 seq는 무시 — 주기 동기화 대비 멱등."""
        if seq in self._rt_conditions:
            return
        await self.connect()
        await self._send(_cnsr_req(seq, realtime=True))
        self._rt_conditions.append(seq)

    async def remove_realtime_condition(self, seq: str) -> None:
        await self._send({"trnm": "CNSRCLR", "seq": seq})  # ka10174
        if seq in self._rt_conditions:
            self._rt_conditions.remove(seq)

    # ── 실시간 TR 등록 (0B 체결, 0D 호가) ────────────────────────

    async def subscribe(self, codes: list[str], types: list[str], grp_no: str = "1") -> None:
        await self.connect()
        payload = {
            "trnm": "REG", "grp_no": grp_no, "refresh": "1",
            "data": [{"item": codes, "type": types}],
        }
        await self._send(payload)
        self._registered.append(payload)

    async def unsubscribe(self, codes: list[str], types: list[str], grp_no: str = "1") -> None:
        await self._send({
            "trnm": "REMOVE", "grp_no": grp_no, "refresh": "1",
            "data": [{"item": codes, "type": types}],
        })
        self._registered = [
            p for p in self._registered
            if not (p["grp_no"] == grp_no and p["data"][0]["item"] == codes)
        ]

    def scalp_condition_seqs(self) -> list[str]:
        with self._sf() as s:
            rows = s.scalars(
                select(ConditionMap).where(
                    ConditionMap.enabled, ConditionMap.profile == "scalp"
                )
            ).all()
        return [r.seq for r in rows]

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def stop(self) -> None:
        """장 마감·앱 종료: 등록 상태 폐기 후 접속 종료 — 재접속 시 재등록 방지 (§5.4)."""
        self._rt_conditions.clear()
        self._registered.clear()
        await self.close()


def _cnsr_req(seq: str, realtime: bool) -> dict:
    return {
        "trnm": "CNSRREQ",
        "seq": seq,
        "search_type": "1" if realtime else "0",
        "stex_tp": "K",
        "cont_yn": "N",
        "next_key": "",
    }


class ScalpSignalHandler:
    """§5.4 — 조건 편입 이벤트 → 0B/0D 구독 → 판정 → 즉시 해제 (Q-02 한도 관리)."""

    def __init__(self, gateway: RealtimeGateway, session_factory, notify=None,
                 min_score: float = 70.0):
        self._gw = gateway
        self._sf = session_factory
        self._notify = notify
        self._min_score = min_score
        self._watching: dict[str, dict] = {}  # code → 수집 중인 실시간 값

    async def on_real(self, msg: dict) -> None:
        for item in msg.get("data") or []:
            rt_type = item.get("type", "")
            values = item.get("values") or {}
            code = str(item.get("item", "")).strip().removeprefix("A")
            if rt_type == "02":  # 조건검색 편입/이탈 (841: seq, 843: I/D)
                if values.get("843") == "I" and code not in self._watching:
                    self._watching[code] = {}
                    await self._gw.subscribe([code], ["0B", "0D"], grp_no="9")
            elif rt_type == "0B" and code in self._watching:
                w = self._watching[code]
                w["price"] = abs(pnum(values.get("10")))  # 현재가
                w["change_rate"] = pnum(values.get("12"))  # 등락률
                w["strength"] = pnum(values.get("228"))  # 체결강도
                await self._evaluate(code)
            elif rt_type == "0D" and code in self._watching:
                sell_q = pnum(values.get("121"))  # 매도호가총잔량
                buy_q = pnum(values.get("125"))  # 매수호가총잔량
                if sell_q > 0:
                    self._watching[code]["imbalance"] = buy_q / sell_q - 1.0

    async def _evaluate(self, code: str) -> None:
        w = self._watching.get(code) or {}
        if "strength" not in w:
            return
        from ..scoring import PROFILES, Candidate

        candidate = Candidate(
            code=code,
            change_rate=w.get("change_rate", 0.0),
            strength=w.get("strength", 0.0),
            bid_ask_imbalance=w.get("imbalance", 0.0),
            rt_volume_ratio=w.get("rt_volume_ratio", 0.0),
            trading_value=w.get("trading_value", 0.0),
        )
        with self._sf() as s:
            score = PROFILES(s)["scalp"].score(candidate)
        # 판정 후 즉시 구독 해제 → 등록 한도 관리 (설계 §5.4)
        await self._gw.unsubscribe([code], ["0B", "0D"], grp_no="9")
        del self._watching[code]
        if score.total >= self._min_score and self._notify:
            await self._notify("scalp_signal", {
                "code": code, "score": score.total,
                "strength": w.get("strength"), "breakdown": score.breakdown,
            })

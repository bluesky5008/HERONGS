"""KiwoomClient — 인증·스로틀·연속조회·백오프 공통 호출 계층 (FR-01/02, NFR-03, 설계 §2·§6)."""

import asyncio
import logging
import time
from datetime import datetime, timedelta

import httpx

from ..config import Settings
from ..logsetup import register_secret
from .errors import (
    RATE_LIMIT_GLOBAL,
    RATE_LIMIT_PER_TR,
    RECURSION_LIMIT,
    KiwoomError,
)
from .throttle import RateGate

log = logging.getLogger(__name__)

# TR → URL 경로 (doc/kiwoom-rest-api-spec.json에서 추출)
TR_PATHS = {
    "ka10001": "/api/dostk/stkinfo",
    "ka10004": "/api/dostk/mrkcond",
    "ka10008": "/api/dostk/frgnistt",
    "ka10016": "/api/dostk/stkinfo",
    "ka10023": "/api/dostk/rkinfo",
    "ka10027": "/api/dostk/rkinfo",
    "ka10032": "/api/dostk/rkinfo",
    "ka10033": "/api/dostk/rkinfo",
    "ka10045": "/api/dostk/mrkcond",
    "ka10047": "/api/dostk/mrkcond",
    "ka10075": "/api/dostk/acnt",
    "ka10081": "/api/dostk/chart",
    "ka10082": "/api/dostk/chart",
    "ka10085": "/api/dostk/acnt",
    "ka10131": "/api/dostk/frgnistt",
    "ka20001": "/api/dostk/sect",
    "ka20006": "/api/dostk/chart",
    "ka90009": "/api/dostk/rkinfo",
    "kt00001": "/api/dostk/acnt",
    "kt00018": "/api/dostk/acnt",
    "kt10000": "/api/dostk/ordr",
    "kt10001": "/api/dostk/ordr",
    "kt10002": "/api/dostk/ordr",
    "kt10003": "/api/dostk/ordr",
}

_BACKOFFS = [1.0, 2.0, 4.0]  # 지수 백오프, 최대 3회 (설계 §6)
_TOKEN_REFRESH_MARGIN = timedelta(minutes=30)


class KiwoomClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ):
        self._settings = settings
        self._http = httpx.AsyncClient(
            base_url=settings.api_base, transport=transport, timeout=10.0
        )
        self._clock = clock
        self._sleep = sleep
        self._token: str = ""
        self._token_expiry: datetime = datetime.min
        self._token_lock = asyncio.Lock()
        self._global_gate = RateGate(1.0 / settings.rate_global_per_sec, clock, sleep)
        self._tr_gates: dict[str, RateGate] = {}
        self._global_penalty_until = 0.0  # 1701/1702 전역 백오프 (monotonic)
        self._minute_counts: dict[str, int] = {}  # 분당 호출 수집 (Q-03 로그)
        self._minute_start = 0.0

    # ── 인증 (FR-01) ──────────────────────────────────────────────

    async def _ensure_token(self) -> None:
        async with self._token_lock:
            if self._token and datetime.now() < self._token_expiry - _TOKEN_REFRESH_MARGIN:
                return
            resp = await self._http.post(
                "/oauth2/token",
                json={
                    "grant_type": "client_credentials",
                    "appkey": self._settings.kiwoom_appkey,
                    "secretkey": self._settings.kiwoom_secretkey,
                },
            )
            data = resp.json()
            if data.get("return_code", 0) != 0:
                raise KiwoomError(data["return_code"], data.get("return_msg", ""), "au10001")
            self._token = data["token"]
            register_secret(self._token)
            self._token_expiry = datetime.strptime(data["expires_dt"], "%Y%m%d%H%M%S")
            log.info("접근토큰 발급 완료 (만료: %s)", self._token_expiry)

    async def token(self) -> str:
        """유효한 접근토큰 반환 (WebSocket LOGIN용)."""
        await self._ensure_token()
        return self._token

    async def revoke_token(self) -> None:
        if not self._token:
            return
        await self._http.post(
            "/oauth2/revoke",
            json={
                "appkey": self._settings.kiwoom_appkey,
                "secretkey": self._settings.kiwoom_secretkey,
                "token": self._token,
            },
        )
        self._token = ""
        self._token_expiry = datetime.min

    # ── 스로틀 (FR-02, NFR-03) ────────────────────────────────────

    async def _throttle(self, tr_id: str) -> None:
        if tr_id not in self._tr_gates:
            self._tr_gates[tr_id] = RateGate(
                1.0 / self._settings.rate_per_tr_per_sec, self._clock, self._sleep
            )
        await self._global_gate.wait()
        await self._tr_gates[tr_id].wait()
        remaining = self._global_penalty_until - self._clock()
        if remaining > 0:
            await self._sleep(remaining)

    def _count_call(self, tr_id: str) -> None:
        now = self._clock()
        if now - self._minute_start >= 60.0:
            if self._minute_counts:
                log.info("분당 호출 수: %s", dict(self._minute_counts))
            self._minute_counts = {}
            self._minute_start = now
        self._minute_counts[tr_id] = self._minute_counts.get(tr_id, 0) + 1

    # ── 호출 (FR-02) ──────────────────────────────────────────────

    async def call(
        self,
        tr_id: str,
        body: dict,
        cont_yn: str = "N",
        next_key: str = "",
    ) -> tuple[dict, dict]:
        """단일 TR 호출. (응답 body, {'cont-yn':…, 'next-key':…}) 반환."""
        path = TR_PATHS[tr_id]
        await self._ensure_token()
        reissued = False
        for attempt in range(len(_BACKOFFS) + 1):
            await self._throttle(tr_id)
            self._count_call(tr_id)
            resp = await self._http.post(
                path,
                json=body,
                headers={
                    "authorization": f"Bearer {self._token}",
                    "api-id": tr_id,
                    "cont-yn": cont_yn,
                    "next-key": next_key,
                },
            )
            if resp.status_code == 401 and not reissued:
                # 토큰 무효 → 1회 재발급 후 재시도 (설계 §6)
                self._token = ""
                await self._ensure_token()
                reissued = True
                continue
            data = resp.json()
            code = int(data.get("return_code", 0) or 0)
            if code == 0:
                headers = {
                    "cont-yn": resp.headers.get("cont-yn", "N"),
                    "next-key": resp.headers.get("next-key", ""),
                }
                return data, headers
            if code == RECURSION_LIMIT:
                raise KiwoomError(code, data.get("return_msg", ""), tr_id)
            if code == RATE_LIMIT_PER_TR or code in RATE_LIMIT_GLOBAL:
                if attempt >= len(_BACKOFFS):
                    raise KiwoomError(code, data.get("return_msg", ""), tr_id)
                delay = _BACKOFFS[attempt]
                if code in RATE_LIMIT_GLOBAL:
                    self._global_penalty_until = self._clock() + delay
                log.warning("유량 제한(%s) %s — %.0fs 백오프", code, tr_id, delay)
                await self._sleep(delay)
                continue
            raise KiwoomError(code, data.get("return_msg", ""), tr_id)
        raise KiwoomError(-1, "재시도 초과", tr_id)

    async def call_all(
        self, tr_id: str, body: dict, list_key: str, max_pages: int = 20
    ) -> list[dict]:
        """연속조회(cont-yn/next-key) 자동 처리 — list_key 항목을 병합해 반환."""
        rows: list[dict] = []
        cont_yn, next_key = "N", ""
        for _ in range(max_pages):
            data, headers = await self.call(tr_id, body, cont_yn, next_key)
            rows.extend(data.get(list_key) or [])
            if headers["cont-yn"] != "Y":
                break
            cont_yn, next_key = "Y", headers["next-key"]
        return rows

    async def aclose(self) -> None:
        await self._http.aclose()

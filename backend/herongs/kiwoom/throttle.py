"""요청 스로틀 — 전역 + TR별 이중 제한 (NFR-03, 설계 §10 Q-03 방침)."""

import asyncio
import time


class RateGate:
    """고정 간격 게이트: 연속 통과 사이에 최소 interval초를 보장한다."""

    def __init__(self, interval: float, clock=time.monotonic, sleep=asyncio.sleep):
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            grant_at = max(now, self._next_at)
            self._next_at = grant_at + self._interval
        delay = grant_at - now
        if delay > 0:
            await self._sleep(delay)

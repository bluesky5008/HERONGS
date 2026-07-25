"""Notifier — 텔레그램 발송 + 알림 이력 (FR-11/17, 설계 §2).

설계 스택은 python-telegram-bot이지만 발송은 Bot API POST 1건이므로
기존 의존성 httpx로 대체한다 (경미한 변경 — 결정 사다리 5단계, 작업 기록 참조).
"""

import logging
from datetime import datetime

import httpx

from ..config import Settings
from ..models import AlertLog

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, settings: Settings, session_factory, transport=None):
        self._settings = settings
        self._sf = session_factory
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self._settings.telegram_bot_token and self._settings.telegram_chat_id)

    async def send_text(self, text: str, kind: str = "info") -> bool:
        sent = False
        if self.enabled:
            url = (
                f"https://api.telegram.org/bot{self._settings.telegram_bot_token}"
                "/sendMessage"
            )
            try:
                async with httpx.AsyncClient(transport=self._transport, timeout=10) as c:
                    resp = await c.post(url, json={
                        "chat_id": self._settings.telegram_chat_id,
                        "text": text,
                    })
                    sent = resp.status_code == 200
            except Exception as e:
                log.warning("텔레그램 발송 실패: %s", e)
        else:
            log.info("[알림 비활성] %s", text)
        with self._sf() as s:  # 발송 이력 저장 (alert_log)
            s.add(AlertLog(ts=datetime.now(), kind=kind,
                           payload={"text": text}, sent=sent))
            s.commit()
        return sent

    async def send_event(self, kind: str, payload: dict) -> bool:
        """이벤트 종류별 메시지 포맷 (FR-11)."""
        text = self._format(kind, payload)
        return await self.send_text(text, kind=kind)

    @staticmethod
    def _format(kind: str, p: dict) -> str:
        if kind == "new_recommendation":
            lines = [f"📈 [{p.get('profile')}] 신규 추천 (국면: {p.get('regime')})"]
            for s in p.get("stocks", []):
                lines.append(f"  {s['rank']}. {s.get('name') or s['code']} — {s['score']}점")
            return "\n".join(lines)
        if kind == "stop_loss":
            return (f"🛑 손절선 도달: {p.get('name') or p.get('code')} "
                    f"현재가 {p.get('price'):,.0f} ≤ 손절가 {p.get('stop_price'):,.0f}")
        if kind == "take_profit":
            return (f"🎯 목표가 도달: {p.get('name') or p.get('code')} "
                    f"현재가 {p.get('price'):,.0f} ≥ 목표가 {p.get('target_price'):,.0f}")
        if kind == "scalp_signal":
            return (f"⚡ 단타 신호: {p.get('name') or p.get('code')} "
                    f"{p.get('score')}점 (체결강도 {p.get('strength')})")
        if kind in ("morning_briefing", "evening_briefing"):
            return p.get("text", "")
        if kind == "backup_failed":
            return f"⚠️ 백업 실패: {p.get('error')}"
        return f"[{kind}] {p}"

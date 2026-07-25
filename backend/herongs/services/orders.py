"""OrderService — 2단계 주문(preview→confirm)·가드레일·감사 로그 (FR-08/09/15, NFR-02/05, 설계 §5.3).

주문 전송은 confirm()이 유일한 경로이며, confirm은 유효한 preview_id를 요구한다.
preview 없이 주문이 전송되는 코드 경로는 존재하지 않는다 (AC-04).
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from ..config import Settings
from ..kiwoom import KiwoomClient
from ..models import OrderLog
from ..scoring.opinion import RISK_PARAMS, Holding
from ..utils import pnum, price as pprice

log = logging.getLogger(__name__)

PREVIEW_TTL_SEC = 60.0


@dataclass
class Preview:
    preview_id: str
    side: str  # buy | sell
    code: str
    qty: int
    price: float
    amount: float
    created_at: float
    used: bool = False
    payload: dict = field(default_factory=dict)


class GuardrailError(Exception):
    """가드레일 위반 — 사유를 담아 preview 단계에서 거부 (AC-10)."""


class OrderService:
    def __init__(self, client: KiwoomClient, session_factory, settings: Settings,
                 clock=time.monotonic):
        self._client = client
        self._sf = session_factory
        self._settings = settings
        self._clock = clock
        self._previews: dict[str, Preview] = {}

    # ── 계좌 (FR-09) ─────────────────────────────────────────────

    async def holdings(self) -> dict[str, Holding]:
        """보유 종목 {code: Holding} (kt00018)."""
        data, _ = await self._client.call(
            "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"}
        )
        out: dict[str, Holding] = {}
        for r in data.get("acnt_evlt_remn_indv_tot") or []:
            code = (r.get("stk_cd") or "").strip().removeprefix("A")
            if code:
                out[code] = Holding(
                    avg_price=pprice(r.get("pur_pric")),
                    qty=int(pnum(r.get("rmnd_qty"))),
                )
        return out

    async def portfolio(self) -> dict:
        data, _ = await self._client.call(
            "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"}
        )
        stocks = [
            {
                "code": (r.get("stk_cd") or "").strip().removeprefix("A"),
                "name": r.get("stk_nm", ""),
                "qty": int(pnum(r.get("rmnd_qty"))),
                "avg_price": pprice(r.get("pur_pric")),
                "cur_price": pprice(r.get("cur_prc")),
                "pnl": pnum(r.get("evltv_prft")),
                "pnl_pct": pnum(r.get("prft_rt")),
            }
            for r in data.get("acnt_evlt_remn_indv_tot") or []
        ]
        return {
            "total_purchase": pnum(data.get("tot_pur_amt")),
            "total_eval": pnum(data.get("tot_evlt_amt")),
            "total_pnl": pnum(data.get("tot_evlt_pl")),
            "total_pnl_pct": pnum(data.get("tot_prft_rt")),
            "est_assets": pnum(data.get("prsm_dpst_aset_amt")),
            "stocks": stocks,
        }

    async def deposit(self) -> float:
        data, _ = await self._client.call("kt00001", {"qry_tp": "2"})
        return pnum(data.get("entr"))

    # ── 1단계: preview (FR-15, NFR-02) ───────────────────────────

    async def preview(self, side: str, code: str, qty: int, price: float,
                      profile: str = "swing") -> dict:
        if side not in ("buy", "sell"):
            raise GuardrailError(f"지원하지 않는 주문 구분: {side}")
        if qty <= 0 or price <= 0:
            raise GuardrailError("수량·가격은 0보다 커야 합니다")

        amount = qty * price
        if amount > self._settings.max_order_amount:
            raise GuardrailError(
                f"1회 주문 금액 상한 초과: {amount:,.0f}원 > "
                f"{self._settings.max_order_amount:,.0f}원"
            )
        today_total = self._today_order_total()
        if today_total + amount > self._settings.daily_order_limit:
            raise GuardrailError(
                f"일일 누적 주문 상한 초과: 오늘 {today_total:,.0f}원 + 이번 {amount:,.0f}원 > "
                f"{self._settings.daily_order_limit:,.0f}원"
            )

        # 계좌 대비 비중 (FR-15)
        weight_pct = None
        try:
            pf = await self.portfolio()
            assets = pf["est_assets"] or pf["total_eval"]
            if assets:
                weight_pct = round(amount / assets * 100, 2)
        except Exception as e:
            log.warning("계좌 조회 실패(비중 미표시): %s", e)

        stop_rate, target_rate = RISK_PARAMS.get(profile, RISK_PARAMS["swing"])
        pv = Preview(
            preview_id=uuid.uuid4().hex,
            side=side, code=code, qty=qty, price=price, amount=amount,
            created_at=self._clock(),
            payload={
                "side": side, "code": code, "qty": qty, "price": price,
                "amount": amount, "weight_pct": weight_pct,
                "suggested_stop": round(price * (1 - stop_rate), 0),
                "suggested_target": round(price * (1 + target_rate), 0),
                "profile": profile,
                "trading_mode": self._settings.trading_mode,
                "expires_in_sec": PREVIEW_TTL_SEC,
            },
        )
        self._previews[pv.preview_id] = pv
        return {"preview_id": pv.preview_id, **pv.payload}

    def _today_order_total(self) -> float:
        today = datetime.now().date()
        with self._sf() as s:
            rows = s.scalars(
                select(OrderLog).where(OrderLog.side.in_(("buy", "sell")))
            ).all()
        return sum(
            r.qty * r.price for r in rows
            if r.ts.date() == today and r.status != "failed"
        )

    # ── 2단계: confirm — 주문 전송의 유일한 경로 (AC-04) ─────────

    async def confirm(self, preview_id: str) -> dict:
        pv = self._previews.get(preview_id)
        if pv is None:
            raise GuardrailError("유효하지 않은 preview_id")
        if pv.used:
            raise GuardrailError("이미 사용된 preview_id (중복 전송 방지)")
        if self._clock() - pv.created_at > PREVIEW_TTL_SEC:
            raise GuardrailError("preview 유효시간(60초) 만료 — 다시 확인해 주세요")
        pv.used = True

        tr_id = "kt10000" if pv.side == "buy" else "kt10001"
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": pv.code,
            "ord_qty": str(pv.qty),
            "ord_uv": str(int(pv.price)),
            "trde_tp": "0",  # 보통(지정가)
            "cond_uv": "",
        }
        log_row = OrderLog(
            ts=datetime.now(), side=pv.side, code=pv.code, qty=pv.qty,
            price=pv.price, preview=pv.payload, status="requested",
        )
        try:
            data, _ = await self._client.call(tr_id, body)
            log_row.kiwoom_ord_no = str(data.get("ord_no", ""))
            log_row.status = "submitted"
            return_msg = data.get("return_msg", "")
        except Exception:
            log_row.status = "failed"
            raise
        finally:
            with self._sf() as s:  # 모든 요청·응답 기록 (NFR-05)
                s.add(log_row)
                s.commit()
        return {"ord_no": log_row.kiwoom_ord_no, "status": log_row.status,
                "message": return_msg}

    # ── 미체결·정정·취소 (FR-09) ─────────────────────────────────

    async def open_orders(self) -> list[dict]:
        rows = await self._client.call_all(
            "ka10075",
            {"all_stk_tp": "0", "trde_tp": "0", "stk_cd": "", "stex_tp": "0"},
            "oso",
        )
        return [
            {
                "ord_no": r.get("ord_no", ""),
                "code": (r.get("stk_cd") or "").strip().removeprefix("A"),
                "name": r.get("stk_nm", ""),
                "status": r.get("ord_stt", ""),
                "side": r.get("io_tp_nm", ""),
                "qty": int(pnum(r.get("ord_qty"))),
                "price": pprice(r.get("ord_pric")),
                "unfilled_qty": int(pnum(r.get("oso_qty"))),
            }
            for r in rows
        ]

    async def modify(self, orig_ord_no: str, code: str, qty: int, price: float) -> dict:
        data, _ = await self._client.call(
            "kt10002",
            {"dmst_stex_tp": "KRX", "orig_ord_no": orig_ord_no, "stk_cd": code,
             "mdfy_qty": str(qty), "mdfy_uv": str(int(price)), "mdfy_cond_uv": ""},
        )
        self._log_simple("modify", code, qty, price, str(data.get("ord_no", "")))
        return {"ord_no": str(data.get("ord_no", ""))}

    async def cancel(self, orig_ord_no: str, code: str, qty: int = 0) -> dict:
        data, _ = await self._client.call(
            "kt10003",
            {"dmst_stex_tp": "KRX", "orig_ord_no": orig_ord_no, "stk_cd": code,
             "cncl_qty": str(qty)},
        )
        self._log_simple("cancel", code, qty, 0.0, str(data.get("ord_no", "")))
        return {"ord_no": str(data.get("ord_no", ""))}

    def _log_simple(self, side: str, code: str, qty: int, price: float, ord_no: str):
        with self._sf() as s:
            s.add(OrderLog(ts=datetime.now(), side=side, code=code, qty=qty,
                           price=price, kiwoom_ord_no=ord_no, status="submitted"))
            s.commit()

    # ── 대사 (설계 §6: 응답 유실 복구) ───────────────────────────

    async def reconcile(self) -> int:
        """미체결 조회로 order_log 상태 갱신. 갱신 건수 반환."""
        open_nos = {o["ord_no"] for o in await self.open_orders()}
        updated = 0
        with self._sf() as s:
            rows = s.scalars(
                select(OrderLog).where(OrderLog.status == "submitted")
            ).all()
            for r in rows:
                if r.kiwoom_ord_no and r.kiwoom_ord_no not in open_nos:
                    r.status = "closed"  # 체결 또는 취소 완료
                    updated += 1
            s.commit()
        return updated

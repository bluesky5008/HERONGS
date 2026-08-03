"""WU-08 — 2단계 주문, 가드레일, 감사 로그, 대사."""

from datetime import datetime

import pytest
from sqlalchemy import select

from herongs.models import OrderLog
from herongs.services.orders import GuardrailError, OrderService

from .conftest import FakeTime, make_kiwoom_client

ACCOUNT_ROUTES = {
    "kt00018": {"tot_pur_amt": "1000000", "tot_evlt_amt": "1100000",
                "tot_evlt_pl": "100000", "tot_prft_rt": "10.0",
                "prsm_dpst_aset_amt": "2000000",
                "acnt_evlt_remn_indv_tot": [
                    {"stk_cd": "A005930", "stk_nm": "삼성전자", "rmnd_qty": "10",
                     "pur_pric": "70000", "cur_prc": "75000",
                     "evltv_prft": "50000", "prft_rt": "7.1"}]},
    "kt00001": {"entr": "500000"},
    "kt10000": {"ord_no": "0000138"},
    "kt10001": {"ord_no": "0000139"},
    "kt10002": {"ord_no": "0000140"},
    "ka10075": {"oso": []},
}


def make_order_service(sf, settings, clock=None):
    client = make_kiwoom_client(ACCOUNT_ROUTES, settings)
    ft = FakeTime()
    return OrderService(client, sf, settings, clock=clock or ft.clock), ft


async def test_preview_blocks_over_limit(sf, settings):
    svc, _ = make_order_service(sf, settings)
    # 1회 상한 500만원 초과 → 사유와 함께 차단 (AC-10)
    with pytest.raises(GuardrailError, match="1회 주문 금액 상한"):
        await svc.preview("buy", "005930", qty=100, price=70000)


async def test_preview_daily_limit(sf, settings):
    with sf() as s:
        s.add(OrderLog(ts=datetime.now(), side="buy", code="005930", qty=100,
                       price=180000, status="submitted"))  # 오늘 이미 1,800만원
        s.commit()
    svc, _ = make_order_service(sf, settings)
    with pytest.raises(GuardrailError, match="일일 누적"):
        await svc.preview("buy", "005930", qty=50, price=70000)  # +350만원 > 2,000만원


async def test_preview_confirm_flow(sf, settings):
    svc, _ = make_order_service(sf, settings)
    pv = await svc.preview("buy", "005930", qty=10, price=70000)
    # preview에 예상금액·비중·손절/목표 제안 포함 (FR-15)
    assert pv["amount"] == 700000
    assert pv["weight_pct"] == 35.0  # 70만 / 200만
    assert pv["suggested_stop"] < 70000 < pv["suggested_target"]

    result = await svc.confirm(pv["preview_id"])
    assert result["ord_no"] == "0000138"
    with sf() as s:
        row = s.scalars(select(OrderLog)).one()
        assert row.status == "submitted"
        assert row.preview["amount"] == 700000  # 감사 로그 (NFR-05)


async def test_confirm_requires_valid_preview(sf, settings):
    svc, _ = make_order_service(sf, settings)
    with pytest.raises(GuardrailError, match="유효하지 않은"):
        await svc.confirm("no-such-id")  # AC-04: preview 없이 전송 불가


async def test_confirm_rejects_reuse_and_expiry(sf, settings):
    ft = FakeTime()
    svc, _ = make_order_service(sf, settings, clock=ft.clock)
    pv = await svc.preview("sell", "005930", qty=1, price=70000)
    await svc.confirm(pv["preview_id"])
    with pytest.raises(GuardrailError, match="이미 사용된"):
        await svc.confirm(pv["preview_id"])  # 중복 전송 방지 (설계 §6)

    pv2 = await svc.preview("sell", "005930", qty=1, price=70000)
    ft.now += 61.0  # TTL 60초 경과
    with pytest.raises(GuardrailError, match="만료"):
        await svc.confirm(pv2["preview_id"])


async def test_holdings_and_reconcile(sf, settings):
    svc, _ = make_order_service(sf, settings)
    holdings = await svc.holdings()
    assert holdings["005930"].avg_price == 70000.0
    with sf() as s:
        s.add(OrderLog(ts=datetime.now(), side="buy", code="005930", qty=1,
                       price=1000, kiwoom_ord_no="0000200", status="submitted"))
        s.commit()
    updated = await svc.reconcile()  # 미체결 목록에 없음 → closed
    assert updated == 1

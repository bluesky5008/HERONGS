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
    "kt00001": {"entr": "500000", "ord_alow_amt": "000000499994528"},
    "ka10001": {"stk_nm": "삼성전자", "cur_prc": "-230250", "flu_rt": "-3.86",
                "base_pric": "239500"},
    "ka10004": {  # 실응답 구조: 1단만 fpr, 2단부터 {n}th_pre (2026-08-04 실검증)
        "bid_req_base_tm": "131243",
        "sel_fpr_bid": "-230500", "sel_fpr_req": "31576",
        "sel_2th_pre_bid": "-231000", "sel_2th_pre_req": "29198",
        "sel_3th_pre_bid": "-231500", "sel_3th_pre_req": "14622",
        "buy_fpr_bid": "-230000", "buy_fpr_req": "17889",
        "buy_2th_pre_bid": "-229500", "buy_2th_pre_req": "126297",
        "tot_sel_req": "148667", "tot_buy_req": "941529",
    },
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


def recording_routes(seen: list, base: dict) -> dict:
    """호출된 TR을 seen에 기록하는 라우트 (호출 수 검증용)."""
    def wrap(tr, body):
        def handler(_request):
            seen.append(tr)
            return body
        return handler
    return {tr: wrap(tr, body) for tr, body in base.items()}


async def test_quote_parses_orderbook_and_account(sf, settings):
    svc, _ = make_order_service(sf, settings)
    q = await svc.quote("005930")
    assert q["cur_price"] == 230250 and q["change_rate"] == -3.86  # 등락 부호 제거
    ob = q["orderbook"]
    assert ob["base_time"] == "13:12:43"
    # 1단은 fpr 규칙 — 놓치면 최우선 호가가 통째로 빠진다 (설계 R-2)
    assert ob["asks"][0] == {"price": 230500, "qty": 31576}
    assert ob["bids"][0] == {"price": 230000, "qty": 17889}
    assert [a["price"] for a in ob["asks"]] == [230500, 231000, 231500]  # 없는 단은 제외
    assert ob["total_ask_qty"] == 148667 and ob["total_bid_qty"] == 941529
    assert q["holding_qty"] == 10  # kt00018 보유 10주
    assert q["orderable_cash"] == 499994528  # 예수금이 아닌 주문가능금액 (D-5)
    assert q["errors"] == []


async def test_quote_without_account_skips_account_trs(sf, settings):
    seen: list[str] = []
    svc = OrderService(
        make_kiwoom_client(recording_routes(seen, ACCOUNT_ROUTES), settings), sf, settings
    )
    q = await svc.quote("005930", with_account=False)
    assert q["holding_qty"] is None and q["orderable_cash"] is None
    assert sorted(seen) == ["ka10001", "ka10004"]  # 자동 갱신은 2 TR만 (NFR-08, AC-17)


async def test_quote_absorbs_partial_failure(sf, settings):
    routes = {**ACCOUNT_ROUTES, "ka10004": {"return_code": 20, "return_msg": "호가 조회 실패"}}
    svc = OrderService(make_kiwoom_client(routes, settings), sf, settings)
    q = await svc.quote("005930")
    assert q["orderbook"] is None and q["errors"] == ["orderbook"]
    assert q["cur_price"] == 230250 and q["holding_qty"] == 10  # 나머지는 정상 (NFR-07)


async def test_modify_blocks_over_limit(sf, settings):
    svc, _ = make_order_service(sf, settings)
    # 정정은 preview 미경유 → 1회 상한을 직접 검사 (DCR-002)
    with pytest.raises(GuardrailError, match="1회 주문 금액 상한"):
        await svc.modify("0000138", "005930", qty=100, price=70000)


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

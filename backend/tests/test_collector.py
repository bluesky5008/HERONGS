"""WU-06 — 깔때기 수집, 위생 필터, 일봉 증분 적재."""

from herongs.models import DailyPrice, Instrument
from herongs.services.collector import Collector

from .conftest import make_kiwoom_client

CHART_ROWS = [
    {"dt": "20260724", "cur_prc": "70000", "open_pric": "69000", "high_pric": "70500",
     "low_pric": "68500", "trde_qty": "1000", "trde_prica": "70"},
    {"dt": "20260723", "cur_prc": "69000", "open_pric": "68000", "high_pric": "69500",
     "low_pric": "67500", "trde_qty": "900", "trde_prica": "62"},
]

ROUTES = {
    "ka10023": {"trde_qty_sdnin": [
        {"stk_cd": "005930", "stk_nm": "삼성전자", "flu_rt": "+2.5"}]},
    "ka10032": {"trde_prica_upper": [
        {"stk_cd": "005930", "stk_nm": "삼성전자", "trde_prica": "500000"},
        {"stk_cd": "000660", "stk_nm": "SK하이닉스", "trde_prica": "300000"}]},
    "ka10027": {"pred_pre_flu_rt_upper": []},
    "ka10016": {"ntl_pric": []},
    "ka90009": {"frgnr_orgn_trde_upper": [
        {"for_netprps_stk_cd": "035420", "for_netprps_stk_nm": "NAVER",
         "orgn_netprps_stk_cd": "005930", "orgn_netprps_stk_nm": "삼성전자"}]},
    "ka10001": {"stk_nm": "삼성전자", "per": "9.5", "pbr": "1.1", "roe": "10.2",
                "crd_rt": "0.5"},
    "ka10081": {"stk_dt_pole_chart_qry": CHART_ROWS},
    "ka10131": {"orgn_frgnr_cont_trde_prst": [
        {"stk_cd": "005930", "frgnr_cont_netprps_dys": "3", "orgn_cont_netprps_dys": "1"}]},
}


async def test_collect_candidates_union_dedup(sf, settings):
    col = Collector(make_kiwoom_client(ROUTES, settings), sf, settings)
    found = await col.collect_candidates()
    assert set(found) == {"005930", "000660", "035420"}  # 합집합·중복 제거
    assert found["005930"]["name"] == "삼성전자"


async def test_hygiene_filter_drops_flagged_and_illiquid(sf, settings):
    with sf() as s:
        s.add(Instrument(code="000660", is_halted=True))  # 거래정지
        s.add(Instrument(code="035420", avg_trading_value=1_000_000))  # 저유동성
        s.add(Instrument(code="005930", avg_trading_value=5_000_000_000))
        s.commit()
    col = Collector(make_kiwoom_client(ROUTES, settings), sf, settings)
    kept, dropped = col.hygiene_filter(["005930", "000660", "035420"])
    assert kept == ["005930"]
    assert set(dropped) == {"000660", "035420"}  # AC-07 단위 검증


async def test_ingest_daily_incremental(sf, settings):
    col = Collector(make_kiwoom_client(ROUTES, settings), sf, settings)
    await col.ingest_daily("005930")
    with sf() as s:
        assert s.query(DailyPrice).count() == 2
    await col.ingest_daily("005930")  # 재실행해도 중복 적재 없음 (NFR-06 증분)
    with sf() as s:
        assert s.query(DailyPrice).count() == 2
        inst = s.get(Instrument, "005930")
        assert inst.avg_trading_value > 0  # 위생 필터 근거 갱신


async def test_scan_end_to_end_excludes_halted(sf, settings):
    with sf() as s:
        s.add(Instrument(code="000660", is_halted=True))
        s.commit()
    col = Collector(make_kiwoom_client(ROUTES, settings), sf, settings)
    candidates = await col.scan()
    codes = {c.code for c in candidates}
    assert "000660" not in codes  # AC-07
    assert "005930" in codes
    samsung = next(c for c in candidates if c.code == "005930")
    assert samsung.per == 9.5
    assert len(samsung.foreign_net) == 3  # ka10131 연속 순매수 3일
    assert samsung.closes == [69000.0, 70000.0]  # 과거→최신


async def test_condition_source_feeds_candidates(sf, settings):
    from herongs.models import ConditionMap

    with sf() as s:
        s.add(ConditionMap(seq="0", name="HERONGS_SWING", profile="swing", enabled=True))
        s.commit()

    async def cond_source(seq):
        assert seq == "0"
        return ["123456"]

    col = Collector(make_kiwoom_client(ROUTES, settings), sf, settings,
                    condition_source=cond_source)
    found = await col.collect_candidates()
    assert "123456" in found  # FR-13: 조건검색 결과가 후보군에 반영 (AC-08 단위)

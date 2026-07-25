"""WU-07 — 추천 생성, 의견, 성과 추적."""

from datetime import date, datetime

from sqlalchemy import select

from herongs.models import DailyPrice, Opinion, Recommendation
from herongs.scoring import Candidate
from herongs.scoring.opinion import Holding
from herongs.services.collector import Collector
from herongs.services.recommendation import RecommendationService

from .conftest import make_kiwoom_client
from .test_collector import ROUTES


def make_service(sf, settings, notify=None):
    col = Collector(make_kiwoom_client(ROUTES, settings), sf, settings)
    return RecommendationService(col, sf, settings, notify=notify)


async def test_run_scan_saves_recommendations_with_rationale(sf, settings):
    alerts = []

    async def notify(kind, payload):
        alerts.append((kind, payload))

    svc = make_service(sf, settings, notify)
    results = await svc.run_scan()
    assert set(results) == {"long", "swing", "scalp"}  # 전략별 목록 (AC-02)
    for entries in results.values():
        assert len(entries) <= settings.recommend_top_n
        for e in entries:
            assert e["breakdown"]  # 근거 포함 (FR-05)
    with sf() as s:
        recs = s.scalars(select(Recommendation)).all()
    assert all(r.score_breakdown for r in recs)
    # 신규 진입 알림 (FR-11) — 추천이 생겼다면 알림도 발생
    total = sum(len(v) for v in results.values())
    if total:
        assert alerts


async def test_opinions_saved_and_stop_loss_alerts(sf, settings):
    svc = make_service(sf, settings)
    candidate = Candidate(code="005930", name="삼성전자",
                          closes=[100.0] * 130, volumes=[1000.0] * 130)
    holdings = {"005930": Holding(avg_price=120.0, qty=10)}  # 현재가 100 < 손절선
    out = svc.opinions_for(candidate, holdings)
    assert len(out) == 3  # 3개 전략 관점 (AC-03)
    swing = next(o for o in out if o["profile"] == "swing")
    assert swing["stance"] == "sell"
    assert swing["override"] == "stop_loss"  # 매입가 반영 (FR-07)
    assert swing["holding"]["pnl_pct"] < 0
    with sf() as s:
        assert s.query(Opinion).count() == 3


async def test_evaluate_performance_and_report(sf, settings):
    svc = make_service(sf, settings)
    with sf() as s:
        s.add(Recommendation(id=1, ts=datetime(2026, 7, 20, 10, 0), profile="swing",
                             code="005930", score=80.0, score_breakdown={}, rank=1,
                             regime="bull", base_price=100.0))
        for i, (d, close) in enumerate([(21, 105.0), (22, 110.0), (23, 95.0)]):
            s.add(DailyPrice(code="005930", date=date(2026, 7, d), open=close,
                             high=close, low=close, close=close, volume=1,
                             trading_value=1.0))
        s.commit()
    saved = svc.evaluate_performance()
    assert saved == 1  # 경과 1영업일만 충족 (5/20일은 아직)
    report = svc.performance_report()
    assert report["swing"][1]["count"] == 1
    assert report["swing"][1]["hit_rate"] == 100.0  # +5% → 적중
    assert report["swing"][1]["avg_return"] == 5.0
    hist = svc.history("swing")
    assert hist[0]["returns"][1] == 5.0  # AC-09: 이력에서 경과 수익률 확인


async def test_bear_regime_reduces_swing_recommendations(sf, settings):
    from herongs.models import MarketRegime

    with sf() as s:
        s.add(MarketRegime(date=date.today(), label="bear", metrics={}))
        s.commit()
    svc = make_service(sf, settings)
    assert svc.current_regime() == "bear"
    results = await svc.run_scan()
    # 하락 국면: 스윙 추천 개수 상한이 절반으로 (FR-14)
    assert len(results["swing"]) <= max(1, settings.recommend_top_n // 2)

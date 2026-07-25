"""WU-05 — 스코어링 프로파일 + §5.6 의견 판정."""

import json

from herongs.db import init_db, set_setting
from herongs.scoring import PROFILES, Candidate, decide_stance, load_weights
from herongs.scoring.base import Score
from herongs.scoring.opinion import Holding
from herongs.scoring.regime import classify_regime


def good_long_candidate() -> Candidate:
    closes = [float(x) for x in range(100, 250)]  # 장기 상승 추세
    return Candidate(
        code="005930",
        closes=closes,
        volumes=[1000.0] * 150,
        per=6.0,
        pbr=0.8,
        roe=16.0,
        foreign_net=[1, 1, 1, 1, 1],
    )


def test_long_profile_scores_high_for_value_stock():
    score = PROFILES()["long"].score(good_long_candidate())
    assert score.total >= 90
    assert set(score.breakdown) == {"value", "quality", "trend", "supply"}
    # 근거(FR-05): 그룹별 기여 점수와 세부 수치 포함
    assert score.breakdown["value"]["points"] > 0
    assert score.breakdown["value"]["details"]["per"] == 6.0


def test_scalp_profile_uses_realtime_metrics():
    c = Candidate(
        code="000001",
        change_rate=7.0,
        rt_volume_ratio=3.0,
        strength=150.0,
        bid_ask_imbalance=1.0,
        trading_value=6_000_000_000,
    )
    score = PROFILES()["scalp"].score(c)
    assert score.total >= 90


def test_weights_loaded_from_setting():
    init_db(":memory:")
    from herongs.db import SessionLocal

    with SessionLocal() as s:
        set_setting(s, "weights.long", json.dumps({"value": 100, "quality": 0, "trend": 0, "supply": 0}))
        w = load_weights(s, "long")
        assert w["value"] == 100
        score = PROFILES(s)["long"].score(good_long_candidate())
        assert score.breakdown["quality"]["points"] == 0


# ── §5.6 판정 4단계 ──────────────────────────────────────────────


def s(total: float) -> Score:
    return Score(total=total, breakdown={})


def test_score_mapping_unheld():
    assert decide_stance("swing", s(75), 100)["stance"] == "buy"
    assert decide_stance("swing", s(55), 100)["stance"] == "watch"
    assert decide_stance("swing", s(30), 100)["stance"] == "avoid"


def test_score_mapping_held():
    h = Holding(avg_price=100, qty=10)
    assert decide_stance("swing", s(75), 100, holding=h)["stance"] == "hold"
    assert decide_stance("swing", s(55), 100, holding=h)["stance"] == "hold"
    assert decide_stance("swing", s(30), 100, holding=h)["stance"] == "sell"


def test_override_stop_loss_beats_score():
    # 우선 규칙: 손절선 도달은 점수가 높아도 매도 (리스크 차단 우선)
    h = Holding(avg_price=100, qty=10, stop_price=90)
    r = decide_stance("swing", s(95), current_price=89, holding=h)
    assert r["stance"] == "sell"
    assert r["override"] == "stop_loss"


def test_override_take_profit():
    h = Holding(avg_price=100, qty=10, target_price=130)
    r = decide_stance("long", s(80), current_price=135, holding=h)
    assert r["stance"] == "sell"
    assert r["override"] == "take_profit"


def test_override_halted_unheld_refuses():
    r = decide_stance("swing", s(95), 100, is_halted=True)
    assert r["stance"] == "avoid"
    assert r["override"] == "excluded"


def test_hysteresis_keeps_buy_until_67():
    # "매수였던 종목은 67점 미만으로 떨어져야 관망 전환" (설계 §5.6)
    r = decide_stance("swing", s(68), 100, prev_band="high")
    assert r["stance"] == "buy"
    assert r["hysteresis_applied"]
    r = decide_stance("swing", s(66), 100, prev_band="high")
    assert r["stance"] == "watch"
    assert not r["hysteresis_applied"]


def test_bear_regime_raises_buy_threshold_for_swing_only():
    # 하락 국면: 스윙·단타 매수 기준 80점, 장기는 70점 유지
    assert decide_stance("swing", s(75), 100, regime="bear")["stance"] == "watch"
    assert decide_stance("swing", s(85), 100, regime="bear")["stance"] == "buy"
    assert decide_stance("long", s(75), 100, regime="bear")["stance"] == "buy"


def test_classify_regime():
    up = [float(x) for x in range(100, 130)]
    down = [float(x) for x in range(130, 100, -1)]
    assert classify_regime(up, up)[0] == "bull"
    assert classify_regime(down, down)[0] == "bear"
    assert classify_regime(up, down)[0] == "sideways"

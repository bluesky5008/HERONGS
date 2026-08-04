"""매수/매도/홀딩 의견 판정 — 설계 §5.6의 4단계 (FR-06/07).

1) 점수 산출(profiles) → 2) 우선 규칙(오버라이드) → 3) 점수→의견 매핑(히스테리시스)
→ 4) 시장 국면 보정. 리스크 차단이 종목 매력도보다 항상 우선한다.
"""

from dataclasses import dataclass

from .base import Score

BUY_TH = 70.0
WATCH_TH = 40.0
HYSTERESIS = 3.0
BEAR_BUY_PENALTY = 10.0  # 하락 국면: 스윙·단타 매수 기준 +10 (장기 미적용)

# 전략별 손절/목표 제안 배율 (FR-15): (손절률, 목표률)
RISK_PARAMS = {"long": (0.10, 0.20), "swing": (0.05, 0.10), "scalp": (0.02, 0.03)}


@dataclass
class Holding:
    """보유 정보 (FR-07)."""

    avg_price: float
    qty: int
    stop_price: float | None = None  # 전략별 손절선
    target_price: float | None = None  # 목표가
    orderable_qty: int | None = None  # 매매가능수량 — 미체결 매도분 제외 (FR-22)


def _band(score: float, buy_th: float) -> str:
    if score >= buy_th:
        return "high"
    if score >= WATCH_TH:
        return "mid"
    return "low"


def decide_stance(
    profile_key: str,
    score: Score,
    current_price: float,
    holding: Holding | None = None,
    prev_band: str | None = None,
    regime: str = "sideways",
    is_managed: bool = False,
    is_halted: bool = False,
) -> dict:
    """rationale dict 반환: stance, band, score, breakdown, override, regime 등 (FR-05)."""
    # 4) 국면 보정 — 매핑 기준점에 선반영 (설계 §5.6-4)
    buy_th = BUY_TH
    regime_adjusted = False
    if regime == "bear" and profile_key in ("swing", "scalp"):
        buy_th += BEAR_BUY_PENALTY
        regime_adjusted = True

    # 2) 우선 규칙(오버라이드) — 점수보다 먼저 평가
    override = None
    if is_halted or is_managed:
        override = "excluded"  # 거래정지·관리종목 (FR-12)
        stance = "sell" if holding else "avoid"
    elif holding and holding.stop_price and current_price <= holding.stop_price:
        override = "stop_loss"
        stance = "sell"
    elif holding and holding.target_price and current_price >= holding.target_price:
        override = "take_profit"
        stance = "sell"

    hysteresis_applied = False
    if override is None:
        # 3) 점수 → 의견 매핑 + 히스테리시스(경계 ±3, 직전 밴드 유지)
        band = _band(score.total, buy_th)
        if prev_band and band != prev_band:
            boundary = buy_th if "high" in (band, prev_band) else WATCH_TH
            if abs(score.total - boundary) < HYSTERESIS:
                band = prev_band
                hysteresis_applied = True
        if holding:
            stance = {"high": "hold", "mid": "hold", "low": "sell"}[band]
        else:
            stance = {"high": "buy", "mid": "watch", "low": "avoid"}[band]
    else:
        band = _band(score.total, buy_th)

    return {
        "stance": stance,
        "band": band,
        "score": score.total,
        "score_breakdown": score.breakdown,
        "override": override,
        "regime": regime,
        "buy_threshold": buy_th,
        "regime_adjusted": regime_adjusted,
        "hysteresis_applied": hysteresis_applied,
        "held": holding is not None,
    }

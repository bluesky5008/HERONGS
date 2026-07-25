"""전략 프로파일 3종 — 부록 B 초기 가중치, setting 테이블에서 튜닝 (FR-04)."""

import json

from sqlalchemy.orm import Session

from .. import indicators as ind
from ..db import get_setting
from ..indicators import clamp01
from .base import Candidate, Profile, Score

# 부록 B 초기 가중치 (합계 100)
DEFAULT_WEIGHTS = {
    "long": {"value": 40, "quality": 25, "trend": 20, "supply": 15},
    "swing": {"supply": 35, "trend": 30, "momentum": 25, "risk": 10},
    "scalp": {"rt_momentum": 50, "strength": 30, "risk": 20},
}


class LongProfile(Profile):
    key = "long"

    def score(self, c: Candidate) -> Score:
        # 가치: PER 0~12, PBR 0.2~1.5가 우량 구간 (부록 A 기준)
        per_s = 0.0
        if c.per is not None and c.per > 0:
            per_s = 1.0 if c.per <= 8 else 0.7 if c.per <= 12 else 0.3 if c.per <= 20 else 0.0
        pbr_s = 0.0
        if c.pbr is not None and c.pbr >= 0.2:
            pbr_s = 1.0 if c.pbr <= 1.0 else 0.7 if c.pbr <= 1.5 else 0.2 if c.pbr <= 3 else 0.0
        value = (per_s + pbr_s) / 2

        # 퀄리티: ROE 8% 이상 우량, 16%에서 만점
        quality = clamp01((c.roe or 0.0) / 16.0)

        # 추세: 120일선 위 + 20일선이 60일선 위
        ma120 = ind.sma(c.closes, 120)
        above120 = 1.0 if ma120 and c.closes and c.closes[-1] >= ma120 else 0.0
        ma20, ma60 = ind.sma(c.closes, 20), ind.sma(c.closes, 60)
        mid_trend = 1.0 if ma20 and ma60 and ma20 > ma60 else 0.0
        trend = above120 * 0.7 + mid_trend * 0.3

        # 수급: 외국인 연속 순매수 5일에서 만점
        f_days = ind.consecutive_positive(c.foreign_net)
        supply = clamp01(f_days / 5.0)

        return self._build({
            "value": (value, {"per": c.per, "pbr": c.pbr}),
            "quality": (quality, {"roe": c.roe}),
            "trend": (trend, {"above_ma120": bool(above120), "ma20_gt_ma60": bool(mid_trend)}),
            "supply": (supply, {"foreign_net_days": f_days}),
        })


class SwingProfile(Profile):
    key = "swing"

    def score(self, c: Candidate) -> Score:
        # 수급: 외국인/기관 연속 순매수 (3일 기준 충족, 5일 만점)
        f_days = ind.consecutive_positive(c.foreign_net)
        i_days = ind.consecutive_positive(c.inst_net)
        supply = clamp01(max(f_days, i_days) / 5.0)

        # 추세: 정배열 또는 최근 골든크로스
        aligned = ind.is_aligned(c.closes)
        gc = ind.golden_cross_within(c.closes, 5)
        trend = 1.0 if aligned else 0.7 if gc else 0.0

        # 모멘텀: 거래량 배율(3배 만점) + 60일 고점 근접(-5% 이내 만점)
        vr = ind.volume_ratio(c.volumes) or 0.0
        prox = ind.high_proximity(c.closes, 60) or 0.0
        momentum = clamp01(vr / 3.0) * 0.5 + clamp01((prox - 90.0) / 5.0) * 0.5

        # 리스크: 신용비율 낮을수록 양호 (0%=만점, 10%↑=0점)
        risk = 1.0 - clamp01((c.credit_ratio or 0.0) / 10.0)

        return self._build({
            "supply": (supply, {"foreign_net_days": f_days, "inst_net_days": i_days}),
            "trend": (trend, {"aligned": aligned, "golden_cross": gc}),
            "momentum": (momentum, {"volume_ratio": round(vr, 2), "high_proximity": round(prox, 1)}),
            "risk": (risk, {"credit_ratio": c.credit_ratio}),
        })


class ScalpProfile(Profile):
    key = "scalp"

    def score(self, c: Candidate) -> Score:
        # 실시간 모멘텀: 등락률 +2~+15% 유효 구간, 거래량 배율 3배 만점
        cr = c.change_rate
        cr_s = clamp01((cr - 2.0) / 5.0) if 2.0 <= cr <= 15.0 else 0.0
        vr_s = clamp01(c.rt_volume_ratio / 3.0)
        rt_momentum = cr_s * 0.5 + vr_s * 0.5

        # 체결: 체결강도 120 기준, 150 만점 + 매수호가 우위
        strength = clamp01((c.strength - 100.0) / 50.0) * 0.7 + clamp01(c.bid_ask_imbalance) * 0.3

        # 리스크: 유동성(거래대금 50억 만점)
        risk = clamp01(c.trading_value / 5_000_000_000)

        return self._build({
            "rt_momentum": (rt_momentum, {"change_rate": cr, "rt_volume_ratio": c.rt_volume_ratio}),
            "strength": (strength, {"strength": c.strength, "bid_ask_imbalance": c.bid_ask_imbalance}),
            "risk": (risk, {"trading_value": c.trading_value}),
        })


_CLASSES = {"long": LongProfile, "swing": SwingProfile, "scalp": ScalpProfile}


def load_weights(session: Session | None, profile_key: str) -> dict[str, float]:
    """setting 테이블의 weights.<profile> (JSON) 우선, 없으면 부록 B 기본값."""
    if session is not None:
        raw = get_setting(session, f"weights.{profile_key}")
        if raw:
            try:
                return json.loads(raw)
            except ValueError:
                pass
    return dict(DEFAULT_WEIGHTS[profile_key])


def PROFILES(session: Session | None = None) -> dict[str, Profile]:
    """가중치가 로드된 프로파일 3종."""
    return {k: cls(load_weights(session, k)) for k, cls in _CLASSES.items()}

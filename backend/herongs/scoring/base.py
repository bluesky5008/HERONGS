"""Profile 플러그인 인터페이스 (설계 §2 ScoringEngine)."""

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """스코어링 입력 — Collector가 채우고 프로파일이 소비한다."""

    code: str
    name: str = ""
    closes: list[float] = field(default_factory=list)  # 일봉 종가, 과거→최신
    volumes: list[float] = field(default_factory=list)
    trading_value: float = 0.0  # 당일 거래대금(원)
    # 기본 지표 (ka10001)
    per: float | None = None
    pbr: float | None = None
    roe: float | None = None
    # 수급 (ka10131 등): 일별 순매수량, 과거→최신
    foreign_net: list[float] = field(default_factory=list)
    inst_net: list[float] = field(default_factory=list)
    credit_ratio: float | None = None  # 신용비율(%)
    # 실시간 (단타, 0B/0D)
    change_rate: float = 0.0  # 당일 등락률(%)
    strength: float = 0.0  # 체결강도
    rt_volume_ratio: float = 0.0  # 전일 동시간 대비 거래량 배율
    bid_ask_imbalance: float = 0.0  # 매수호가잔량/매도호가잔량 - 1


@dataclass
class Score:
    """0~100 총점 + 지표 그룹별 기여 내역 (FR-05)."""

    total: float
    breakdown: dict  # {group: {"weight": w, "subscore": 0~1, "points": w*subscore, "details": {…}}}


class Profile:
    """전략 프로파일 인터페이스. Phase 2 LLM 보정도 이 인터페이스로 확장한다."""

    key: str = ""

    def __init__(self, weights: dict[str, float]):
        self.weights = weights

    def score(self, c: Candidate) -> Score:  # pragma: no cover - 추상
        raise NotImplementedError

    def _build(self, groups: dict[str, tuple[float, dict]]) -> Score:
        """groups: {그룹명: (subscore 0~1, 세부 수치)} → Score."""
        breakdown = {}
        total = 0.0
        for name, (sub, details) in groups.items():
            w = self.weights.get(name, 0.0)
            pts = round(w * sub, 1)
            total += pts
            breakdown[name] = {
                "weight": w,
                "subscore": round(sub, 3),
                "points": pts,
                "details": details,
            }
        return Score(total=round(total, 1), breakdown=breakdown)

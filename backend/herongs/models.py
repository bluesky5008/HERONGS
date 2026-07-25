"""데이터 모델 — 설계 §3의 11개 테이블."""

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    """종목 마스터 + 위생 필터 플래그 (FR-12)."""

    __tablename__ = "instrument"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), default="")
    market: Mapped[str] = mapped_column(String(10), default="")  # KOSPI | KOSDAQ
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False)  # 관리종목
    is_halted: Mapped[bool] = mapped_column(Boolean, default=False)  # 거래정지
    is_warned: Mapped[bool] = mapped_column(Boolean, default=False)  # 투자위험/경고
    avg_trading_value: Mapped[float] = mapped_column(Float, default=0.0)  # 일평균 거래대금(원)


class DailyPrice(Base):
    """일봉 적재 (NFR-06)."""

    __tablename__ = "daily_price"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    trading_value: Mapped[float] = mapped_column(Float, default=0.0)


class Recommendation(Base):
    """추천 이력 (FR-04/05/16)."""

    __tablename__ = "recommendation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    profile: Mapped[str] = mapped_column(String(10))  # long | swing | scalp
    code: Mapped[str] = mapped_column(String(12))
    score: Mapped[float] = mapped_column(Float)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    rank: Mapped[int] = mapped_column(Integer)
    regime: Mapped[str] = mapped_column(String(10), default="")
    base_price: Mapped[float] = mapped_column(Float, default=0.0)  # 성과 추적 기준가


class RecommendationPerf(Base):
    """추천 경과 수익률 (FR-16)."""

    __tablename__ = "recommendation_perf"

    rec_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation.id"), primary_key=True
    )
    horizon: Mapped[int] = mapped_column(Integer, primary_key=True)  # 1 | 5 | 20 영업일
    return_pct: Mapped[float] = mapped_column(Float)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime)


class Opinion(Base):
    """개별 종목 의견 이력 (FR-06/07, §5.6)."""

    __tablename__ = "opinion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    code: Mapped[str] = mapped_column(String(12))
    profile: Mapped[str] = mapped_column(String(10))
    stance: Mapped[str] = mapped_column(String(10))  # buy | sell | hold | watch | avoid
    rationale: Mapped[dict] = mapped_column(JSON, default=dict)


class OrderLog(Base):
    """주문 감사 로그 (FR-08, NFR-05)."""

    __tablename__ = "order_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    side: Mapped[str] = mapped_column(String(6))  # buy | sell | modify | cancel
    code: Mapped[str] = mapped_column(String(12))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    kiwoom_ord_no: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="requested")


class ConditionMap(Base):
    """HTS 조건검색식 ↔ 전략 매핑 (FR-13)."""

    __tablename__ = "condition_map"

    seq: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    profile: Mapped[str] = mapped_column(String(10), default="")  # 매핑 전략, 빈 값=미매핑
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketRegime(Base):
    """시장 국면 (FR-14)."""

    __tablename__ = "market_regime"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    label: Mapped[str] = mapped_column(String(10))  # bull | bear | sideways
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class Watchlist(Base):
    """관심종목 (FR-10)."""

    __tablename__ = "watchlist"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    group_name: Mapped[str] = mapped_column(String(30), default="default")
    added_at: Mapped[datetime] = mapped_column(DateTime)


class AlertLog(Base):
    """알림 이력 (FR-11/17)."""

    __tablename__ = "alert_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Base):
    """가중치·가드레일·도메인 모드 등 런타임 설정."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000))

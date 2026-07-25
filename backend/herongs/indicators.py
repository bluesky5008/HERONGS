"""IndicatorEngine — 파생 지표 순수 함수 (설계 §2). 시계열은 과거→최신 순."""


def sma(values: list[float], n: int) -> float | None:
    """단순이동평균. 데이터 부족 시 None."""
    if len(values) < n or n <= 0:
        return None
    return sum(values[-n:]) / n


def disparity(values: list[float], n: int) -> float | None:
    """이격도(%): 현재가 / n일 이평 * 100."""
    ma = sma(values, n)
    if ma is None or ma == 0:
        return None
    return values[-1] / ma * 100.0


def volume_ratio(volumes: list[float], n: int = 20) -> float | None:
    """거래량 배율: 당일 거래량 / 직전 n일 평균."""
    if len(volumes) < n + 1:
        return None
    avg = sum(volumes[-n - 1 : -1]) / n
    if avg == 0:
        return None
    return volumes[-1] / avg


def is_aligned(closes: list[float]) -> bool:
    """이평선 정배열 (5 > 20 > 60)."""
    ma5, ma20, ma60 = sma(closes, 5), sma(closes, 20), sma(closes, 60)
    if None in (ma5, ma20, ma60):
        return False
    return ma5 > ma20 > ma60


def golden_cross_within(closes: list[float], days: int = 5) -> bool:
    """최근 days일 이내 5일선이 20일선을 상향 돌파했는가."""
    for back in range(days):
        end = len(closes) - back
        cur5, cur20 = sma(closes[:end], 5), sma(closes[:end], 20)
        pre5, pre20 = sma(closes[: end - 1], 5), sma(closes[: end - 1], 20)
        if None in (cur5, cur20, pre5, pre20):
            return False
        if cur5 > cur20 and pre5 <= pre20:
            return True
    return False


def rate_of_change(values: list[float], n: int) -> float | None:
    """n일 수익률(%)."""
    if len(values) < n + 1 or values[-n - 1] == 0:
        return None
    return (values[-1] / values[-n - 1] - 1.0) * 100.0


def high_proximity(closes: list[float], n: int = 60) -> float | None:
    """n일 최고가 대비 현재가 위치(%). 100이면 신고가."""
    if not closes:
        return None
    window = closes[-n:]
    peak = max(window)
    if peak == 0:
        return None
    return closes[-1] / peak * 100.0


def consecutive_positive(values: list[float]) -> int:
    """끝에서부터 연속 양수 개수 (예: 연속 순매수 일수)."""
    count = 0
    for v in reversed(values):
        if v > 0:
            count += 1
        else:
            break
    return count


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

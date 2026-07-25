"""공용 파서 — 키움 응답의 숫자 문자열 처리 ("+74800", "-1,234" 등)."""


def pnum(s, default: float = 0.0) -> float:
    """부호 유지 숫자 파싱. 빈 값·비숫자는 default."""
    if s is None:
        return default
    text = str(s).strip().replace(",", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def price(s, default: float = 0.0) -> float:
    """가격 파싱 — 키움은 등락 방향을 부호로 붙이므로 절댓값."""
    return abs(pnum(s, default))

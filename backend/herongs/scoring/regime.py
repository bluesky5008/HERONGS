"""시장 국면 판단 (FR-14) — KOSPI/KOSDAQ 지수 20일선 대비 위치 + 등락 종목 수."""


def classify_regime(
    kospi_closes: list[float],
    kosdaq_closes: list[float],
    adv_dec_ratio: float | None = None,
) -> tuple[str, dict]:
    """(label, metrics). label: bull | bear | sideways."""
    from ..indicators import sma

    def above_ma20(closes: list[float]) -> bool | None:
        ma = sma(closes, 20)
        return None if ma is None or not closes else closes[-1] >= ma

    kospi_up = above_ma20(kospi_closes)
    kosdaq_up = above_ma20(kosdaq_closes)
    metrics = {
        "kospi_above_ma20": kospi_up,
        "kosdaq_above_ma20": kosdaq_up,
        "adv_dec_ratio": adv_dec_ratio,
    }
    ups = [v for v in (kospi_up, kosdaq_up) if v is not None]
    if not ups:
        return "sideways", metrics
    if all(ups) and (adv_dec_ratio is None or adv_dec_ratio >= 1.0):
        return "bull", metrics
    if not any(ups) and (adv_dec_ratio is None or adv_dec_ratio < 1.0):
        return "bear", metrics
    return "sideways", metrics

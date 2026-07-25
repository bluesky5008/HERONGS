"""WU-04 — 지표 순수 함수."""

from herongs import indicators as ind


def test_sma():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5
    assert ind.sma([1, 2], 5) is None


def test_disparity():
    assert ind.disparity([100, 100, 110], 2) is not None
    assert ind.disparity([], 5) is None


def test_volume_ratio():
    vols = [100.0] * 20 + [300.0]
    assert ind.volume_ratio(vols, 20) == 3.0
    assert ind.volume_ratio([100.0] * 5, 20) is None


def test_is_aligned():
    closes = list(range(1, 121))  # 지속 상승 → 5>20>60 정배열
    assert ind.is_aligned([float(x) for x in closes])
    assert not ind.is_aligned([float(x) for x in reversed(closes)])


def test_golden_cross_within():
    # 하락 후 급반등 → 최근 5일 내 5일선이 20일선 상향 돌파
    closes = [float(x) for x in range(100, 70, -1)] + [90.0, 95.0, 100.0, 105.0]
    assert ind.golden_cross_within(closes, 5)
    assert not ind.golden_cross_within([float(x) for x in range(100, 60, -1)], 5)


def test_rate_of_change():
    import pytest

    assert ind.rate_of_change([100.0, 110.0], 1) == pytest.approx(10.0)


def test_high_proximity():
    assert ind.high_proximity([100.0, 200.0, 190.0], 60) == 95.0


def test_consecutive_positive():
    assert ind.consecutive_positive([1, -1, 2, 3]) == 2
    assert ind.consecutive_positive([-1]) == 0
    assert ind.consecutive_positive([]) == 0

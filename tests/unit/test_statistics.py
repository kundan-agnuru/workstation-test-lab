import pytest

from analysis.statistics import compare_to_baseline, summarize


def test_statistics_use_sample_standard_deviation() -> None:
    result = summarize([10, 12, 14])
    assert result.mean == 12
    assert result.median == 12
    assert result.standard_deviation == 2


def test_stable_lower_is_better_regression_is_degraded() -> None:
    result = compare_to_baseline([110, 111, 109], baseline=100, direction="lower")
    assert result.state == "degraded"
    assert result.degradation_percent == pytest.approx(10)


def test_noisy_samples_are_inconclusive() -> None:
    result = compare_to_baseline([70, 100, 130], baseline=100, direction="higher")
    assert result.state == "inconclusive"
    assert "variation" in result.reason


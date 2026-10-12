from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class SampleStats:
    count: int
    mean: float
    median: float
    standard_deviation: float | None
    coefficient_of_variation: float | None


@dataclass(frozen=True)
class Comparison:
    state: str
    degradation_percent: float | None
    statistics: SampleStats
    reason: str


def summarize(samples: list[float]) -> SampleStats:
    if not samples:
        raise ValueError("at least one sample is required")
    mean = statistics.fmean(samples)
    deviation = statistics.stdev(samples) if len(samples) >= 2 else None
    variation = abs(deviation / mean) * 100 if deviation is not None and mean != 0 else None
    return SampleStats(len(samples), mean, statistics.median(samples), deviation, variation)


def compare_to_baseline(
    samples: list[float],
    baseline: float,
    direction: str,
    threshold_percent: float = 5.0,
    max_variation_percent: float = 10.0,
    minimum_samples: int = 3,
) -> Comparison:
    if baseline <= 0:
        raise ValueError("baseline must be positive")
    if direction not in {"higher", "lower"}:
        raise ValueError("direction must be higher or lower")
    stats = summarize(samples)
    if stats.count < minimum_samples:
        return Comparison("inconclusive", None, stats, f"requires at least {minimum_samples} samples")
    if stats.coefficient_of_variation is not None and stats.coefficient_of_variation > max_variation_percent:
        return Comparison("inconclusive", None, stats, "sample variation exceeds policy")
    if direction == "higher":
        degradation = (baseline - stats.mean) / baseline * 100
    else:
        degradation = (stats.mean - baseline) / baseline * 100
    state = "degraded" if degradation >= threshold_percent else "within_threshold"
    return Comparison(state, degradation, stats, "compatible samples compared")


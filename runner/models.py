from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class Package(str, Enum):
    ENVIRONMENT = "environment"
    DRIVER = "driver"
    GPU = "gpu"
    CPU = "cpu"


class ResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"


class FailureCategory(str, Enum):
    ASSERTION = "assertion"
    APPLICATION = "application"
    INFRASTRUCTURE = "infrastructure"
    TIMEOUT = "timeout"
    PARSER = "parser"


@dataclass(frozen=True)
class MetricRecord:
    test_key: str
    attempt: int
    name: str
    value: float
    unit: str
    iteration: int = 1
    direction: str = "neutral"


@dataclass(frozen=True)
class ArtifactRecord:
    test_key: str
    attempt: int
    kind: str
    path: Path
    sha256: str
    media_type: str = "text/plain"


@dataclass(frozen=True)
class ResultRecord:
    test_key: str
    status: ResultStatus
    duration_ms: int
    timestamp: datetime
    message: str
    attempt: int = 1
    failure_category: FailureCategory | None = None


@dataclass
class PackageOutcome:
    results: list[ResultRecord] = field(default_factory=list)
    metrics: list[MetricRecord] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)


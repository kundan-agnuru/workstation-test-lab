from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

PackageName = Literal["environment", "driver", "gpu", "cpu"]
ExecutionMode = Literal["real", "simulated"]
ResultStatus = Literal["PASS", "FAIL", "ERROR", "SKIP"]
FailureCategory = Literal["assertion", "application", "infrastructure", "timeout", "parser"]


class RunCreate(BaseModel):
    run_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    machine_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    execution_mode: ExecutionMode
    selected_packages: list[PackageName] = Field(min_length=1, max_length=4)
    environment_snapshot: dict[str, Any]
    started_at: datetime

    @field_validator("selected_packages")
    @classmethod
    def packages_are_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("selected packages must be unique")
        return value


class RunPatch(BaseModel):
    status: Literal["COMPLETED", "ABORTED"]
    ended_at: datetime


class MetricIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    value: float
    unit: str = Field(min_length=1, max_length=32)
    iteration: int = Field(ge=1)
    direction: Literal["higher", "lower", "neutral"]
    workload: dict[str, Any] = Field(default_factory=dict)


class ArtifactIn(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=3, max_length=128)
    content_base64: str

    def decoded(self) -> bytes:
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("artifact content_base64 is invalid") from exc


class ResultIn(BaseModel):
    test_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.-]+$")
    attempt: int = Field(ge=1)
    status: ResultStatus
    duration_ms: int = Field(ge=0)
    timestamp: datetime
    failure_category: FailureCategory | None = None
    message: str = Field(max_length=10000)
    metrics: list[MetricIn] = Field(default_factory=list, max_length=1000)
    artifacts: list[ArtifactIn] = Field(default_factory=list, max_length=50)


class PackageIngestion(BaseModel):
    run_id: str
    package_execution_id: str
    package: PackageName
    schema_version: int = Field(ge=1)
    parser_version: str = Field(min_length=1, max_length=32)
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    ended_at: datetime
    host_snapshot: dict[str, Any]
    results: list[ResultIn] = Field(max_length=10000)
    raw_log_base64: str

    def decoded_log(self) -> bytes:
        try:
            return base64.b64decode(self.raw_log_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("raw_log_base64 is invalid") from exc


class BaselineCreate(BaseModel):
    test_key: str
    metric_name: str
    value: float = Field(gt=0)
    unit: str
    direction: Literal["higher", "lower"]
    environment_match: dict[str, Any]
    approved_by: str = Field(min_length=1, max_length=160)


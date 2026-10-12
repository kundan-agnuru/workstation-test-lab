from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class HostSnapshot(BaseModel):
    os: str
    cpu: str
    gpu: str
    driver: str
    application: str


class ParsedMetric(BaseModel):
    test_key: str
    attempt: int = Field(ge=1)
    name: str
    value: float
    unit: str
    iteration: int = Field(ge=1)
    direction: str


class ParsedArtifact(BaseModel):
    test_key: str
    attempt: int = Field(ge=1)
    kind: str
    path: str
    sha256: str
    media_type: str
    content: bytes | None = None


class ParsedResult(BaseModel):
    test_key: str
    attempt: int = Field(ge=1)
    status: str
    duration_ms: int = Field(ge=0)
    timestamp: datetime
    failure_category: str | None
    message: str
    metrics: list[ParsedMetric] = Field(default_factory=list)
    artifacts: list[ParsedArtifact] = Field(default_factory=list)


class ParsedPackage(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    schema_version: int
    parser_version: str
    run_id: str
    package_execution_id: str
    package: str
    machine_id: str
    execution_mode: str
    started_at: datetime
    ended_at: datetime
    host: HostSnapshot
    results: list[ParsedResult]
    file_hash: str
    source_path: Path
    raw_log: bytes


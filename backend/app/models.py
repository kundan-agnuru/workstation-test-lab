from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db import Base

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class Machine(Base):
    __tablename__ = "machines"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    inventory: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    machine_id: Mapped[str] = mapped_column(ForeignKey("machines.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    selected_packages: Mapped[list] = mapped_column(JSON_VALUE, nullable=False)
    environment_snapshot: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    package_executions: Mapped[list[PackageExecution]] = relationship(back_populates="run", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','COMPLETED','ABORTED')", name="ck_runs_status"),
        CheckConstraint("execution_mode IN ('real','simulated')", name="ck_runs_mode"),
    )


class PackageExecution(Base):
    __tablename__ = "package_executions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    package: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_state: Mapped[str] = mapped_column(String(16), nullable=False, default="INGESTED")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run: Mapped[Run] = relationship(back_populates="package_executions")
    results: Mapped[list[TestResult]] = relationship(back_populates="package_execution", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="package_execution", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("package IN ('environment','driver','gpu','cpu')", name="ck_package_name"),
        UniqueConstraint("id", "file_hash", name="uq_package_replay_identity"),
        Index("ix_package_run_package", "run_id", "package"),
    )


class TestResult(Base):
    __tablename__ = "test_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_execution_id: Mapped[str] = mapped_column(ForeignKey("package_executions.id", ondelete="CASCADE"), nullable=False)
    test_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    package_execution: Mapped[PackageExecution] = relationship(back_populates="results")
    metrics: Mapped[list[Metric]] = relationship(back_populates="result", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="result")
    __table_args__ = (
        UniqueConstraint("package_execution_id", "test_key", "attempt", name="uq_result_identity"),
        CheckConstraint("status IN ('PASS','FAIL','ERROR','SKIP')", name="ck_result_status"),
        CheckConstraint("duration_ms >= 0", name="ck_result_duration"),
        CheckConstraint("attempt >= 1", name="ck_result_attempt"),
    )


class Metric(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("test_results.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    workload: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False, default=dict)
    result: Mapped[TestResult] = relationship(back_populates="metrics")
    __table_args__ = (
        CheckConstraint("iteration >= 1", name="ck_metric_iteration"),
        CheckConstraint("direction IN ('higher','lower','neutral')", name="ck_metric_direction"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_execution_id: Mapped[str] = mapped_column(ForeignKey("package_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("test_results.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    package_execution: Mapped[PackageExecution] = relationship(back_populates="artifacts")
    result: Mapped[TestResult | None] = relationship(back_populates="artifacts")


class Baseline(Base):
    __tablename__ = "baselines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    environment_match: Mapped[dict] = mapped_column(JSON_VALUE, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(160), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


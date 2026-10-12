from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import models
from backend.app.schemas import PackageIngestion, RunCreate


def create_or_get_run(session: Session, payload: RunCreate) -> tuple[models.Run, bool]:
    existing = session.get(models.Run, payload.run_id)
    if existing:
        same = (
            existing.machine_id == payload.machine_id
            and existing.execution_mode == payload.execution_mode
            and existing.selected_packages == payload.selected_packages
            and existing.environment_snapshot == payload.environment_snapshot
        )
        if not same:
            raise HTTPException(409, "run ID already exists with different metadata")
        return existing, True

    now = datetime.now(UTC)
    machine = session.get(models.Machine, payload.machine_id)
    if machine is None:
        machine = models.Machine(id=payload.machine_id, inventory=payload.environment_snapshot, updated_at=now)
        session.add(machine)
    else:
        machine.inventory = payload.environment_snapshot
        machine.updated_at = now
    run = models.Run(
        id=payload.run_id,
        machine_id=payload.machine_id,
        status="RUNNING",
        execution_mode=payload.execution_mode,
        selected_packages=payload.selected_packages,
        environment_snapshot=payload.environment_snapshot,
        started_at=payload.started_at,
        created_at=now,
    )
    session.add(run)
    session.commit()
    return run, False


def ingest_package(session: Session, payload: PackageIngestion, max_bytes: int) -> tuple[models.PackageExecution, bool]:
    try:
        raw_log = payload.decoded_log()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(raw_log) > max_bytes:
        raise HTTPException(413, "decoded raw log exceeds the configured limit")
    actual_hash = hashlib.sha256(raw_log).hexdigest()
    if actual_hash != payload.file_hash:
        raise HTTPException(422, "raw log SHA-256 does not match file_hash")

    existing = session.get(models.PackageExecution, payload.package_execution_id)
    if existing:
        if existing.file_hash != payload.file_hash:
            raise HTTPException(409, "package execution ID already exists with different content")
        return existing, True
    run = session.get(models.Run, payload.run_id)
    if run is None:
        raise HTTPException(404, "run must be registered before package ingestion")
    if payload.package not in run.selected_packages:
        raise HTTPException(422, "package was not selected for this run")
    if payload.ended_at < payload.started_at:
        raise HTTPException(422, "package end time precedes start time")

    identities = [(item.test_key, item.attempt) for item in payload.results]
    if len(identities) != len(set(identities)):
        raise HTTPException(422, "duplicate test key and attempt in package")

    package = models.PackageExecution(
        id=payload.package_execution_id,
        run_id=payload.run_id,
        package=payload.package,
        file_hash=payload.file_hash,
        parser_version=payload.parser_version,
        schema_version=payload.schema_version,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        ingestion_state="INGESTED",
        ingested_at=datetime.now(UTC),
    )
    session.add(package)
    session.flush()
    session.add(
        models.Artifact(
            package_execution_id=package.id,
            kind="raw_log",
            filename=f"{payload.package}.log",
            sha256=payload.file_hash,
            media_type="text/plain",
            content=raw_log,
        )
    )
    for result_payload in payload.results:
        result = models.TestResult(
            package_execution_id=package.id,
            test_key=result_payload.test_key,
            attempt=result_payload.attempt,
            status=result_payload.status,
            duration_ms=result_payload.duration_ms,
            timestamp=result_payload.timestamp,
            failure_category=result_payload.failure_category,
            message=result_payload.message,
        )
        session.add(result)
        session.flush()
        for metric in result_payload.metrics:
            session.add(
                models.Metric(
                    result_id=result.id,
                    name=metric.name,
                    value=metric.value,
                    unit=metric.unit,
                    iteration=metric.iteration,
                    direction=metric.direction,
                    workload=metric.workload,
                )
            )
        for artifact_payload in result_payload.artifacts:
            try:
                content = artifact_payload.decoded()
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if hashlib.sha256(content).hexdigest() != artifact_payload.sha256:
                raise HTTPException(422, f"artifact hash mismatch for {artifact_payload.filename}")
            session.add(
                models.Artifact(
                    package_execution_id=package.id,
                    result_id=result.id,
                    kind=artifact_payload.kind,
                    filename=artifact_payload.filename,
                    sha256=artifact_payload.sha256,
                    media_type=artifact_payload.media_type,
                    content=content,
                )
            )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return package, False


def package_names_for_run(session: Session, run_id: str) -> list[str]:
    return list(
        session.scalars(
            select(models.PackageExecution.package)
            .where(models.PackageExecution.run_id == run_id)
            .order_by(models.PackageExecution.package)
        )
    )


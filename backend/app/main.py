from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.orm import Session, selectinload

from analysis.statistics import compare_to_baseline
from backend.app import models
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.reruns import execute_package_rerun
from backend.app.schemas import (
    BaselineCreate,
    ExecutionMode,
    PackageIngestion,
    PackageName,
    RunCreate,
    RunPatch,
)
from backend.app.services import create_or_get_run, ingest_package, package_names_for_run

settings = get_settings()
app = FastAPI(title="Workstation Test Lab API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.dashboard_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-Request-ID"],
)
Db = Annotated[Session, Depends(get_db)]


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_ingestion_bytes * 2:
        return JSONResponse(
            status_code=413,
            content={"request_id": request_id, "status": 413, "detail": "request body is too large"},
            headers={"X-Request-ID": request_id},
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    request_id = request.headers.get("X-Request-ID") or getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse({"request_id": request_id, "status": exc.status_code, "detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    return JSONResponse({"request_id": request_id, "status": 422, "detail": exc.errors()}, status_code=422)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Db) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "database unavailable") from exc
    return {"status": "ready"}


def _completeness(run: models.Run, ingested: list[str]) -> dict[str, object]:
    missing = sorted(set(run.selected_packages) - set(ingested))
    return {"ingested_packages": ingested, "missing_packages": missing, "complete": not missing}


def _as_utc(value: datetime) -> datetime:
    """Normalize database timestamps; SQLite may return a naive value."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _run_dict(run: models.Run, ingested: list[str]) -> dict[str, object]:
    return {
        "run_id": run.id,
        "machine_id": run.machine_id,
        "status": run.status,
        "execution_mode": run.execution_mode,
        "selected_packages": run.selected_packages,
        "environment_snapshot": run.environment_snapshot,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "completeness": _completeness(run, ingested),
    }


@app.post("/api/v1/runs", status_code=201)
def register_run(payload: RunCreate, db: Db):
    run, duplicate = create_or_get_run(db, payload)
    return {**_run_dict(run, package_names_for_run(db, run.id)), "duplicate": duplicate}


@app.patch("/api/v1/runs/{run_id}")
def update_run(run_id: str, payload: RunPatch, db: Db):
    run = db.get(models.Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if _as_utc(payload.ended_at) < _as_utc(run.started_at):
        raise HTTPException(422, "run end time precedes start time")
    run.status = payload.status
    run.ended_at = payload.ended_at
    db.commit()
    return _run_dict(run, package_names_for_run(db, run.id))


@app.post("/api/v1/package-results", status_code=201)
def post_package(payload: PackageIngestion, db: Db):
    package, duplicate = ingest_package(db, payload, settings.max_ingestion_bytes)
    return {
        "package_execution_id": package.id,
        "run_id": package.run_id,
        "file_hash": package.file_hash,
        "duplicate": duplicate,
    }


@app.post("/api/v1/reruns/{package}", status_code=201)
def rerun_package(package: PackageName, db: Db, execution_mode: ExecutionMode = "real"):
    try:
        run = execute_package_rerun(
            db,
            package,
            execution_mode,
            settings.rerun_artifacts_root,
            settings.max_ingestion_bytes,
        )
    except Exception as exc:
        raise HTTPException(500, f"rerun failed: {exc}") from exc
    return _run_dict(run, package_names_for_run(db, run.id))


@app.get("/api/v1/runs")
def list_runs(
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    execution_mode: str | None = "real",
    machine: str | None = None,
    status: str | None = None,
    package: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
):
    query = select(models.Run)
    count_query = select(func.count(models.Run.id))
    conditions = []
    if execution_mode and execution_mode != "all":
        conditions.append(models.Run.execution_mode == execution_mode)
    if machine:
        conditions.append(models.Run.machine_id == machine)
    if status:
        conditions.append(models.Run.status == status)
    if started_after:
        conditions.append(models.Run.started_at >= started_after)
    if started_before:
        conditions.append(models.Run.started_at <= started_before)
    if package:
        # JSON's generic ``contains`` comparator becomes a string LIKE query.
        # PostgreSQL then tries to concatenate LIKE wildcards with JSONB and
        # rejects the query. Casting to text gives both PostgreSQL and SQLite
        # the same exact JSON-string membership check.
        conditions.append(cast(models.Run.selected_packages, String).contains(f'"{package}"'))
    query = query.where(*conditions).order_by(models.Run.started_at.desc(), models.Run.id).offset(offset).limit(limit)
    count_query = count_query.where(*conditions)
    runs = db.scalars(query).all()
    items = [_run_dict(run, package_names_for_run(db, run.id)) for run in runs]
    return {"items": items, "total": db.scalar(count_query) or 0, "limit": limit, "offset": offset}


@app.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, db: Db):
    run = db.get(models.Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    ingested = package_names_for_run(db, run.id)
    statuses = Counter(
        db.scalars(
            select(models.TestResult.status)
            .join(models.PackageExecution)
            .where(models.PackageExecution.run_id == run.id)
        ).all()
    )
    return {**_run_dict(run, ingested), "status_counts": dict(statuses)}


def _result_dict(result: models.TestResult, package: str | None = None) -> dict[str, object]:
    return {
        "result_id": result.id,
        "package_execution_id": result.package_execution_id,
        "package": package or result.package_execution.package,
        "test_key": result.test_key,
        "attempt": result.attempt,
        "status": result.status,
        "duration_ms": result.duration_ms,
        "timestamp": result.timestamp,
        "failure_category": result.failure_category,
        "message": result.message,
    }


@app.get("/api/v1/runs/{run_id}/results")
def list_results(
    run_id: str,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    package: str | None = None,
    status: str | None = None,
    test_key: str | None = None,
):
    if db.get(models.Run, run_id) is None:
        raise HTTPException(404, "run not found")
    conditions = [models.PackageExecution.run_id == run_id]
    if package:
        conditions.append(models.PackageExecution.package == package)
    if status:
        conditions.append(models.TestResult.status == status)
    if test_key:
        conditions.append(models.TestResult.test_key == test_key)
    base = select(models.TestResult, models.PackageExecution.package).join(models.PackageExecution).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(models.TestResult.timestamp, models.TestResult.id).offset(offset).limit(limit)).all()
    return {"items": [_result_dict(item, package_name) for item, package_name in rows], "total": total, "limit": limit, "offset": offset}


@app.get("/api/v1/results/{result_id}")
def get_result(result_id: int, db: Db):
    result = db.scalar(
        select(models.TestResult)
        .options(selectinload(models.TestResult.metrics), selectinload(models.TestResult.artifacts), selectinload(models.TestResult.package_execution))
        .where(models.TestResult.id == result_id)
    )
    if result is None:
        raise HTTPException(404, "result not found")
    return {
        **_result_dict(result),
        "metrics": [
            {"name": item.name, "value": item.value, "unit": item.unit, "iteration": item.iteration, "direction": item.direction, "workload": item.workload}
            for item in result.metrics
        ],
        "artifacts": [
            {"artifact_id": item.id, "kind": item.kind, "filename": item.filename, "sha256": item.sha256, "media_type": item.media_type}
            for item in result.artifacts
        ],
    }


@app.get("/api/v1/artifacts/{artifact_id}")
def get_artifact(artifact_id: int, db: Db):
    artifact = db.get(models.Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "artifact not found")
    return Response(
        artifact.content,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'inline; filename="{artifact.filename}"', "ETag": artifact.sha256},
    )


@app.get("/api/v1/summary")
def summary(
    db: Db,
    execution_mode: str | None = "real",
    machine: str | None = None,
    package: str | None = None,
    status: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
):
    conditions = []
    if execution_mode and execution_mode != "all":
        conditions.append(models.Run.execution_mode == execution_mode)
    if machine:
        conditions.append(models.Run.machine_id == machine)
    if package:
        conditions.append(models.PackageExecution.package == package)
    if status:
        conditions.append(models.TestResult.status == status)
    if started_after:
        conditions.append(models.Run.started_at >= started_after)
    if started_before:
        conditions.append(models.Run.started_at <= started_before)
    rows = db.execute(
        select(models.TestResult.status, func.count(models.TestResult.id))
        .join(models.PackageExecution)
        .join(models.Run)
        .where(*conditions)
        .group_by(models.TestResult.status)
    ).all()
    counts = {name: 0 for name in ("PASS", "FAIL", "ERROR", "SKIP")}
    counts.update(dict(rows))
    denominator = counts["PASS"] + counts["FAIL"] + counts["ERROR"]
    run_query = select(models.Run).distinct()
    if package or status:
        run_query = run_query.join(models.PackageExecution).join(models.TestResult)
    run_conditions = []
    if execution_mode and execution_mode != "all":
        run_conditions.append(models.Run.execution_mode == execution_mode)
    if machine:
        run_conditions.append(models.Run.machine_id == machine)
    if started_after:
        run_conditions.append(models.Run.started_at >= started_after)
    if started_before:
        run_conditions.append(models.Run.started_at <= started_before)
    if package:
        run_conditions.append(models.PackageExecution.package == package)
    if status:
        run_conditions.append(models.TestResult.status == status)
    runs = db.scalars(run_query.where(*run_conditions)).all()
    incomplete = sum(bool(set(run.selected_packages) - set(package_names_for_run(db, run.id))) for run in runs)
    package_rows = db.execute(
        select(models.PackageExecution.package, models.TestResult.status, func.count(models.TestResult.id))
        .join(models.TestResult)
        .join(models.Run)
        .where(*conditions)
        .group_by(models.PackageExecution.package, models.TestResult.status)
    ).all()
    package_counts: dict[str, dict[str, int]] = {name: dict.fromkeys(("PASS", "FAIL", "ERROR", "SKIP"), 0) for name in ("environment", "driver", "gpu", "cpu")}
    for package_name, result_status, count in package_rows:
        package_counts[package_name][result_status] = count
    return {
        "status_counts": counts,
        "pass_rate": counts["PASS"] / denominator if denominator else None,
        "run_count": len(runs),
        "incomplete_run_count": incomplete,
        "package_counts": package_counts,
    }


@app.get("/api/v1/metrics/trends")
def metric_trends(
    db: Db,
    test_key: str,
    metric_name: str,
    execution_mode: str = "real",
    machine: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    conditions = [models.TestResult.test_key == test_key, models.Metric.name == metric_name]
    if execution_mode != "all":
        conditions.append(models.Run.execution_mode == execution_mode)
    if machine:
        conditions.append(models.Run.machine_id == machine)
    rows = db.execute(
        select(models.Metric, models.TestResult.timestamp, models.Run.id, models.Run.machine_id, models.Run.environment_snapshot)
        .join(models.TestResult)
        .join(models.PackageExecution)
        .join(models.Run)
        .where(*conditions)
        .order_by(models.TestResult.timestamp.desc(), models.Metric.id.desc())
        .limit(limit)
    ).all()
    items = [
            {
                "timestamp": timestamp,
                "value": metric.value,
                "unit": metric.unit,
                "iteration": metric.iteration,
                "direction": metric.direction,
                "run_id": run_id,
                "machine_id": machine_id,
                "environment_snapshot": environment,
            }
            for metric, timestamp, run_id, machine_id, environment in rows
        ]
    baseline = db.scalar(
        select(models.Baseline)
        .where(
            models.Baseline.test_key == test_key,
            models.Baseline.metric_name == metric_name,
            models.Baseline.active.is_(True),
        )
        .order_by(models.Baseline.approved_at.desc(), models.Baseline.id.desc())
    )
    comparison = None
    baseline_data = None
    if baseline:
        compatible = [
            item["value"]
            for item in items
            if all(item["environment_snapshot"].get(key) == value for key, value in baseline.environment_match.items())
            and item["unit"] == baseline.unit
        ]
        if compatible:
            comparison = asdict(compare_to_baseline(compatible, baseline.value, baseline.direction))
        baseline_data = {
            "baseline_id": baseline.id,
            "value": baseline.value,
            "unit": baseline.unit,
            "direction": baseline.direction,
            "environment_match": baseline.environment_match,
            "approved_by": baseline.approved_by,
            "approved_at": baseline.approved_at,
        }
    return {"items": items, "baseline": baseline_data, "comparison": comparison}


@app.post("/api/v1/baselines", status_code=201)
def create_baseline(payload: BaselineCreate, db: Db):
    baseline = models.Baseline(
        **payload.model_dump(), approved_at=datetime.now(UTC), active=True
    )
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return {"baseline_id": baseline.id, **payload.model_dump(), "approved_at": baseline.approved_at, "active": True}


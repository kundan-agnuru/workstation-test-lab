from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app import models
from backend.app.schemas import PackageIngestion, RunCreate
from backend.app.services import create_or_get_run, ingest_package
from ingestion.client import IngestionClient
from parsers.registry import parse_log
from runner.inventory import collect_inventory, machine_id
from runner.log_writer import write_package_log
from runner.models import Package
from runner.packages import PACKAGE_RUNNERS


def _write_manifest(
    run_directory: Path,
    run_id: str,
    host_id: str,
    execution_mode: str,
    package: Package,
    inventory: dict[str, object],
    started_at: datetime,
) -> None:
    manifest = {
        "run_id": run_id,
        "machine_id": host_id,
        "execution_mode": execution_mode,
        "selected_packages": [package.value],
        "started_at": started_at.isoformat(),
        "inventory": inventory,
    }
    temporary = run_directory / "run.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(run_directory / "run.json")


def execute_package_rerun(
    session: Session,
    package_name: str,
    execution_mode: str,
    artifacts_root: Path,
    max_ingestion_bytes: int,
) -> models.Run:
    package = Package(package_name)
    run_id = str(uuid.uuid4())
    package_execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    artifacts_root = artifacts_root.resolve()
    run_directory = artifacts_root / run_id
    execution_directory = run_directory / package_execution_id
    run_directory.mkdir(parents=True, exist_ok=False)

    host_id = machine_id()
    inventory = collect_inventory(artifacts_root)
    _write_manifest(run_directory, run_id, host_id, execution_mode, package, inventory, started_at)
    run, _ = create_or_get_run(
        session,
        RunCreate(
            run_id=run_id,
            machine_id=host_id,
            execution_mode=execution_mode,
            selected_packages=[package.value],
            environment_snapshot=inventory,
            started_at=started_at,
        ),
    )

    try:
        execution_directory.mkdir(parents=True, exist_ok=False)
        outcome = PACKAGE_RUNNERS[package](
            execution_directory,
            execution_mode,
            require_gpu=False,
            expected_driver=None,
            repeats=3,
        )
        log_path = write_package_log(
            execution_directory,
            run_id,
            package_execution_id,
            package,
            host_id,
            execution_mode,
            inventory,
            started_at,
            outcome,
        )
        parsed = parse_log(log_path, expected_package=package.value)
        ingest_package(
            session,
            PackageIngestion.model_validate(IngestionClient.package_payload(parsed)),
            max_ingestion_bytes,
        )
        run = session.get(models.Run, run_id)
        assert run is not None
        run.status = "COMPLETED"
        run.ended_at = datetime.now(UTC)
        session.commit()
        session.refresh(run)
        return run
    except Exception:
        session.rollback()
        failed_run = session.get(models.Run, run_id)
        if failed_run is not None:
            failed_run.status = "ABORTED"
            failed_run.ended_at = datetime.now(UTC)
            session.commit()
        raise

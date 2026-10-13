from __future__ import annotations

import base64
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from parsers.errors import LogParseError
from parsers.models import ParsedPackage
from parsers.registry import parse_log


class IngestionClient:
    def __init__(self, api_url: str, artifacts_root: Path, retries: int = 3) -> None:
        self.api_url = api_url.rstrip("/")
        self.artifacts_root = artifacts_root
        self.retries = max(0, retries)
        self.state_path = artifacts_root / ".ingestion-state.json"
        self.state = self._load_state()

    def _load_state(self) -> dict[str, object]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"acknowledged": {}}
        except (OSError, json.JSONDecodeError):
            return {"acknowledged": {}}

    def _save_state(self) -> None:
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def discover(self) -> list[Path]:
        quarantine = (self.artifacts_root / "quarantine").resolve()
        return sorted(
            path
            for path in self.artifacts_root.glob("*/*/*.log")
            if quarantine not in path.resolve().parents and path.is_file()
        )

    def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = httpx.request(method, f"{self.api_url}{path}", timeout=15, **kwargs)
                if response.status_code < 500:
                    return response
                last_error = RuntimeError(f"API returned {response.status_code}")
            except httpx.RequestError as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(min(0.5 * (2**attempt), 4.0))
        raise RuntimeError(f"API request failed after {self.retries + 1} attempts: {last_error}")

    def _manifest(self, package: ParsedPackage) -> dict[str, object]:
        path = package.source_path.parent.parent / "run.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"missing or invalid run manifest {path}: {exc}") from exc

    @staticmethod
    def package_payload(package: ParsedPackage) -> dict[str, object]:
        return {
            "run_id": package.run_id,
            "package_execution_id": package.package_execution_id,
            "package": package.package,
            "schema_version": package.schema_version,
            "parser_version": package.parser_version,
            "file_hash": package.file_hash,
            "started_at": package.started_at.isoformat(),
            "ended_at": package.ended_at.isoformat(),
            "host_snapshot": package.host.model_dump(),
            "results": [
                {
                    "test_key": result.test_key,
                    "attempt": result.attempt,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "timestamp": result.timestamp.isoformat(),
                    "failure_category": result.failure_category,
                    "message": result.message,
                    "metrics": [metric.model_dump(exclude={"test_key", "attempt"}) for metric in result.metrics],
                    "artifacts": [
                        {
                            "kind": artifact.kind,
                            "filename": artifact.path,
                            "sha256": artifact.sha256,
                            "media_type": artifact.media_type,
                            "content_base64": base64.b64encode(artifact.content or b"").decode("ascii"),
                        }
                        for artifact in result.artifacts
                    ],
                }
                for result in package.results
            ],
            "raw_log_base64": base64.b64encode(package.raw_log).decode("ascii"),
        }

    def _register(self, package: ParsedPackage, manifest: dict[str, object]) -> None:
        payload = {
            "run_id": package.run_id,
            "machine_id": package.machine_id,
            "execution_mode": package.execution_mode,
            "selected_packages": manifest["selected_packages"],
            "environment_snapshot": manifest["inventory"],
            "started_at": manifest["started_at"],
        }
        response = self._request("POST", "/api/v1/runs", json=payload)
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"run registration rejected ({response.status_code}): {response.text}")

    def _quarantine(self, path: Path, error: LogParseError) -> Path:
        directory = self.artifacts_root / "quarantine"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{path.parent.name}-{path.name}"
        if destination.exists():
            destination = directory / f"{path.parent.name}-{time.time_ns()}-{path.name}"
        shutil.move(str(path), destination)
        diagnostic = destination.with_suffix(destination.suffix + ".error.json")
        diagnostic.write_text(json.dumps(error.as_dict(), indent=2), encoding="utf-8")
        return destination

    def ingest_file(self, path: Path) -> str:
        package = parse_log(path)
        acknowledged = self.state.setdefault("acknowledged", {})
        assert isinstance(acknowledged, dict)
        if acknowledged.get(package.package_execution_id) == package.file_hash:
            return "already_acknowledged"
        manifest = self._manifest(package)
        self._register(package, manifest)
        response = self._request("POST", "/api/v1/package-results", json=self.package_payload(package))
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"package ingestion rejected ({response.status_code}): {response.text}")
        acknowledged[package.package_execution_id] = package.file_hash
        self._save_state()
        return "duplicate" if response.json().get("duplicate") else "ingested"

    def ingest_all(self) -> tuple[list[dict[str, str]], int]:
        outcomes: list[dict[str, str]] = []
        failures = 0
        touched_runs: dict[str, dict[str, object]] = {}
        for path in self.discover():
            try:
                package = parse_log(path)
                manifest = self._manifest(package)
                touched_runs[package.run_id] = manifest
                status = self.ingest_file(path)
                outcomes.append({"file": str(path), "status": status})
            except LogParseError as exc:
                failures += 1
                destination = self._quarantine(path, exc)
                outcomes.append({"file": str(path), "status": "quarantined", "detail": str(exc), "destination": str(destination)})
            except Exception as exc:
                failures += 1
                outcomes.append({"file": str(path), "status": "pending", "detail": str(exc)})

        acknowledged = self.state.get("acknowledged", {})
        if isinstance(acknowledged, dict):
            for run_id, manifest in touched_runs.items():
                run_directory = self.artifacts_root / run_id
                execution_ids = [path.parent.name for path in run_directory.glob("*/*.log")]
                selected = manifest.get("selected_packages", [])
                if len(execution_ids) >= len(selected) and all(item in acknowledged for item in execution_ids):
                    response = self._request(
                        "PATCH",
                        f"/api/v1/runs/{run_id}",
                        json={"status": "COMPLETED", "ended_at": datetime.now(UTC).isoformat()},
                    )
                    if response.status_code != 200:
                        failures += 1
                        outcomes.append({"file": str(run_directory), "status": "pending_completion", "detail": response.text})
        return outcomes, failures


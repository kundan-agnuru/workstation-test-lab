from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from runner.models import Package, PackageOutcome


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_package_log(
    directory: Path,
    run_id: str,
    package_execution_id: str,
    package: Package,
    machine_id: str,
    execution_mode: str,
    inventory: dict[str, object],
    started_at: datetime,
    outcome: PackageOutcome,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    final_path = directory / f"{package.value}.log"
    temporary_path = final_path.with_suffix(".log.tmp")
    lines = [
        " ".join(
            [
                "META schema_version=1",
                f"run_id={run_id}",
                f"package_execution_id={package_execution_id}",
                f"package={package.value}",
                f"machine_id={machine_id}",
                f"execution_mode={execution_mode}",
                f"started_at={_timestamp(started_at)}",
            ]
        ),
        "HOST " + " ".join(f"{key}={_quoted(inventory.get(key, ''))}" for key in ("os", "cpu", "gpu", "driver", "application")),
    ]
    for result in outcome.results:
        category = result.failure_category.value if result.failure_category else "-"
        lines.append(
            " ".join(
                [
                    "RESULT",
                    f"test_key={result.test_key}",
                    f"attempt={result.attempt}",
                    f"status={result.status.value}",
                    f"duration_ms={result.duration_ms}",
                    f"timestamp={_timestamp(result.timestamp)}",
                    f"failure_category={category}",
                    f"message={_quoted(result.message)}",
                ]
            )
        )
    for metric in outcome.metrics:
        lines.append(
            " ".join(
                [
                    "METRIC",
                    f"test_key={metric.test_key}",
                    f"attempt={metric.attempt}",
                    f"name={metric.name}",
                    f"value={metric.value:.12g}",
                    f"unit={metric.unit}",
                    f"iteration={metric.iteration}",
                    f"direction={metric.direction}",
                ]
            )
        )
    for artifact in outcome.artifacts:
        lines.append(
            " ".join(
                [
                    "ARTIFACT",
                    f"test_key={artifact.test_key}",
                    f"attempt={artifact.attempt}",
                    f"kind={artifact.kind}",
                    f"path={_quoted(artifact.path.name)}",
                    f"sha256={artifact.sha256}",
                    f"media_type={artifact.media_type}",
                ]
            )
        )
    lines.append(f"END result_count={len(outcome.results)} ended_at={_timestamp(datetime.now(UTC))}")
    with temporary_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary_path.replace(final_path)
    return final_path


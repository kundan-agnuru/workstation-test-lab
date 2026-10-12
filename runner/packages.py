from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from runner.models import (
    ArtifactRecord,
    FailureCategory,
    MetricRecord,
    Package,
    PackageOutcome,
    ResultRecord,
    ResultStatus,
)
from runner.subprocesses import CommandResult, run_command


def utc_now() -> datetime:
    return datetime.now(UTC)


def _result(
    key: str,
    status: ResultStatus,
    message: str,
    duration_ms: int = 0,
    category: FailureCategory | None = None,
    attempt: int = 1,
) -> ResultRecord:
    return ResultRecord(key, status, max(duration_ms, 0), utc_now(), message, attempt, category)


def _artifact_for(command: CommandResult, directory: Path, key: str, attempt: int = 1) -> ArtifactRecord:
    safe_name = key.replace(".", "-")
    path = directory / f"{safe_name}-attempt-{attempt}.txt"
    content = (
        f"args={json.dumps(command.args)}\nreturncode={command.returncode}\n"
        f"timed_out={str(command.timed_out).lower()}\n\nSTDOUT\n{command.stdout}"
        f"\n\nSTDERR\n{command.stderr}"
    ).encode()
    path.write_bytes(content)
    return ArtifactRecord(key, attempt, "command_output", path, hashlib.sha256(content).hexdigest())


def environment_package(directory: Path, mode: str, **_: object) -> PackageOutcome:
    outcome = PackageOutcome()
    if mode == "simulated":
        outcome.results.extend(
            [
                _result("environment.os", ResultStatus.PASS, "Simulated operating system available"),
                _result("environment.python", ResultStatus.PASS, "Simulated Python 3.12 available"),
                _result("environment.output_writable", ResultStatus.PASS, "Simulated output path is writable"),
                _result("environment.disk_free", ResultStatus.PASS, "Simulated free disk exceeds 1 GiB"),
            ]
        )
        outcome.metrics.append(MetricRecord("environment.disk_free", 1, "disk_free", 128, "GiB"))
        return outcome

    outcome.results.append(_result("environment.os", ResultStatus.PASS, f"Host OS: {os.name}"))
    version_ok = sys.version_info >= (3, 11)
    outcome.results.append(
        _result(
            "environment.python",
            ResultStatus.PASS if version_ok else ResultStatus.FAIL,
            f"Python {sys.version.split()[0]}",
            category=None if version_ok else FailureCategory.ASSERTION,
        )
    )
    try:
        probe = directory / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        outcome.results.append(_result("environment.output_writable", ResultStatus.PASS, "Output path is writable"))
    except OSError as exc:
        outcome.results.append(
            _result("environment.output_writable", ResultStatus.ERROR, str(exc), category=FailureCategory.INFRASTRUCTURE)
        )
    free = shutil.disk_usage(directory).free
    free_gib = free / (1024**3)
    enough = free_gib >= 1
    outcome.results.append(
        _result(
            "environment.disk_free",
            ResultStatus.PASS if enough else ResultStatus.FAIL,
            f"{free_gib:.2f} GiB free",
            category=None if enough else FailureCategory.INFRASTRUCTURE,
        )
    )
    outcome.metrics.append(MetricRecord("environment.disk_free", 1, "disk_free", free_gib, "GiB"))
    return outcome


def driver_package(
    directory: Path,
    mode: str,
    require_gpu: bool = False,
    expected_driver: str | None = None,
    **_: object,
) -> PackageOutcome:
    outcome = PackageOutcome()
    if mode == "simulated":
        version = expected_driver or "580.00"
        outcome.results.append(_result("driver.communication", ResultStatus.PASS, f"Simulated driver {version}"))
        if expected_driver:
            outcome.results.append(_result("driver.version", ResultStatus.PASS, f"Expected driver {version} installed"))
        return outcome

    command = run_command(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], 10)
    outcome.artifacts.append(_artifact_for(command, directory, "driver.communication"))
    if command.timed_out:
        outcome.results.append(
            _result("driver.communication", ResultStatus.ERROR, "nvidia-smi timed out", command.duration_ms, FailureCategory.TIMEOUT)
        )
        return outcome
    if command.returncode != 0 or not command.stdout.strip():
        status = ResultStatus.FAIL if require_gpu else ResultStatus.SKIP
        category = FailureCategory.INFRASTRUCTURE if require_gpu else None
        outcome.results.append(
            _result("driver.communication", status, command.stderr.strip() or "NVIDIA driver unavailable", command.duration_ms, category)
        )
        return outcome
    version = command.stdout.strip().splitlines()[0].strip()
    outcome.results.append(_result("driver.communication", ResultStatus.PASS, f"Driver {version} responded", command.duration_ms))
    if expected_driver:
        matches = version == expected_driver
        outcome.results.append(
            _result(
                "driver.version",
                ResultStatus.PASS if matches else ResultStatus.FAIL,
                f"Installed {version}; expected {expected_driver}",
                category=None if matches else FailureCategory.ASSERTION,
            )
        )
    return outcome


def gpu_package(directory: Path, mode: str, require_gpu: bool = False, **_: object) -> PackageOutcome:
    outcome = PackageOutcome()
    if mode == "simulated":
        outcome.results.append(_result("gpu.detect", ResultStatus.PASS, "Simulated NVIDIA GPU detected", 4))
        outcome.metrics.extend(
            [
                MetricRecord("gpu.detect", 1, "vram_total", 8192, "MiB", direction="higher"),
                MetricRecord("gpu.detect", 1, "temperature", 42, "C", direction="lower"),
            ]
        )
        return outcome

    command = run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,temperature.gpu,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        10,
    )
    outcome.artifacts.append(_artifact_for(command, directory, "gpu.detect"))
    if command.timed_out:
        outcome.results.append(_result("gpu.detect", ResultStatus.ERROR, "GPU query timed out", command.duration_ms, FailureCategory.TIMEOUT))
        return outcome
    if command.returncode != 0 or not command.stdout.strip():
        status = ResultStatus.FAIL if require_gpu else ResultStatus.SKIP
        category = FailureCategory.INFRASTRUCTURE if require_gpu else None
        outcome.results.append(_result("gpu.detect", status, command.stderr.strip() or "No supported GPU detected", command.duration_ms, category))
        return outcome
    first = [part.strip() for part in command.stdout.splitlines()[0].split(",")]
    try:
        name, memory, temperature, utilization = first
        outcome.results.append(_result("gpu.detect", ResultStatus.PASS, f"Detected {name}", command.duration_ms))
        outcome.metrics.extend(
            [
                MetricRecord("gpu.detect", 1, "vram_total", float(memory), "MiB", direction="higher"),
                MetricRecord("gpu.detect", 1, "temperature", float(temperature), "C", direction="lower"),
                MetricRecord("gpu.detect", 1, "utilization", float(utilization), "%", direction="lower"),
            ]
        )
    except (ValueError, TypeError) as exc:
        outcome.results.append(_result("gpu.detect", ResultStatus.ERROR, f"Unexpected nvidia-smi output: {exc}", command.duration_ms, FailureCategory.APPLICATION))
    return outcome


def _cpu_workload(iterations: int) -> int:
    digest = b"workstation-test-lab"
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return digest[0]


def cpu_package(directory: Path, mode: str, repeats: int = 3, **_: object) -> PackageOutcome:
    outcome = PackageOutcome()
    cores = os.cpu_count() or 0
    outcome.results.append(
        _result("cpu.inventory", ResultStatus.PASS if cores else ResultStatus.ERROR, f"{cores} logical cores", category=None if cores else FailureCategory.INFRASTRUCTURE)
    )
    outcome.metrics.append(MetricRecord("cpu.inventory", 1, "logical_cores", cores, "count", direction="higher"))
    workload_iterations = 10_000 if mode == "simulated" else 100_000
    for iteration in range(1, max(1, repeats) + 1):
        started = time.perf_counter()
        try:
            _cpu_workload(workload_iterations)
            elapsed = (time.perf_counter() - started) * 1000
            outcome.results.append(_result("cpu.workload", ResultStatus.PASS, f"Iteration {iteration} completed", round(elapsed), attempt=iteration))
            outcome.metrics.append(MetricRecord("cpu.workload", iteration, "elapsed", elapsed, "ms", iteration, "lower"))
        except Exception as exc:  # pragma: no cover - protects the runner boundary
            elapsed = (time.perf_counter() - started) * 1000
            outcome.results.append(_result("cpu.workload", ResultStatus.ERROR, str(exc), round(elapsed), FailureCategory.APPLICATION, iteration))
    return outcome


PACKAGE_RUNNERS = {
    Package.ENVIRONMENT: environment_package,
    Package.DRIVER: driver_package,
    Package.GPU: gpu_package,
    Package.CPU: cpu_package,
}


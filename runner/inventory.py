from __future__ import annotations

import os
import platform
import re
import socket
from pathlib import Path

from runner.subprocesses import run_command


def machine_id() -> str:
    configured = os.getenv("WORKSTATION_MACHINE_ID")
    source = configured or socket.gethostname() or "unknown-machine"
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", source).strip("-")
    return normalized[:128] or "unknown-machine"


def collect_inventory(output_root: Path) -> dict[str, str | int]:
    gpu = ""
    driver = ""
    probe = run_command(
        ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
        timeout_seconds=5,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        first = probe.stdout.strip().splitlines()[0]
        parts = [part.strip() for part in first.split(",", 1)]
        gpu = parts[0]
        driver = parts[1] if len(parts) > 1 else ""

    return {
        "os": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or platform.machine() or "unknown",
        "logical_cores": os.cpu_count() or 0,
        "gpu": gpu,
        "driver": driver,
        "application": "",
        "python": platform.python_version(),
        "output_root": str(output_root.resolve()),
    }


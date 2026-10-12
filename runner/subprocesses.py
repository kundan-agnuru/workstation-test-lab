from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


def run_command(args: list[str], timeout_seconds: float = 15) -> CommandResult:
    """Run a command without a shell, capturing diagnostics and enforcing a timeout."""
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_seconds,
        )
        return CommandResult(
            args=tuple(args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return CommandResult(
            args=tuple(args),
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(
            args=tuple(args),
            returncode=None,
            stdout="",
            stderr=str(exc),
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )


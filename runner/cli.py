from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from runner.inventory import collect_inventory, machine_id
from runner.log_writer import write_package_log
from runner.models import Package
from runner.packages import PACKAGE_RUNNERS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workstation-lab")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="execute selected test packages")
    run.add_argument("--packages", nargs="+", default=["all"], choices=["all", *(item.value for item in Package)])
    run.add_argument("--mode", choices=["real", "simulated"], default="real")
    run.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    run.add_argument("--machine-id")
    run.add_argument("--require-gpu", action="store_true")
    run.add_argument("--expected-driver")
    run.add_argument("--cpu-repeats", type=int, default=3)
    return parser


def run(args: argparse.Namespace) -> int:
    selected = list(Package) if "all" in args.packages else [Package(value) for value in args.packages]
    run_id = str(uuid.uuid4())
    run_directory = args.artifacts / run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    host_id = args.machine_id or machine_id()
    inventory = collect_inventory(args.artifacts)
    started_at = datetime.now(UTC)
    manifest = {
        "run_id": run_id,
        "machine_id": host_id,
        "execution_mode": args.mode,
        "selected_packages": [package.value for package in selected],
        "started_at": started_at.isoformat(),
        "inventory": inventory,
    }
    (run_directory / "run.json.tmp").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_directory / "run.json.tmp").replace(run_directory / "run.json")

    failures = 0
    for package in selected:
        execution_id = str(uuid.uuid4())
        execution_directory = run_directory / execution_id
        try:
            execution_directory.mkdir(parents=True, exist_ok=False)
            outcome = PACKAGE_RUNNERS[package](
                execution_directory,
                args.mode,
                require_gpu=args.require_gpu,
                expected_driver=args.expected_driver,
                repeats=max(1, args.cpu_repeats),
            )
            path = write_package_log(execution_directory, run_id, execution_id, package, host_id, args.mode, inventory, started_at, outcome)
            print(path)
        except Exception as exc:
            failures += 1
            print(f"{package.value}: runner error: {exc}", file=sys.stderr)
    print(f"run_id={run_id}")
    return 1 if failures else 0


def main() -> None:
    args = _parser().parse_args()
    raise SystemExit(run(args))


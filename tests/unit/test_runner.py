import argparse
from pathlib import Path

from parsers.registry import parse_log
from runner.cli import run


def test_simulated_run_writes_four_finalized_logs(tmp_path: Path) -> None:
    arguments = argparse.Namespace(
        packages=["all"],
        mode="simulated",
        artifacts=tmp_path,
        machine_id="test-machine",
        require_gpu=False,
        expected_driver=None,
        cpu_repeats=3,
    )
    assert run(arguments) == 0
    logs = list(tmp_path.glob("*/*/*.log"))
    assert len(logs) == 4
    assert not list(tmp_path.rglob("*.tmp"))
    assert {parse_log(path).package for path in logs} == {"environment", "driver", "gpu", "cpu"}


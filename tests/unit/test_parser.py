from pathlib import Path

import pytest

from parsers.errors import LogParseError
from parsers.registry import parse_log

FIXTURES = Path(__file__).parents[1] / "fixtures" / "logs"


def test_valid_log_parses_escaped_message_and_metric() -> None:
    package = parse_log(FIXTURES / "valid_environment.log")
    assert package.package == "environment"
    assert package.execution_mode == "simulated"
    assert package.results[0].message == 'Detected "Windows" correctly'
    assert package.results[1].metrics[0].value == 128
    assert len(package.file_hash) == 64


@pytest.mark.parametrize(
    ("name", "reason"),
    [("missing_end.log", "missing END"), ("malformed_metric.log", "unknown result")],
)
def test_invalid_log_has_actionable_error(name: str, reason: str) -> None:
    with pytest.raises(LogParseError) as raised:
        parse_log(FIXTURES / name)
    assert reason in raised.value.reason
    assert raised.value.line_number is not None
    assert raised.value.parser_version


def test_duplicate_result_is_rejected(tmp_path: Path) -> None:
    content = (FIXTURES / "valid_environment.log").read_text(encoding="utf-8")
    result = next(line for line in content.splitlines() if line.startswith("RESULT"))
    content = content.replace("END result_count=2", f"{result}\nEND result_count=3")
    path = tmp_path / "duplicate.log"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LogParseError, match="duplicate result identity"):
        parse_log(path)


def test_unsupported_schema_is_explicit(tmp_path: Path) -> None:
    content = (FIXTURES / "valid_environment.log").read_text(encoding="utf-8").replace("schema_version=1", "schema_version=9", 1)
    path = tmp_path / "future.log"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LogParseError, match="unsupported schema version 9"):
        parse_log(path)


from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

from parsers.errors import LogParseError
from parsers.models import HostSnapshot, ParsedArtifact, ParsedMetric, ParsedPackage, ParsedResult

PARSER_VERSION = "v1.0"
IDENT = r"[A-Za-z0-9_.-]+"
UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
TIMESTAMP = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z"
JSON_STRING = r'"(?:\\.|[^"\\])*"'
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"

META_RE = re.compile(
    rf"^META schema_version=(?P<schema_version>\d+) run_id=(?P<run_id>{UUID}) "
    rf"package_execution_id=(?P<package_execution_id>{UUID}) "
    rf"package=(?P<package>environment|driver|gpu|cpu) machine_id=(?P<machine_id>{IDENT}) "
    rf"execution_mode=(?P<execution_mode>real|simulated) started_at=(?P<started_at>{TIMESTAMP})$"
)
HOST_RE = re.compile(
    rf"^HOST os=(?P<os>{JSON_STRING}) cpu=(?P<cpu>{JSON_STRING}) "
    rf"gpu=(?P<gpu>{JSON_STRING}) driver=(?P<driver>{JSON_STRING}) "
    rf"application=(?P<application>{JSON_STRING})$"
)
RESULT_RE = re.compile(
    rf"^RESULT test_key=(?P<test_key>{IDENT}) attempt=(?P<attempt>\d+) "
    rf"status=(?P<status>PASS|FAIL|ERROR|SKIP) duration_ms=(?P<duration_ms>\d+) "
    rf"timestamp=(?P<timestamp>{TIMESTAMP}) "
    rf"failure_category=(?P<failure_category>-|assertion|application|infrastructure|timeout|parser) "
    rf"message=(?P<message>{JSON_STRING})$"
)
METRIC_RE = re.compile(
    rf"^METRIC test_key=(?P<test_key>{IDENT}) attempt=(?P<attempt>\d+) "
    rf"name=(?P<name>{IDENT}) value=(?P<value>{NUMBER}) unit=(?P<unit>[A-Za-z%][A-Za-z0-9%/_.-]*) "
    rf"iteration=(?P<iteration>\d+) direction=(?P<direction>higher|lower|neutral)$"
)
ARTIFACT_RE = re.compile(
    rf"^ARTIFACT test_key=(?P<test_key>{IDENT}) attempt=(?P<attempt>\d+) "
    rf"kind=(?P<kind>{IDENT}) path=(?P<path>{JSON_STRING}) sha256=(?P<sha256>[0-9a-f]{{64}}) "
    rf"media_type=(?P<media_type>[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+)$"
)
END_RE = re.compile(rf"^END result_count=(?P<result_count>\d+) ended_at=(?P<ended_at>{TIMESTAMP})$")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    return parsed.astimezone(UTC)


def _decode(value: str, path: Path, line_number: int) -> str:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LogParseError(path, line_number, PARSER_VERSION, f"invalid JSON string: {exc.msg}") from exc
    if not isinstance(decoded, str):
        raise LogParseError(path, line_number, PARSER_VERSION, "quoted field must decode to a string")
    return decoded


def parse_v1(path: Path, raw: bytes, expected_package: str | None = None) -> ParsedPackage:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LogParseError(path, None, PARSER_VERSION, f"file is not UTF-8: {exc}") from exc
    lines = text.splitlines()
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) < 3:
        raise LogParseError(path, None, PARSER_VERSION, "truncated file: META, HOST, and END are required")

    meta = META_RE.fullmatch(lines[0])
    if not meta:
        raise LogParseError(path, 1, PARSER_VERSION, "malformed META record")
    groups = meta.groupdict()
    if int(groups["schema_version"]) != 1:
        raise LogParseError(path, 1, PARSER_VERSION, f"unsupported schema version {groups['schema_version']}")
    if expected_package and groups["package"] != expected_package:
        raise LogParseError(path, 1, PARSER_VERSION, f"expected package {expected_package}, got {groups['package']}")

    host_match = HOST_RE.fullmatch(lines[1])
    if not host_match:
        raise LogParseError(path, 2, PARSER_VERSION, "malformed HOST record")
    host = HostSnapshot(**{key: _decode(value, path, 2) for key, value in host_match.groupdict().items()})

    results: dict[tuple[str, int], ParsedResult] = {}
    ended_at: datetime | None = None
    declared_count: int | None = None
    for index, line in enumerate(lines[2:], start=3):
        if ended_at is not None:
            raise LogParseError(path, index, PARSER_VERSION, "records found after END")
        if match := RESULT_RE.fullmatch(line):
            item = match.groupdict()
            key = (item["test_key"], int(item["attempt"]))
            if key in results:
                raise LogParseError(path, index, PARSER_VERSION, f"duplicate result identity {key[0]} attempt {key[1]}")
            results[key] = ParsedResult(
                test_key=key[0],
                attempt=key[1],
                status=item["status"],
                duration_ms=int(item["duration_ms"]),
                timestamp=_utc(item["timestamp"]),
                failure_category=None if item["failure_category"] == "-" else item["failure_category"],
                message=_decode(item["message"], path, index),
            )
        elif match := METRIC_RE.fullmatch(line):
            item = match.groupdict()
            key = (item["test_key"], int(item["attempt"]))
            if key not in results:
                raise LogParseError(path, index, PARSER_VERSION, "metric references an unknown result")
            value = float(item["value"])
            if not math.isfinite(value):
                raise LogParseError(path, index, PARSER_VERSION, "metric value must be finite")
            results[key].metrics.append(
                ParsedMetric(
                    test_key=key[0], attempt=key[1], name=item["name"], value=value,
                    unit=item["unit"], iteration=int(item["iteration"]), direction=item["direction"]
                )
            )
        elif match := ARTIFACT_RE.fullmatch(line):
            item = match.groupdict()
            key = (item["test_key"], int(item["attempt"]))
            if key not in results:
                raise LogParseError(path, index, PARSER_VERSION, "artifact references an unknown result")
            relative = Path(_decode(item["path"], path, index))
            if relative.is_absolute() or len(relative.parts) != 1:
                raise LogParseError(path, index, PARSER_VERSION, "artifact path must be a local filename")
            artifact_path = path.parent / relative
            try:
                content = artifact_path.read_bytes()
            except OSError as exc:
                raise LogParseError(path, index, PARSER_VERSION, f"artifact cannot be read: {exc}") from exc
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise LogParseError(path, index, PARSER_VERSION, "artifact SHA-256 does not match")
            results[key].artifacts.append(
                ParsedArtifact(
                    test_key=key[0],
                    attempt=key[1],
                    kind=item["kind"],
                    path=str(relative),
                    sha256=item["sha256"],
                    media_type=item["media_type"],
                    content=content,
                )
            )
        elif match := END_RE.fullmatch(line):
            declared_count = int(match.group("result_count"))
            ended_at = _utc(match.group("ended_at"))
        else:
            record = line.split(" ", 1)[0] if line else "empty"
            raise LogParseError(path, index, PARSER_VERSION, f"malformed or unknown {record} record")

    if ended_at is None or declared_count is None:
        raise LogParseError(path, len(lines), PARSER_VERSION, "missing END record")
    if declared_count != len(results):
        raise LogParseError(path, len(lines), PARSER_VERSION, f"END declares {declared_count} results, parsed {len(results)}")
    if ended_at < _utc(groups["started_at"]):
        raise LogParseError(path, len(lines), PARSER_VERSION, "END timestamp precedes META timestamp")

    return ParsedPackage(
        schema_version=1,
        parser_version=PARSER_VERSION,
        run_id=groups["run_id"],
        package_execution_id=groups["package_execution_id"],
        package=groups["package"],
        machine_id=groups["machine_id"],
        execution_mode=groups["execution_mode"],
        started_at=_utc(groups["started_at"]),
        ended_at=ended_at,
        host=host,
        results=list(results.values()),
        file_hash=hashlib.sha256(raw).hexdigest(),
        source_path=path,
        raw_log=raw,
    )


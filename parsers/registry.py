from __future__ import annotations

import re
from pathlib import Path

from parsers.errors import LogParseError
from parsers.models import ParsedPackage
from parsers.v1 import parse_v1

HEADER_VERSION_RE = re.compile(rb"^META schema_version=(?P<version>\d+) ")


def parse_log(path: Path, expected_package: str | None = None) -> ParsedPackage:
    raw = path.read_bytes()
    match = HEADER_VERSION_RE.match(raw)
    if not match:
        raise LogParseError(path, 1, "registry", "missing or malformed schema version")
    version = int(match.group("version"))
    if version == 1:
        return parse_v1(path, raw, expected_package)
    raise LogParseError(path, 1, "registry", f"unsupported schema version {version}")


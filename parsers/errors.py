from __future__ import annotations

from pathlib import Path


class LogParseError(ValueError):
    def __init__(self, path: Path, line_number: int | None, parser_version: str, reason: str) -> None:
        self.path = path
        self.line_number = line_number
        self.parser_version = parser_version
        self.reason = reason
        location = f"{path}"
        if line_number is not None:
            location += f":{line_number}"
        super().__init__(f"{location} [{parser_version}]: {reason}")

    def as_dict(self) -> dict[str, object]:
        return {
            "file": str(self.path),
            "line_number": self.line_number,
            "parser_version": self.parser_version,
            "reason": self.reason,
        }


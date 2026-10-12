from __future__ import annotations

import argparse
import json
from pathlib import Path

from ingestion.client import IngestionClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workstation-ingest")
    subcommands = parser.add_subparsers(dest="command", required=True)
    ingest = subcommands.add_parser("ingest", help="parse and upload finalized logs")
    ingest.add_argument("--api-url", default="http://127.0.0.1:8000")
    ingest.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ingest.add_argument("--retries", type=int, default=3)
    return parser


def main() -> None:
    args = _parser().parse_args()
    client = IngestionClient(args.api_url, args.artifacts, args.retries)
    outcomes, failures = client.ingest_all()
    print(json.dumps(outcomes, indent=2))
    raise SystemExit(1 if failures else 0)


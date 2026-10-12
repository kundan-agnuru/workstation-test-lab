# Log format v1

Every finalized file describes one package execution. Records are UTF-8, one per
line, and follow this order: `META`, `HOST`, zero or more `RESULT`/`METRIC`/`ARTIFACT`
records, then exactly one `END`. The parser uses anchored regular expressions.

- Packages: `environment`, `driver`, `gpu`, `cpu`
- Result statuses: `PASS`, `FAIL`, `ERROR`, `SKIP`
- Run lifecycle: `RUNNING`, `COMPLETED`, `ABORTED`
- Failure categories: `assertion`, `application`, `infrastructure`, `timeout`, `parser`
- Execution modes: `real`, `simulated`
- Timestamps: UTC ISO 8601 with a `Z` suffix
- Durations: nonnegative integer milliseconds

Example:

```text
META schema_version=1 run_id=89d24d68-8a3b-4be9-95a1-d6ebff03076c package_execution_id=83b4ee40-5ce3-470b-b0a9-cb987d19b2ed package=gpu machine_id=lab-001 execution_mode=real started_at=2026-10-12T12:00:00.000Z
HOST os="Windows 11" cpu="AMD Ryzen" gpu="NVIDIA RTX" driver="580.00" application=""
RESULT test_key=gpu.detect attempt=1 status=PASS duration_ms=42 timestamp=2026-10-12T12:00:00.042Z failure_category=- message="GPU detected"
METRIC test_key=gpu.detect attempt=1 name=vram_total value=8192 unit=MiB iteration=1 direction=higher
END result_count=1 ended_at=2026-10-12T12:00:00.043Z
```

All quoted fields are JSON strings. This defines escaping for quotes, backslashes,
newlines, and Unicode. Identifiers match conservative ASCII patterns. A metric must
refer to a preceding result with the same test key and attempt. The final count is
the number of `RESULT` lines. A missing or mismatched `END`, unsupported version,
duplicate result identity, or malformed line rejects the entire file.


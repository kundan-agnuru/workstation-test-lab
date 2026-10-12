# API contract

All endpoints are under `/api/v1` except liveness and readiness. JSON errors include
a request ID, status code, and detail. List endpoints use `limit` and `offset`, have
deterministic ordering, and return `{items, total, limit, offset}`.

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Process liveness |
| `GET /ready` | Database readiness |
| `POST /api/v1/runs` | Register a run and immutable environment snapshot |
| `PATCH /api/v1/runs/{run_id}` | Complete or abort a run |
| `POST /api/v1/package-results` | Atomically ingest a parsed package and raw log |
| `GET /api/v1/runs` | Filtered run list |
| `GET /api/v1/runs/{run_id}` | Run summary and package completeness |
| `GET /api/v1/runs/{run_id}/results` | Filtered results for one run |
| `GET /api/v1/results/{result_id}` | Result, metrics, and artifacts |
| `GET /api/v1/artifacts/{artifact_id}` | Stored artifact bytes |
| `GET /api/v1/summary` | Aggregate counts for current filters |
| `GET /api/v1/metrics/trends` | Historical compatible metric samples |

Package ingestion includes IDs, hashes, parser version, host snapshot, normalized
results and metrics, and a base64 raw-log artifact. Repeating an identical execution
UUID and hash is a no-op; reusing an execution UUID with different bytes returns
HTTP 409. Requests larger than `MAX_INGESTION_BYTES` return HTTP 413.

The dashboard computes pass rate as `PASS / (PASS + FAIL + ERROR)`. `SKIP` and no
results are displayed separately. Real and simulated data are never combined unless
the caller explicitly requests both modes.


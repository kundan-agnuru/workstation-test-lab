# Troubleshooting

## Database is unavailable

Check `docker compose ps` and `docker compose logs postgres`. The ingestion client
keeps unacknowledged files pending and retries transient failures with bounded
backoff. Run it again after the API and database recover.

## A log was quarantined

Look under `artifacts/quarantine/`. Its adjacent `.error.json` contains the source
path, line number, parser version, and reason. The original bytes are preserved.

## GPU or driver is skipped

Real mode uses `nvidia-smi`. A missing command or device is `SKIP` unless
`--require-gpu` was supplied. Confirm the vendor driver is installed and that
`nvidia-smi` is on `PATH`.

## Migration or schema errors

Confirm `DATABASE_URL`, then run `alembic current` and `alembic upgrade head`.
Never point tests at a database containing valuable data.

## Dashboard cannot reach the API

Verify `GET http://127.0.0.1:8000/health`, the configured `VITE_API_BASE_URL`, and
that `DASHBOARD_ORIGIN` exactly matches the browser origin.


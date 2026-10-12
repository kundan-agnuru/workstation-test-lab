# Workstation Test Lab

Workstation Test Lab is a portfolio-scale automation system for running environment,
driver, GPU, and CPU checks; persisting immutable package logs; validating them with
versioned regex parsers; ingesting them into PostgreSQL; and exploring results in a
React dashboard.

The project uses read-only probes. Missing optional hardware produces an explicit
`SKIP`. Simulated runs remain labelled from the result file through the API and UI.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- Docker Desktop or a PostgreSQL 15+ server

## Quick start (PowerShell)

### Automated start with Codex

Invoke the repository skill as `$fireup`, or open `/skills` and select `/fireUp`.
It starts Docker Desktop when needed, builds the complete stack, waits for its health
checks, and returns the ready URLs. If a new Docker installation requires a Windows
restart, it temporarily uses the installed project-local Python and Node toolchains.
The same launcher can be run directly:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\.codex\skills\fireup\scripts\fire-up.ps1
```

The dashboard is available at `http://localhost:5173`, and API documentation is at
`http://127.0.0.1:8000/docs`. Repeated calls reuse the running services and database.

### Manual development setup

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
docker compose up -d postgres
alembic upgrade head
uvicorn backend.app.main:app --reload
```

In another terminal:

```powershell
python -m runner run --packages all --mode simulated
python -m ingestion ingest --api-url http://127.0.0.1:8000
Set-Location dashboard
npm ci
npm run dev
```

Open `http://localhost:5173`. API documentation is at
`http://127.0.0.1:8000/docs`.

## Quick start (bash)

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
docker compose up -d postgres
alembic upgrade head
uvicorn backend.app.main:app --reload
```

Then run the same runner and ingestion commands shown above. Use `npm ci && npm run
dev` from `dashboard/`.

To start the complete stack instead, run `docker compose up --build`.

## Runner examples

```powershell
# A safe demonstration with deterministic synthetic hardware values
python -m runner run --packages all --mode simulated

# Read-only probes against the current workstation
python -m runner run --packages environment cpu gpu driver --mode real

# Require GPU presence, converting an unavailable GPU from SKIP to FAIL
python -m runner run --packages gpu driver --mode real --require-gpu
```

Each package writes a finalized `.log` beneath
`artifacts/<run-id>/<package-execution-id>/`. Detailed command output is stored next
to that log. The writer first creates a `.tmp` file and atomically renames it; the
ingestion client discovers only finalized logs.

## Validation

```powershell
python -m pytest
ruff check .
Set-Location dashboard
npm run typecheck
npm run build
```

PostgreSQL integration tests run when `TEST_DATABASE_URL` is set. Hardware checks
are intentionally separate from software-only unit tests.

## Architecture and limitations

The API is the only supported database boundary. A package upload is transactional
and idempotent by execution UUID plus SHA-256. The raw log is retained in the
database so dashboard details do not depend on a runner filesystem.

This first release executes on one machine and has no authentication because every
service binds to localhost. Add ingestion credentials and user access control before
exposing it to a network. GPU and driver probes use `nvidia-smi` when present. The
CPU workload is useful for exercising timing and trend analysis, but it is not a
standardized benchmark. Distributed scheduling from phase 9 remains an optional
extension after the single-machine workflow.

See [the log contract](docs/log-format.md), [the API contract](docs/api-contract.md),
[troubleshooting](docs/troubleshooting.md), and [the demo](docs/demo.md).


---
name: fireup
description: Start the Workstation Test Lab locally, wait for Docker services to become healthy, and report the dashboard and API URLs. Use when the user asks to fire up, launch, start, run, or open this project's local dashboard.
---

# Fire Up

Start the complete local application with the bundled PowerShell launcher.

## Run

1. From the repository root, run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\.codex\skills\fireup\scripts\fire-up.ps1
   ```

2. Let the script start Docker Desktop when its engine is not already running.
3. Wait for the script to confirm that both the API and dashboard are healthy.
4. Return the exact dashboard URL and API documentation URL printed by the script.

The launcher is idempotent. It creates `.env` from `.env.example` only when needed,
uses `docker compose up --build --detach`, and preserves the existing PostgreSQL
volume. When a newly installed Docker Desktop is waiting for a required Windows
restart, it uses the already installed project-local Python and Node toolchains so
the dashboard can still run immediately. Do not stop or remove containers after a
successful launch.

## Missing prerequisites

If `docker` is unavailable on Windows, install Docker Desktop with:

```powershell
winget install --id Docker.DockerDesktop --exact --accept-source-agreements --accept-package-agreements
```

Installation can show a Windows administrator prompt. After installation, rerun the
launcher. If Docker reports that a restart or sign-out is required, tell the user
exactly what Docker reports and provide the same `$fireup` command to continue.

## Failure handling

If startup fails, run `docker compose ps` and `docker compose logs --tail 100` from
the repository root. Explain the failing service and fix project configuration when
the failure is within the repository. Never delete the database volume as part of
startup troubleshooting.

import base64
import hashlib
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models
from backend.app.db import Base, get_db
from backend.app.main import app


@pytest.fixture()
def api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def register(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs",
        json={
            "run_id": "11111111-1111-4111-8111-111111111111",
            "machine_id": "lab-001",
            "execution_mode": "simulated",
            "selected_packages": ["environment"],
            "environment_snapshot": {"os": "test", "driver": ""},
            "started_at": "2026-10-12T12:00:00Z",
        },
    )
    assert response.status_code == 201, response.text


def payload() -> dict[str, object]:
    raw = b"example raw package log\n"
    return {
        "run_id": "11111111-1111-4111-8111-111111111111",
        "package_execution_id": "22222222-2222-4222-8222-222222222222",
        "package": "environment",
        "schema_version": 1,
        "parser_version": "v1.0",
        "file_hash": hashlib.sha256(raw).hexdigest(),
        "started_at": "2026-10-12T12:00:00Z",
        "ended_at": "2026-10-12T12:00:01Z",
        "host_snapshot": {"os": "test"},
        "results": [
            {
                "test_key": "environment.os",
                "attempt": 1,
                "status": "PASS",
                "duration_ms": 2,
                "timestamp": "2026-10-12T12:00:00Z",
                "failure_category": None,
                "message": "ok",
                "metrics": [],
                "artifacts": [],
            }
        ],
        "raw_log_base64": base64.b64encode(raw).decode(),
    }


def test_package_ingestion_is_idempotent_and_queryable(api) -> None:
    client, _ = api
    register(client)
    first = client.post("/api/v1/package-results", json=payload())
    second = client.post("/api/v1/package-results", json=payload())
    assert first.status_code == 201, first.text
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    results = client.get("/api/v1/runs/11111111-1111-4111-8111-111111111111/results")
    assert results.json()["total"] == 1
    completed = client.patch(
        "/api/v1/runs/11111111-1111-4111-8111-111111111111",
        json={"status": "COMPLETED", "ended_at": "2026-10-12T12:00:02Z"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completeness"]["complete"] is True


def test_changed_content_conflicts(api) -> None:
    client, _ = api
    register(client)
    original = payload()
    assert client.post("/api/v1/package-results", json=original).status_code == 201
    raw = b"changed\n"
    changed = {**original, "file_hash": hashlib.sha256(raw).hexdigest(), "raw_log_base64": base64.b64encode(raw).decode()}
    response = client.post("/api/v1/package-results", json=changed)
    assert response.status_code == 409


def test_invalid_artifact_rolls_back_entire_package(api) -> None:
    client, factory = api
    register(client)
    invalid = payload()
    invalid["results"][0]["artifacts"] = [
        {
            "kind": "stdout",
            "filename": "stdout.txt",
            "sha256": "0" * 64,
            "media_type": "text/plain",
            "content_base64": base64.b64encode(b"different").decode(),
        }
    ]
    assert client.post("/api/v1/package-results", json=invalid).status_code == 422
    with factory() as session:
        assert session.scalar(select(models.PackageExecution)) is None
        assert session.scalar(select(models.TestResult)) is None


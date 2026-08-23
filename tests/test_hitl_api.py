"""FastAPI TestClient tests for /api/hitl endpoints.

Tests the unified HITL REST API:
  GET  /api/hitl/tasks
  POST /api/hitl/tasks/{task_id}/decide
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import pytest
    fixture = pytest.fixture
except ImportError:
    pytest = None
    def fixture(*args, **kwargs):
        def decorator(f):
            return f
        return decorator(args[0]) if args and callable(args[0]) else decorator

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

# ---------------------------------------------------------------------------
# We need to point the router's DB at a temp file before importing the app.
# We monkey-patch the module-level _store and _graph inside backend.routes.hitl.
# ---------------------------------------------------------------------------


@fixture()
def db_path() -> Generator[str, None, None]:
    """Temp database with the full schema."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name

    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS SUBSCRIPTION_PLANS (
            plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            monthly_cost_usd REAL NOT NULL,
            max_speed_mbps INTEGER NOT NULL
        );
        INSERT INTO SUBSCRIPTION_PLANS (name, monthly_cost_usd, max_speed_mbps)
            VALUES ('Basic', 29.99, 50);

        CREATE TABLE IF NOT EXISTS ACCOUNTS (
            account_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            account_pin TEXT NOT NULL,
            address TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS EQUIPMENT (
            serial_num TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL,
            model_type TEXT NOT NULL,
            status TEXT NOT NULL,
            last_error_log TEXT
        );

        CREATE TABLE IF NOT EXISTS SUPPORT_TICKETS (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            ticket_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            description TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS threads (
            thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            graph_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            graph_type TEXT NOT NULL,
            state TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            step_number INTEGER NOT NULL,
            state_data TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS hitl_tasks (
            task_id TEXT PRIMARY KEY,
            graph_type TEXT NOT NULL,
            thread_id TEXT,
            run_id TEXT,
            account_id INTEGER,
            task_type TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'approved', 'rejected', 'modified')),
            action_json TEXT NOT NULL,
            decision_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS failure_logs (
            failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            failure_type TEXT NOT NULL,
            failure_step TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            state_data TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

    yield path
    os.unlink(path)


@fixture()
def client(db_path: str) -> Generator[TestClient, None, None]:
    """TestClient with HITL router's DB redirected to temp file."""
    from shared.hitl.store import SqliteHITLStore
    from graphs.order_activation.graph import ActivationGraph
    import backend.routes.hitl as hitl_module

    real_store = SqliteHITLStore(db_path)
    real_graph = ActivationGraph(db_path)

    with patch.object(hitl_module, "_store", real_store), \
         patch.object(hitl_module, "_graph", real_graph):
        from backend.main import app
        with TestClient(app) as c:
            yield c


@fixture()
def seeded_task(db_path: str) -> int:
    """Insert one pending HITL task and return its task_id as int."""
    from shared.hitl.store import SqliteHITLStore
    store = SqliteHITLStore(db_path)
    task_id = store.create_request(
        run_id="42",
        payload={"description": "Equipment approval required"},
        thread_id="7",
        graph_type="order_activation",
        account_id=1,
        task_type="equipment_cost",
        id_mode="numeric",
    )
    return int(task_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListTasks:
    def test_returns_list(self, client: TestClient):
        resp = client.get("/api/hitl/tasks")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_by_status(self, client: TestClient, db_path: str, seeded_task: int):
        resp = client.get("/api/hitl/tasks?status=pending")
        assert resp.status_code == 200
        data = resp.json()
        assert any(t["task_id"] == str(seeded_task) for t in data)

    def test_filter_by_graph_type(self, client: TestClient, db_path: str, seeded_task: int):
        resp = client.get("/api/hitl/tasks?graph_type=order_activation")
        assert resp.status_code == 200
        data = resp.json()
        assert any(t["task_id"] == str(seeded_task) for t in data)

    def test_filter_unknown_status_returns_empty(self, client: TestClient):
        resp = client.get("/api/hitl/tasks?status=nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []


class TestDecideTask:
    def test_approve_returns_200(self, client: TestClient, seeded_task: int):
        resp = client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={"actor_id": "admin1", "status": "approved", "notes": "LGTM"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["status"] == "approved"
        assert "admin1" in body["message"]

    def test_reject_returns_200(self, client: TestClient, seeded_task: int):
        resp = client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={"actor_id": "admin2", "status": "rejected", "notes": "Too pricey"},
        )
        assert resp.status_code == 200
        assert resp.json()["task"]["status"] == "rejected"

    def test_not_found_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/hitl/tasks/99999/decide",
            json={"actor_id": "admin1", "status": "approved"},
        )
        assert resp.status_code == 404

    def test_already_decided_returns_409(self, client: TestClient, seeded_task: int):
        # First decision
        client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={"actor_id": "admin1", "status": "approved"},
        )
        # Second decision on same task
        resp = client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={"actor_id": "admin1", "status": "approved"},
        )
        assert resp.status_code == 409
        assert "already been decided" in resp.json()["detail"]

    def test_invalid_status_returns_422(self, client: TestClient, seeded_task: int):
        resp = client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={"actor_id": "admin1", "status": "maybe"},
        )
        assert resp.status_code == 422

    def test_modified_requires_modification_payload(self, client: TestClient, seeded_task: int):
        # 'modified' without modification dict should 422
        resp = client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={"actor_id": "admin1", "status": "modified"},
        )
        assert resp.status_code == 422

    def test_modified_with_payload_returns_200(self, client: TestClient, seeded_task: int):
        resp = client.post(
            f"/api/hitl/tasks/{seeded_task}/decide",
            json={
                "actor_id": "admin1",
                "status": "modified",
                "modification": {"equipment_model": "WiFi-V4"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["task"]["status"] == "modified"


class TestEndToEndPauseResume:
    """Full HITL flow through the API: run → pause → GET → decide → resume."""

    def test_full_flow_via_api(self, client: TestClient, db_path: str):
        """Run graph, check pending task appears in API, approve via API."""
        from graphs.order_activation.graph import ActivationGraph

        graph = ActivationGraph(db_path)
        pause_result = graph.run(
            customer_name="API Flow User",
            address="1 API Ave",
            plan_id=1,
            pin="0000",
        )
        assert pause_result.get("paused") is True
        task_id = pause_result["task_id"]

        # Task should appear in GET /tasks
        resp = client.get("/api/hitl/tasks?status=pending")
        assert resp.status_code == 200
        task_ids = [t["task_id"] for t in resp.json()]
        assert str(task_id) in task_ids

        # Approve via API — this also triggers resume automatically
        resp = client.post(
            f"/api/hitl/tasks/{task_id}/decide",
            json={"actor_id": "api_admin", "status": "approved", "notes": "ok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["status"] == "approved"

        # resume_result should show completed activation
        resume = body.get("resume_result") or {}
        assert resume.get("success") is True, f"Resume failed: {resume}"
        assert resume["data"]["activated"] is True

        # Task should no longer be pending
        resp2 = client.get("/api/hitl/tasks?status=pending")
        pending_ids = [t["task_id"] for t in resp2.json()]
        assert str(task_id) not in pending_ids

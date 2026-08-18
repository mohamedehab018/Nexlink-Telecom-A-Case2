"""Tests for Order-to-Activation Graph."""
import pytest
import sqlite3
import os
import tempfile
from graphs.order_activation.states import GraphState, ActivationData
from graphs.order_activation.graph import ActivationGraph
from graphs.order_activation.checkpoint import CheckpointManager
from graphs.order_activation.hitl import HITLManager
from graphs.order_activation.failure import FailureManager
from graphs.order_activation.tools import (
    create_account, assign_equipment, configure_equipment,
    activate_service, send_welcome_message, check_equipment_available
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    # Create schema
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS SUBSCRIPTION_PLANS (
            plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            monthly_cost_usd REAL NOT NULL,
            max_speed_mbps INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ACCOUNTS (
            account_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            account_pin TEXT NOT NULL,
            address TEXT NOT NULL,
            FOREIGN KEY (plan_id) REFERENCES SUBSCRIPTION_PLANS(plan_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS EQUIPMENT (
            serial_num TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL,
            model_type TEXT NOT NULL,
            status TEXT NOT NULL,
            last_error_log TEXT,
            FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS SUPPORT_TICKETS (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            ticket_type TEXT NOT NULL CHECK(ticket_type IN ('billing', 'technical', 'dispatch', 'other')),
            status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'ongoing', 'closed')),
            description TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            graph_type TEXT NOT NULL CHECK(graph_type IN ('outage', 'order_activation', 'sla_dispute')),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'failed')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL,
            graph_type TEXT NOT NULL CHECK(graph_type IN ('outage', 'order_activation', 'sla_dispute')),
            state TEXT,
            status TEXT NOT NULL DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed', 'paused')),
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            step_number INTEGER NOT NULL,
            state_data TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hitl_tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
            admin_id TEXT,
            admin_notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved_at DATETIME,
            FOREIGN KEY (run_id) REFERENCES runs(run_id),
            FOREIGN KEY (thread_id) REFERENCES threads(thread_id),
            FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failure_logs (
            failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            failure_type TEXT NOT NULL,
            failure_step TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            state_data TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES runs(run_id),
            FOREIGN KEY (thread_id) REFERENCES threads(thread_id),
            FOREIGN KEY (account_id) REFERENCES ACCOUNTS(account_id)
        )
    """)
    
    # Seed data
    conn.execute("INSERT INTO SUBSCRIPTION_PLANS (name, monthly_cost_usd, max_speed_mbps) VALUES ('Basic', 29.99, 50)")
    conn.execute("INSERT INTO SUBSCRIPTION_PLANS (name, monthly_cost_usd, max_speed_mbps) VALUES ('Premium', 49.99, 100)")
    conn.commit()
    conn.close()
    
    yield db_path
    
    os.unlink(db_path)


class TestActivationData:
    """Test ActivationData class."""
    
    def test_creation(self):
        data = ActivationData()
        assert data.account_id is None
        assert data.verified is False
        assert data.messages == []
    
    def test_to_dict(self):
        data = ActivationData(account_id=123, customer_name="Test")
        d = data.to_dict()
        assert d["account_id"] == 123
        assert d["customer_name"] == "Test"
    
    def test_from_dict(self):
        d = {"account_id": 123, "customer_name": "Test", "verified": True}
        data = ActivationData.from_dict(d)
        assert data.account_id == 123
        assert data.customer_name == "Test"
        assert data.verified is True
    
    def test_add_message(self):
        data = ActivationData()
        data.add_message("user", "Hello")
        data.add_message("assistant", "Hi there")
        assert len(data.messages) == 2
        assert data.messages[0]["role"] == "user"


class TestCheckpointManager:
    """Test CheckpointManager class."""
    
    def test_create_thread(self, temp_db):
        mgr = CheckpointManager(temp_db)
        thread_id = mgr.create_thread(account_id=1)
        assert thread_id > 0
    
    def test_create_run(self, temp_db):
        mgr = CheckpointManager(temp_db)
        thread_id = mgr.create_thread(account_id=1)
        run_id = mgr.create_run(thread_id)
        assert run_id > 0
    
    def test_save_and_load_checkpoint(self, temp_db):
        mgr = CheckpointManager(temp_db)
        thread_id = mgr.create_thread(account_id=1)
        run_id = mgr.create_run(thread_id)
        
        data = ActivationData(account_id=1, customer_name="Test")
        mgr.save_checkpoint(run_id, 0, GraphState.CREATE_ACCOUNT, data)
        
        loaded = mgr.load_checkpoint(run_id)
        assert loaded is not None
        state, loaded_data = loaded
        assert state == GraphState.CREATE_ACCOUNT
        assert loaded_data.account_id == 1


class TestHITLManager:
    """Test HITLManager class."""
    
    def test_create_approval_request(self, temp_db):
        mgr = HITLManager(temp_db)
        task_id = mgr.create_approval_request(
            run_id=1, thread_id=1, account_id=1,
            task_type="equipment_cost", description="Test"
        )
        assert task_id > 0
    
    def test_approve_task(self, temp_db):
        mgr = HITLManager(temp_db)
        task_id = mgr.create_approval_request(
            run_id=1, thread_id=1, account_id=1,
            task_type="equipment_cost", description="Test"
        )
        result = mgr.approve_task(task_id, "admin1", "Approved")
        assert result["success"] is True
    
    def test_reject_task(self, temp_db):
        mgr = HITLManager(temp_db)
        task_id = mgr.create_approval_request(
            run_id=1, thread_id=1, account_id=1,
            task_type="equipment_cost", description="Test"
        )
        result = mgr.reject_task(task_id, "admin1", "Too expensive")
        assert result["success"] is True


class TestFailureManager:
    """Test FailureManager class."""
    
    def test_log_failure(self, temp_db):
        mgr = FailureManager(temp_db)
        failure_id = mgr.log_failure(
            run_id=1, thread_id=1, account_id=1,
            failure_type="equipment", failure_step="configure",
            failure_reason="Equipment not found"
        )
        assert failure_id > 0
    
    def test_create_failure_ticket(self, temp_db):
        mgr = FailureManager(temp_db)
        result = mgr.create_failure_ticket(
            account_id=1, failure_type="equipment",
            failure_reason="Not found"
        )
        assert result["success"] is True
        assert result["ticket_id"] > 0
    
    def test_should_retry(self, temp_db):
        mgr = FailureManager(temp_db)
        assert mgr.should_retry(0, 3) is True
        assert mgr.should_retry(2, 3) is True
        assert mgr.should_retry(3, 3) is False


class TestTools:
    """Test MCP tools."""
    
    def test_create_account(self, temp_db):
        result = create_account(
            customer_name="Test User",
            address="123 Test St",
            plan_id=1,
            pin="1234",
            db_path=temp_db
        )
        assert result["success"] is True
        assert result["account_id"] > 0
    
    def test_assign_equipment(self, temp_db):
        # First create account
        account = create_account("Test", "Address", 1, "1234", temp_db)
        
        result = assign_equipment(
            account_id=account["account_id"],
            serial_num="TEST-001",
            model_type="WiFi-V3",
            db_path=temp_db
        )
        assert result["success"] is True
    
    def test_configure_equipment(self, temp_db):
        # Create account and assign equipment
        account = create_account("Test", "Address", 1, "1234", temp_db)
        assign_equipment(account["account_id"], "TEST-001", "WiFi-V3", temp_db)
        
        result = configure_equipment("TEST-001", db_path=temp_db)
        assert result["success"] is True
    
    def test_activate_service(self, temp_db):
        # Full setup
        account = create_account("Test", "Address", 1, "1234", temp_db)
        assign_equipment(account["account_id"], "TEST-001", "WiFi-V3", temp_db)
        configure_equipment("TEST-001", db_path=temp_db)
        
        result = activate_service(account["account_id"], temp_db)
        assert result["success"] is True
    
    def test_send_welcome_message(self, temp_db):
        account = create_account("Test", "Address", 1, "1234", temp_db)
        result = send_welcome_message(account["account_id"], temp_db)
        assert result["success"] is True
    
    def test_check_equipment_available(self, temp_db):
        result = check_equipment_available("WiFi-V3", temp_db)
        assert result["available"] is True
        assert result["requires_approval"] is True


class TestActivationGraph:
    """Test ActivationGraph class."""
    
    def test_full_activation(self, temp_db):
        graph = ActivationGraph(temp_db)
        result = graph.run(
            customer_name="Test User",
            address="123 Test St",
            plan_id=1,
            pin="1234"
        )
        assert result["success"] is True
        assert result["account_id"] > 0
    
    def test_activation_with_existing_account(self, temp_db):
        # Create account first
        account = create_account("Test", "Address", 1, "1234", temp_db)
        
        graph = ActivationGraph(temp_db)
        result = graph.run(
            customer_name="Test User",
            address="123 Test St",
            plan_id=1,
            pin="1234",
            account_id=account["account_id"]
        )
        assert result["success"] is True

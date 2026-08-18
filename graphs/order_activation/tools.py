"""MCP Tools for Order-to-Activation Graph.

New tools needed for customer activation workflow.
"""
from __future__ import annotations
import sqlite3
from typing import Optional, Dict, Any
from contextlib import contextmanager


def get_connection(db_path: str = "db/nexlink.db") -> sqlite3.Connection:
    """Get database connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_conn(db_path: str = "db/nexlink.db"):
    """Context manager for database connection."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


def create_account(
    customer_name: str,
    address: str,
    plan_id: int,
    pin: str,
    db_path: str = "db/nexlink.db"
) -> Dict[str, Any]:
    """Create a new customer account.
    
    Args:
        customer_name: Full name of customer
        address: Installation address
        plan_id: Subscription plan ID
        pin: 4-digit security PIN
        db_path: Path to database
        
    Returns:
        Dictionary with account details
    """
    with db_conn(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO ACCOUNTS (customer_name, address, plan_id, account_pin)
               VALUES (?, ?, ?, ?)""",
            (customer_name, address, plan_id, pin)
        )
        account_id = cursor.lastrowid
        conn.commit()
        
        return {
            "success": True,
            "account_id": account_id,
            "customer_name": customer_name,
            "address": address,
            "plan_id": plan_id,
            "message": f"Account #{account_id} created successfully"
        }


def assign_equipment(
    account_id: int,
    serial_num: str,
    model_type: str,
    db_path: str = "db/nexlink.db"
) -> Dict[str, Any]:
    """Assign equipment to an account.
    
    Args:
        account_id: Account to assign equipment to
        serial_num: Equipment serial number
        model_type: Equipment model (WiFi-V3, Optic-V1, Coax-V2)
        db_path: Path to database
        
    Returns:
        Dictionary with assignment result
    """
    with db_conn(db_path) as conn:
        # Check if equipment exists
        existing = conn.execute(
            "SELECT * FROM EQUIPMENT WHERE serial_num = ?",
            (serial_num,)
        ).fetchone()
        
        if existing:
            return {
                "success": False,
                "error": f"Equipment {serial_num} already assigned to account #{existing['account_id']}"
            }
        
        # Check if account exists
        account = conn.execute(
            "SELECT * FROM ACCOUNTS WHERE account_id = ?",
            (account_id,)
        ).fetchone()
        
        if not account:
            return {
                "success": False,
                "error": f"Account #{account_id} not found"
            }
        
        # Assign equipment
        conn.execute(
            """INSERT INTO EQUIPMENT (serial_num, account_id, model_type, status)
               VALUES (?, ?, ?, 'active')""",
            (serial_num, account_id, model_type)
        )
        conn.commit()
        
        return {
            "success": True,
            "serial_num": serial_num,
            "account_id": account_id,
            "model_type": model_type,
            "status": "active",
            "message": f"Equipment {serial_num} assigned to account #{account_id}"
        }


def configure_equipment(
    serial_num: str,
    config: Optional[Dict[str, Any]] = None,
    db_path: str = "db/nexlink.db"
) -> Dict[str, Any]:
    """Configure equipment for activation.
    
    Args:
        serial_num: Equipment serial number
        config: Configuration parameters
        db_path: Path to database
        
    Returns:
        Dictionary with configuration result
    """
    with db_conn(db_path) as conn:
        equipment = conn.execute(
            "SELECT * FROM EQUIPMENT WHERE serial_num = ?",
            (serial_num,)
        ).fetchone()
        
        if not equipment:
            return {
                "success": False,
                "error": f"Equipment {serial_num} not found"
            }
        
        # Update status to configured
        conn.execute(
            "UPDATE EQUIPMENT SET status = 'configured' WHERE serial_num = ?",
            (serial_num,)
        )
        conn.commit()
        
        return {
            "success": True,
            "serial_num": serial_num,
            "status": "configured",
            "config": config or {},
            "message": f"Equipment {serial_num} configured successfully"
        }


def activate_service(
    account_id: int,
    db_path: str = "db/nexlink.db"
) -> Dict[str, Any]:
    """Activate service for an account.
    
    Args:
        account_id: Account to activate
        db_path: Path to database
        
    Returns:
        Dictionary with activation result
    """
    with db_conn(db_path) as conn:
        account = conn.execute(
            "SELECT * FROM ACCOUNTS WHERE account_id = ?",
            (account_id,)
        ).fetchone()
        
        if not account:
            return {
                "success": False,
                "error": f"Account #{account_id} not found"
            }
        
        # Check if equipment is configured
        equipment = conn.execute(
            "SELECT * FROM EQUIPMENT WHERE account_id = ? AND status = 'configured'",
            (account_id,)
        ).fetchone()
        
        if not equipment:
            return {
                "success": False,
                "error": "No configured equipment found for this account"
            }
        
        # Update equipment status to active
        conn.execute(
            "UPDATE EQUIPMENT SET status = 'active' WHERE serial_num = ?",
            (equipment['serial_num'],)
        )
        conn.commit()
        
        return {
            "success": True,
            "account_id": account_id,
            "equipment": equipment['serial_num'],
            "status": "active",
            "message": f"Service activated for account #{account_id}"
        }


def send_welcome_message(
    account_id: int,
    db_path: str = "db/nexlink.db"
) -> Dict[str, Any]:
    """Send welcome message to new customer.
    
    Args:
        account_id: Account to send welcome to
        db_path: Path to database
        
    Returns:
        Dictionary with send result
    """
    with db_conn(db_path) as conn:
        account = conn.execute(
            """SELECT a.*, p.name as plan_name, p.max_speed_mbps
               FROM ACCOUNTS a
               JOIN SUBSCRIPTION_PLANS p ON a.plan_id = p.plan_id
               WHERE a.account_id = ?""",
            (account_id,)
        ).fetchone()
        
        if not account:
            return {
                "success": False,
                "error": f"Account #{account_id} not found"
            }
        
        message = f"""Welcome to Nextlink, {account['customer_name']}!

Your account has been activated:
- Account ID: #{account['account_id']}
- Plan: {account['plan_name']} ({account['max_speed_mbps']} Mbps)
- Address: {account['address']}

Your internet service is now active. If you have any questions, please contact support.

Thank you for choosing Nextlink!"""
        
        return {
            "success": True,
            "account_id": account_id,
            "message": message,
            "sent": True
        }


def check_equipment_available(
    model_type: str,
    db_path: str = "db/nexlink.db"
) -> Dict[str, Any]:
    """Check if equipment model is available for assignment.
    
    Args:
        model_type: Equipment model to check
        db_path: Path to database
        
    Returns:
        Dictionary with availability info
    """
    # Define available equipment models
    available_models = {
        "WiFi-V3": {"description": "WiFi Router", "max_speed": 100, "cost": 150},
        "Optic-V1": {"description": "Fiber Modem", "max_speed": 1000, "cost": 200},
        "Coax-V2": {"description": "Cable Modem", "max_speed": 500, "cost": 175},
    }
    
    if model_type not in available_models:
        return {
            "available": False,
            "error": f"Unknown model: {model_type}",
            "available_models": list(available_models.keys())
        }
    
    model_info = available_models[model_type]
    return {
        "available": True,
        "model_type": model_type,
        "description": model_info["description"],
        "max_speed_mbps": model_info["max_speed"],
        "cost_usd": model_info["cost"],
        "requires_approval": model_info["cost"] > 100
    }

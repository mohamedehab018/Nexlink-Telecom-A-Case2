import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Union

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Ordered list of places we'll look for nexlink.db, covering both project
# layouts this codebase has been organized as:
#   - flat:   db.py and nexlink.db in the same folder
#   - nested: db.py in mcp_server/, nexlink.db in a sibling db/ folder
# The first candidate that actually exists on disk wins. This can always be
# overridden explicitly with the NEXLINK_DB_PATH environment variable.
_CANDIDATE_PATHS = [
    os.path.join(_THIS_DIR, "nexlink.db"),                      # flat layout
    os.path.abspath(os.path.join(_THIS_DIR, "..", "db", "nexlink.db")),  # nested layout
    os.path.abspath(os.path.join(os.getcwd(), "nexlink.db")),   # run from db/ itself
    os.path.abspath(os.path.join(os.getcwd(), "db", "nexlink.db")),
]
DEFAULT_DB_PATH = _CANDIDATE_PATHS[0]


def _is_valid_nexlink_db(path: str) -> bool:
    """True if path exists and actually has the ACCOUNTS table -- filters
    out stray empty files (e.g. ones sqlite3.connect() silently created at
    a wrong path before this module started checking)."""
    if not os.path.isfile(path):
        return False
    try:
        conn = sqlite3.connect(path)
        try:
            conn.execute("SELECT 1 FROM ACCOUNTS LIMIT 1")
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def get_db_path() -> str:
    env_path = os.environ.get("NEXLINK_DB_PATH")
    if env_path:
        return env_path
    for candidate in _CANDIDATE_PATHS:
        if _is_valid_nexlink_db(candidate):
            return candidate
    # Nothing valid found -- fall back to the first *existing* file (so an
    # error about "wrong schema" is still more useful than a generic "not
    # found" if the user genuinely put a real, if unseeded, db there), else
    # the primary default path.
    for candidate in _CANDIDATE_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    if not os.path.isfile(path):
        # sqlite3.connect() silently CREATES an empty file if the path
        # doesn't exist rather than raising -- which is exactly how a wrong
        # NEXLINK_DB_PATH or a missing setup_db.py run produces a server
        # that runs fine but can never find any account, ticket, or
        # equipment. Fail loudly here instead, with every path we tried, so
        # the real problem is obvious immediately.
        tried = "\n    - ".join(_CANDIDATE_PATHS)
        raise RuntimeError(
            f"Database file not found. Tried:\n    - {tried}\n"
            f"  - Run `python setup_db.py` (from wherever schema.sql/seed.sql live) "
            f"to create and seed nexlink.db, or set NEXLINK_DB_PATH to point at an "
            f"existing one explicitly."
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT 1 FROM ACCOUNTS LIMIT 1")
    except sqlite3.OperationalError as e:
        conn.close()
        raise RuntimeError(
            f"Database file at {path} exists but doesn't have the expected "
            f"schema ({e}). Run `python setup_db.py` to rebuild it."
        ) from e
    return conn


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Context manager that guarantees the connection is closed.

    sqlite3.Connection's own context manager only commits/rolls back the
    transaction on exit -- it does NOT close the connection. Using it directly
    (as this module previously did, 13x) leaks a connection on every call,
    which is a real problem for a long-running server handling many requests.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# --- READ OPERATIONS ---

def get_account_summary(account_id_or_name: Union[int, str]) -> Optional[Dict[str, Any]]:
    """Retrieves account summary (omitting security PIN). Supports numeric ID or name string."""
    is_numeric = isinstance(account_id_or_name, int) or (
        isinstance(account_id_or_name, str) and account_id_or_name.isdigit()
    )
    
    if is_numeric:
        query = """
            SELECT a.account_id, a.customer_name, a.address, 
                   p.plan_id, p.name AS plan_name, p.monthly_cost_usd, p.max_speed_mbps
            FROM ACCOUNTS a
            JOIN SUBSCRIPTION_PLANS p ON a.plan_id = p.plan_id
            WHERE a.account_id = ?
        """
        params = (int(account_id_or_name),)
    else:
        query = """
            SELECT a.account_id, a.customer_name, a.address, 
                   p.plan_id, p.name AS plan_name, p.monthly_cost_usd, p.max_speed_mbps
            FROM ACCOUNTS a
            JOIN SUBSCRIPTION_PLANS p ON a.plan_id = p.plan_id
            WHERE LOWER(a.customer_name) LIKE LOWER(?)
            LIMIT 1
        """
        params = (f"%{account_id_or_name}%",)

    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None


def verify_account_pin(account_id: int, pin: int) -> bool:
    """Validates the security PIN for a given account."""
    query = "SELECT account_pin FROM ACCOUNTS WHERE account_id = ?"
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (account_id,))
        row = cursor.fetchone()
        return bool(row and int(row["account_pin"]) == pin)


def list_support_tickets(account_id: int) -> List[Dict[str, Any]]:
    """Fetches support tickets for an account ordered by creation date."""
    query = """
        SELECT ticket_id, account_id, ticket_type, status, description, created_at
        FROM SUPPORT_TICKETS
        WHERE account_id = ?
        ORDER BY created_at DESC
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (account_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_ticket_by_id(ticket_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves single ticket record by ticket ID."""
    query = """
        SELECT ticket_id, account_id, ticket_type, status, description, created_at
        FROM SUPPORT_TICKETS
        WHERE ticket_id = ?
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (ticket_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_equipment_by_account(account_id: int) -> List[Dict[str, Any]]:
    """Gets assigned equipment for an account."""
    query = """
        SELECT serial_num, account_id, model_type, status, last_error_log
        FROM EQUIPMENT
        WHERE account_id = ?
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (account_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_equipment_by_serial(serial_num: str) -> Optional[Dict[str, Any]]:
    """Finds hardware details by serial number."""
    query = """
        SELECT serial_num, account_id, model_type, status, last_error_log
        FROM EQUIPMENT
        WHERE serial_num = ?
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (serial_num,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_subscription_plans() -> List[Dict[str, Any]]:
    """Returns available internet plans ordered by price."""
    query = """
        SELECT plan_id, name, monthly_cost_usd, max_speed_mbps
        FROM SUBSCRIPTION_PLANS
        ORDER BY monthly_cost_usd ASC
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, ())
        return [dict(row) for row in cursor.fetchall()]


def account_exists(account_id_or_name: Union[int, str]) -> bool:
    """Checks if an account exists by numeric ID or customer name."""
    is_numeric = isinstance(account_id_or_name, int) or (
        isinstance(account_id_or_name, str) and account_id_or_name.isdigit()
    )
    query = "SELECT 1 FROM ACCOUNTS WHERE account_id = ?" if is_numeric else "SELECT 1 FROM ACCOUNTS WHERE LOWER(customer_name) LIKE LOWER(?)"
    params = (int(account_id_or_name),) if is_numeric else (f"%{account_id_or_name}%",)

    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone() is not None


def ticket_exists_for_account(ticket_id: int, account_id: int) -> bool:
    """Confirms ticket exists and belongs to the specified account."""
    query = "SELECT 1 FROM SUPPORT_TICKETS WHERE ticket_id = ? AND account_id = ?"
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (ticket_id, account_id))
        return cursor.fetchone() is not None


def search_account_by_name(customer_name: str) -> Optional[Dict[str, Any]]:
    """Searches for an account by partial or full customer name."""
    query = """
        SELECT account_id, customer_name, address
        FROM ACCOUNTS
        WHERE LOWER(customer_name) LIKE LOWER(?)
        LIMIT 1
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (f"%{customer_name}%",))
        row = cursor.fetchone()
        return dict(row) if row else None


# --- WRITE OPERATIONS ---

def create_support_ticket(account_id: int, ticket_type: str, description: str) -> Dict[str, Any]:
    """Inserts a new open support ticket."""
    query = """
        INSERT INTO SUPPORT_TICKETS (account_id, ticket_type, status, description)
        VALUES (?, ?, 'open', ?)
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (account_id, ticket_type, description))
        ticket_id = cursor.lastrowid
        conn.commit()
        return get_ticket_by_id(ticket_id)


def schedule_technician_dispatch(account_id: int, description: str) -> Dict[str, Any]:
    """Schedules a technician dispatch by creating a dispatch ticket."""
    query = """
        INSERT INTO SUPPORT_TICKETS (account_id, ticket_type, status, description)
        VALUES (?, 'dispatch', 'open', ?)
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (account_id, description))
        ticket_id = cursor.lastrowid
        conn.commit()
        return get_ticket_by_id(ticket_id)


def update_account_address(account_id: int, new_address: str) -> Dict[str, Any]:
    """Updates the account's address and returns the refreshed account row."""
    query = "UPDATE ACCOUNTS SET address = ? WHERE account_id = ?"
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (new_address, account_id))
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return get_account_summary(account_id)


def apply_billing_credit(account_id: int, ticket_id: int, amount_usd: float) -> Dict[str, Any]:
    """Appends billing credit notification to a ticket description."""
    update_desc = f" [CREDIT APPLIED: ${amount_usd:.2f}]"
    query = """
        UPDATE SUPPORT_TICKETS
        SET description = description || ?
        WHERE ticket_id = ? AND account_id = ?
    """
    with db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (update_desc, ticket_id, account_id))
        conn.commit()
        return get_ticket_by_id(ticket_id)
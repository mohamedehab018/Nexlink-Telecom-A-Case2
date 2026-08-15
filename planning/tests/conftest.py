import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from planning import MCPToolExecutor  # noqa: E402
from planning.planning_lab.algorithms.decomposition import GeneratedPlan  # noqa: E402
from planning.planning_lab.algorithms.dynamic_decomposition import DynamicDecision  # noqa: E402


def build_temp_db(tmp_path: Path) -> str:
    """Seed a fresh copy of the real Nexlink database for the test session."""
    db_path = tmp_path / "nexlink.db"
    conn = sqlite3.connect(db_path)
    conn.executescript((REPO_ROOT / "db" / "schema.sql").read_text())
    conn.executescript((REPO_ROOT / "db" / "seed.sql").read_text())
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Point the real mcp_server db module at an isolated, seeded database."""
    path = build_temp_db(tmp_path)
    monkeypatch.setenv("NEXLINK_DB_PATH", path)
    return path


@pytest.fixture
def executor(db_path):
    return MCPToolExecutor(session_id="test-session")


class ScriptedLLM:
    """Deterministic fake model: returns scripted structured outputs for the
    planner calls and canned prose for reasoning nodes. Never touches the API.

    `plans` is a list of dicts (GeneratedPlan payloads), `decisions` a list of
    dicts (DynamicDecision payloads), consumed in order. `responses` is a list
    of (needle, content) tuples: plain `invoke` returns the first `content`
    whose needle appears in the human message, falling back to `prose`.
    `prompts` records the exact messages seen so tests can assert on real
    context/token growth.
    """

    def __init__(self, plans=None, decisions=None, prose="Completed the reasoning sub-task.", responses=None):
        self.plans = list(plans or [])
        self.decisions = list(decisions or [])
        self.prose = prose
        self.responses = list(responses or [])
        self.prompts = []

    class _Structured:
        def __init__(self, owner, schema):
            self.owner = owner
            self.schema = schema

        def invoke(self, messages, **kwargs):
            self.owner.prompts.append(messages)
            name = self.schema.__name__
            if name == "GeneratedPlan":
                if not self.owner.plans:
                    raise RuntimeError("No scripted plan left for decompose_goal")
                return self.schema.model_validate(self.owner.plans.pop(0))
            if name == "DynamicDecision":
                if not self.owner.decisions:
                    raise RuntimeError("No scripted decision left for dynamic loop")
                return self.schema.model_validate(self.owner.decisions.pop(0))
            raise RuntimeError(f"Unsupported structured schema {name}")

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        return self._Structured(self, schema)

    def invoke(self, messages, **kwargs):
        self.prompts.append(messages)
        text = " ".join(str(m[1]) for m in messages)
        for needle, content in self.responses:
            if needle in text:
                return SimpleNamespace(content=content)
        return SimpleNamespace(content=self.prose)

    @property
    def llm_calls(self) -> int:
        return len(self.prompts)

    @property
    def total_chars(self) -> int:
        return sum(len(str(m[1])) for msgs in self.prompts for m in msgs)


# --- scripted DAGs used by the decomposition tests --------------------------

def static_plan_with_verification() -> dict:
    return {
        "goal": "Resolve the outage incident for Walter White (account 2)",
        "tasks": [
            {"id": "diag", "instruction": "Fetch equipment diagnostics for account 2",
             "depends_on": [], "kind": "tool",
             "tool": "get_equipment_diagnostics", "args": {"account_id": 2}},
            {"id": "verify", "instruction": "Verify the account so write tools are unlocked",
             "depends_on": [], "kind": "tool",
             "tool": "verify_account_identity", "args": {"account_id": 2}},
            {"id": "dispatch", "instruction": "Schedule the technician dispatch for account 2",
             "depends_on": ["diag", "verify"], "kind": "tool",
             "tool": "schedule_technician_dispatch",
             "args": {"account_id": 2, "description": "Resolve total internet loss."}},
            {"id": "summary", "instruction": "Summarise the resolution for the staff",
             "depends_on": ["dispatch"], "kind": "synthesis"},
        ],
    }


def static_plan_missing_verification() -> dict:
    """The realistic failure mode: the planner assumes the session was already
    verified in a prior turn, so the write node has no verify dependency. On a
    fresh session the auth gate rejects the write at runtime."""
    return {
        "goal": "Resolve the outage incident for Walter White (account 2)",
        "tasks": [
            {"id": "diag", "instruction": "Fetch equipment diagnostics for account 2",
             "depends_on": [], "kind": "tool",
             "tool": "get_equipment_diagnostics", "args": {"account_id": 2}},
            {"id": "dispatch", "instruction": "Schedule the technician dispatch for account 2",
             "depends_on": ["diag"], "kind": "tool",
             "tool": "schedule_technician_dispatch",
             "args": {"account_id": 2, "description": "Resolve total internet loss."}},
            {"id": "summary", "instruction": "Summarise the resolution for the staff",
             "depends_on": ["dispatch"], "kind": "synthesis"},
        ],
    }


def dynamic_flow_that_adapts() -> list:
    """Scripted adaptive plan: the write is attempted first, hits the real
    SECURITY ERROR, and only then does the planner reshape the plan to verify
    the session and re-attempt the write."""
    return [
        {"done": False, "tool": "get_equipment_diagnostics", "tool_args": {"account_id": 2}},
        {"done": False, "tool": "schedule_technician_dispatch",
         "tool_args": {"account_id": 2, "description": "Resolve total internet loss."}},
        {"done": False, "tool": "verify_account_identity", "tool_args": {"account_id": 2}},
        {"done": False, "tool": "schedule_technician_dispatch",
         "tool_args": {"account_id": 2, "description": "Resolve total internet loss."}},
        {"done": True},
    ]


def dynamic_flow_known_verified() -> list:
    """Static-plan comparison: when the planner already knows the session is
    verified, dynamic decomposition behaves identically to decomposition-first."""
    return [
        {"done": False, "tool": "get_equipment_diagnostics", "tool_args": {"account_id": 2}},
        {"done": False, "tool": "verify_account_identity", "tool_args": {"account_id": 2}},
        {"done": False, "tool": "schedule_technician_dispatch",
         "tool_args": {"account_id": 2, "description": "Resolve total internet loss."}},
        {"done": True},
    ]

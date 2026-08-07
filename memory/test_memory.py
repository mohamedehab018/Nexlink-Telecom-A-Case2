import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory.system import MemorySystem
from memory.verification import verify_memory_recall


class MemoryTests(unittest.TestCase):
    def test_router_forgets_small_talk_and_promotes_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = MemorySystem(Path(tmp) / "m.db", max_items=1)
            m.remember("user", "Thanks!", "u")
            m.remember("user", "I requested a technician dispatch for account #22.", "u")
            m.remember("assistant", "Dispatch request was recorded.", "u")
            logs = m.store.conn.execute("SELECT destination FROM routing_log ORDER BY id").fetchall()
            self.assertEqual([x[0] for x in logs], ["forget", "episodic"])
            m.close()

    def test_consolidation_versions_conflicting_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = MemorySystem(Path(tmp) / "m.db", max_items=1)
            for text in ["My preferred contact method is SMS.", "overflow", "My preferred contact method changed to email.", "overflow"]:
                m.remember("user", text, "u")
            result = m.consolidation.run_if_due(force=True)
            self.assertEqual(m.store.fact_rows("u")[0]["value"], "email")
            self.assertEqual(len(result["conflicts"]), 1)
            history = m.fact_history("u:contact_preference")
            self.assertEqual([(row["version"], row["status"]) for row in history], [(1, "superseded"), (2, "active")])
            m.close()

    def test_verification_blocks_unsupported_claim(self):
        result = verify_memory_recall("What is my contact preference?", "contact preference: email", "contact preference: SMS")
        self.assertFalse(result.passed)

    def test_expiration_marks_semantic_fact_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = MemorySystem(Path(tmp) / "m.db", max_items=1)
            m.remember("user", "My preferred contact method is SMS.", "u")
            m.remember("assistant", "Noted.", "u")  # evicts the preference to episodic
            m.consolidation.run_if_due(force=True)
            expired = m.consolidation.run_if_due(now=datetime.now(timezone.utc) + timedelta(days=91), force=True)
            self.assertEqual(expired["expired"], 1)
            self.assertEqual(m.store.fact_rows("u"), [])
            self.assertEqual(m.fact_history("u:contact_preference")[0]["status"], "expired")
            m.close()


if __name__ == "__main__":
    unittest.main()

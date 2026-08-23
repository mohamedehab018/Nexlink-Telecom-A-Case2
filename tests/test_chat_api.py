"""Tests for backend/routes/chat.py (session management + endpoints).

The support agent is faked so these run offline without GROQ/RAG/MCP.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["NEXLINK_CHAT_DB"] = _tmp_db.name
os.environ.pop("GROQ_API_KEY", None)  # keep tests offline; /send must 503

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402


class _FakeAgent:
    """Minimal stand-in for the langgraph agent: echoes and records calls."""

    def __init__(self):
        self.turns = []

    async def ainvoke(self, payload, config=None):
        self.turns.append(payload)
        user_texts = [
            c for r, c in payload["messages"] if r == "user"
        ]
        return {"messages": [SimpleNamespace(
            content=f"echo:{user_texts[-1]}", tool_calls=[],
        )]}


def _install_fake_agent():
    import backend.routes.chat as chat
    chat._agent = _FakeAgent()
    return chat


class ChatApiTests(unittest.TestCase):
    def setUp(self):
        self.chat = _install_fake_agent()
        from backend.main import app
        self.client = TestClient(app)

    def test_history_unknown_session_404(self):
        r = self.client.get("/api/chat/history/does-not-exist")
        self.assertEqual(r.status_code, 404)

    def test_send_requires_message(self):
        r = self.client.post("/api/chat/send", json={"message": ""})
        self.assertEqual(r.status_code, 422)

    def test_send_without_api_key_is_503(self):
        import backend.routes.chat as chat
        chat._agent = None  # force lazy build path
        original = chat.create_support_agent

        async def _missing_key():
            raise RuntimeError(
                "Missing GROQ_API_KEY. Please set it in your environment or .env file."
            )

        chat.create_support_agent = _missing_key
        try:
            r = self.client.post("/api/chat/send", json={"message": "hi"})
        finally:
            chat.create_support_agent = original
            chat._agent = None
        self.assertEqual(r.status_code, 503)
        self.assertIn("GROQ_API_KEY", r.json()["detail"])

    def test_send_reply_and_history_roundtrip(self):
        r = self.client.post(
            "/api/chat/send",
            json={"message": "hello agent", "session_id": "s-1"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["session_id"], "s-1")
        self.assertEqual(body["reply"], "echo:hello agent")

        h = self.client.get("/api/chat/history/s-1").json()
        self.assertEqual([m["role"] for m in h["messages"]], ["user", "assistant"])
        self.assertEqual(h["messages"][0]["content"], "hello agent")
        self.assertEqual(h["messages"][1]["content"], "echo:hello agent")

    def test_sessions_are_isolated(self):
        self.client.post("/api/chat/send", json={"message": "one", "session_id": "a"})
        self.client.post("/api/chat/send", json={"message": "two", "session_id": "b"})

        ha = self.client.get("/api/chat/history/a").json()["messages"]
        hb = self.client.get("/api/chat/history/b").json()["messages"]
        self.assertEqual([m["content"] for m in ha], ["one", "echo:one"])
        self.assertEqual([m["content"] for m in hb], ["two", "echo:two"])

        # Rolling memory must also be isolated per session.
        sa = self.chat.session_state("a")
        contents = [i["content"] for i in sa["memory"].short_term.context()]
        self.assertIn("one", contents)
        self.assertNotIn("two", contents)

    def test_generated_session_id_when_absent(self):
        r = self.client.post("/api/chat/send", json={"message": "anon"})
        sid = r.json()["session_id"]
        self.assertTrue(sid.startswith("chat-"))
        self.assertEqual(r.status_code, 200)

    def test_sessions_index_lists_known_chats(self):
        self.client.post("/api/chat/send", json={"message": "x", "session_id": "idx-1"})
        sessions = self.client.get("/api/chat/sessions").json()
        self.assertTrue(any(s["session_id"] == "idx-1" for s in sessions))


if __name__ == "__main__":
    unittest.main(verbosity=2)

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.storage import RunStore


class RunStoreChatTests(unittest.TestCase):
    def test_chat_threads_and_messages_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(Path(tmpdir) / "runs.sqlite3")
            store.create_chat_thread(
                {
                    "thread_id": "thread-1",
                    "agent_name": "system_lead_agent",
                    "title": "Operator chat",
                }
            )
            store.add_chat_message(
                {
                    "message_id": "msg-1",
                    "thread_id": "thread-1",
                    "role": "user",
                    "content": "Nad czym pracujesz?",
                    "metadata_json": {"source": "operator"},
                }
            )
            store.add_chat_message(
                {
                    "message_id": "msg-2",
                    "thread_id": "thread-1",
                    "role": "assistant",
                    "content": "Pilnuję bezpiecznego zakresu zmian.",
                    "run_id": "run-1",
                    "metadata_json": {"current_focus": "scope control"},
                }
            )

            threads = store.list_chat_threads(limit=10)
            self.assertEqual(len(threads), 1)
            self.assertEqual(threads[0]["thread_id"], "thread-1")
            self.assertEqual(threads[0]["last_run_id"], "run-1")

            thread = store.get_chat_thread("thread-1")
            self.assertIsNotNone(thread)
            self.assertEqual(thread["agent_name"], "system_lead_agent")

            messages = store.list_chat_messages("thread-1", limit=10)
            self.assertEqual([item["message_id"] for item in messages], ["msg-1", "msg-2"])
            self.assertEqual(messages[0]["metadata_json"]["source"], "operator")
            self.assertEqual(messages[1]["metadata_json"]["current_focus"], "scope control")

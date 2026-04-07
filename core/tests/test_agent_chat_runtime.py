from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai_agents.runtime.service import AgentRuntimeService


class AgentChatRuntimeTests(unittest.TestCase):
    def test_execute_chat_returns_structured_reply_in_mock_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = SimpleNamespace(
                agent_context_packets_dir=Path(tmpdir) / "packets",
                agent_runtime_overrides_path=Path(tmpdir) / "agent_runtime_overrides.json",
                agent_use_mock_llm=True,
                agent_allow_mock_fallback=True,
                agent_litellm_base_url="http://localhost:4000/v1",
                agent_litellm_api_key="disabled",
            )
            service = AgentRuntimeService(settings=settings)
            model_tier = service.agent_profiles["system_lead_agent"].model_tier
            selected_model = service.model_profiles[model_tier].model

            result = service.execute_chat(
                run_record={
                    "run_id": "run-1",
                    "task_id": "task-1",
                    "agent_name": "system_lead_agent",
                    "model_tier": model_tier,
                    "model": selected_model,
                    "warnings_json": [],
                    "max_iterations": 1,
                    "max_retry_limit": 0,
                    "payload_json": {
                        "agent_name": "system_lead_agent",
                        "metadata": {
                            "chat_mode": True,
                            "chat_thread_id": "thread-1",
                            "chat_latest_user_message": "Co teraz robisz i czy powinieneś zmienić taktykę?",
                            "chat_history": [
                                {"role": "user", "content": "Cześć"}
                            ],
                            "chat_context": {
                                "current_work": [
                                    {
                                        "title": "Review next safe increment",
                                        "status": "running",
                                    }
                                ],
                                "recent_runs": [],
                            },
                        },
                    },
                },
                stop_requested_callback=lambda: False,
            )

            self.assertIn("reply", result["result_json"])
            self.assertIn("current_focus", result["result_json"])
            self.assertEqual(result["review_json"], None)
            self.assertEqual(result["retry_like_requests"], 0)

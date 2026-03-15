"""Regresyjne testy parsowania structured output z CrewAI."""

from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from ai_agents.runtime.crew_factory import CrewAIExecutionEngine
from ai_agents.runtime.schemas import CodingChangeOutput, CodingTaskPacketOutput, PlanOutput


class CrewAIOutputParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = CrewAIExecutionEngine(
            settings=SimpleNamespace(
                agent_litellm_base_url="http://localhost:4000",
                agent_litellm_api_key="test-key",
            ),
            agent_profiles={},
            model_profiles={},
        )

    def test_plan_output_falls_back_to_raw_when_json_dict_is_schema_like(self) -> None:
        crew_output = SimpleNamespace(
            tasks_output=[
                SimpleNamespace(
                    pydantic=None,
                    json_dict={
                        "summary": "Plan dla architektury.",
                        "recommended_actions": {
                            "title": "Recommended Actions",
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "affected_paths": {
                            "title": "Affected Paths",
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "review_required": True,
                        "human_decision_required": False,
                        "warnings": {
                            "title": "Warnings",
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    raw=json.dumps(
                        {
                            "summary": "Plan dla architektury.",
                            "recommended_actions": [
                                "Doprecyzuj przeplyw sterowania.",
                                "Oddziel control layer od execution layer.",
                            ],
                            "affected_paths": ["docs/ARCHITECTURE.md"],
                            "review_required": True,
                            "human_decision_required": False,
                            "warnings": [],
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            pydantic=None,
            json_dict=None,
            raw=None,
        )

        result = self.engine._extract_structured_output(crew_output, PlanOutput)

        self.assertEqual(result.summary, "Plan dla architektury.")
        self.assertEqual(
            result.recommended_actions,
            [
                "Doprecyzuj przeplyw sterowania.",
                "Oddziel control layer od execution layer.",
            ],
        )
        self.assertEqual(result.affected_paths, ["docs/ARCHITECTURE.md"])
        self.assertEqual(result.warnings, [])

    def test_coding_change_output_normalizes_nested_value_wrappers(self) -> None:
        crew_output = SimpleNamespace(
            tasks_output=[
                SimpleNamespace(
                    pydantic=None,
                    json_dict={
                        "summary": "Dodaj maly plik runtime.",
                        "file_edits": [
                            {
                                "path": {
                                    "title": "Path",
                                    "type": "string",
                                    "value": "core/generated_runtime_slice.py",
                                },
                                "content": {
                                    "title": "Content",
                                    "type": "string",
                                    "value": "SLICE_NAME = 'runtime'\\n",
                                },
                                "is_new_file": {
                                    "title": "Is New File",
                                    "type": "boolean",
                                    "value": True,
                                },
                                "rationale": {
                                    "title": "Rationale",
                                    "type": "string",
                                    "value": "Nowy, maly slice offline.",
                                },
                            }
                        ],
                        "notes": {
                            "title": "Notes",
                            "type": "array",
                            "value": ["Zmiana jest mala i odizolowana."],
                        },
                        "required_checks": {
                            "title": "Required Checks",
                            "type": "array",
                            "value": ["python -m compileall core"],
                        },
                    },
                    raw=None,
                )
            ],
            pydantic=None,
            json_dict=None,
            raw=None,
        )

        result = self.engine._extract_structured_output(crew_output, CodingChangeOutput)

        self.assertEqual(result.file_edits[0].path, "core/generated_runtime_slice.py")
        self.assertEqual(result.file_edits[0].content, "SLICE_NAME = 'runtime'\\n")
        self.assertTrue(result.file_edits[0].is_new_file)
        self.assertEqual(result.notes, ["Zmiana jest mala i odizolowana."])
        self.assertEqual(result.required_checks, ["python -m compileall core"])

    def test_coding_task_packet_uses_raw_when_schema_wrappers_leak_into_lists(self) -> None:
        crew_output = SimpleNamespace(
            tasks_output=[
                SimpleNamespace(
                    pydantic=None,
                    json_dict={
                        "summary": "Zadanie dla control layer.",
                        "module_id": "control_layer_runtime",
                        "owner_agent": "control_layer_agent",
                        "goal": "Dodac maly przyrost.",
                        "business_reason": "Zblizyc system do offline control layer.",
                        "owned_scope": "Owned Scope",
                        "read_only_context": "Read Only Context",
                        "target_files": "Target Files",
                        "forbidden_paths": "Forbidden Paths",
                        "risk_level": "low",
                        "acceptance_checks": "Acceptance Checks",
                        "required_tests": "Required Tests",
                        "definition_of_done": "Definition Of Done",
                        "warnings": "Warnings",
                        "review_required": True,
                        "human_decision_required": False,
                    },
                    raw=json.dumps(
                        {
                            "summary": "Zadanie dla control layer.",
                            "module_id": "control_layer_runtime",
                            "owner_agent": "control_layer_agent",
                            "goal": "Dodac maly przyrost.",
                            "business_reason": "Zblizyc system do offline control layer.",
                            "owned_scope": ["core/"],
                            "read_only_context": ["docs/ARCHITECTURE.md"],
                            "target_files": ["core/README.md"],
                            "forbidden_paths": [".env", "docker-compose.yml"],
                            "risk_level": "low",
                            "acceptance_checks": ["Zmiana zostaje w core/."],
                            "required_tests": ["python -m compileall core"],
                            "definition_of_done": ["Diff jest maly i reviewable."],
                            "warnings": [],
                            "review_required": True,
                            "human_decision_required": False,
                        },
                        ensure_ascii=False,
                    ),
                )
            ],
            pydantic=None,
            json_dict=None,
            raw=None,
        )

        result = self.engine._extract_structured_output(
            crew_output,
            CodingTaskPacketOutput,
        )

        self.assertEqual(result.owned_scope, ["core/"])
        self.assertEqual(result.target_files, ["core/README.md"])
        self.assertEqual(result.required_tests, ["python -m compileall core"])
        self.assertEqual(result.warnings, [])


if __name__ == "__main__":
    unittest.main()

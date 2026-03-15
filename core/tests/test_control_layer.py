"""Testy pierwszego przyrostu offline control layer."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

from core.control_layer import ControlLayerService, ControlRequest

FORBIDDEN_IMPORT_ROOTS = {
    "ccxt",
    "docker",
    "freqtrade",
    "httpx",
    "requests",
    "socket",
    "subprocess",
}


class ControlLayerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ControlLayerService()

    def test_dry_control_check_accepts_safe_request(self) -> None:
        request = ControlRequest(
            task_type="dry_control_check",
            payload={
                "subject": "bootstrap-control-layer",
                "checks": ["offline_only", "no_runtime", "no_secrets"],
                "require_all_green": True,
            },
            source="unit-test",
        )

        result = self.service.execute(request)

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.decision.accepted)
        self.assertEqual(result.output["check_count"], 3)
        self.assertEqual(result.output["mode"], "offline_only")

    def test_dry_control_check_rejects_runtime_and_secret_flags(self) -> None:
        request = ControlRequest(
            task_type="dry_control_check",
            payload={
                "subject": "unsafe-request",
                "checks": ["offline_only"],
                "touches_runtime": True,
                "uses_secrets": True,
            },
            source="unit-test",
        )

        result = self.service.execute(request)

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.decision.accepted)
        joined_reasons = " ".join(result.decision.reasons)
        self.assertIn("touches_runtime", joined_reasons)
        self.assertIn("uses_secrets", joined_reasons)

    def test_unknown_task_type_is_rejected_with_registry_hint(self) -> None:
        request = ControlRequest(
            task_type="unknown_task",
            payload={"subject": "unknown", "checks": ["offline_only"]},
            source="unit-test",
        )

        result = self.service.execute(request)

        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.decision.accepted)
        self.assertIn("dry_control_check", result.output["available_task_types"])

    def test_control_layer_module_has_no_forbidden_runtime_imports(self) -> None:
        module_dir = Path(__file__).resolve().parents[1] / "control_layer"
        violations: list[str] = []

        for path in sorted(module_dir.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module_name = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split(".")[0]
                        if module_name in FORBIDDEN_IMPORT_ROOTS:
                            violations.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module_name = node.module.split(".")[0]
                    if module_name in FORBIDDEN_IMPORT_ROOTS:
                        violations.append(f"{path}: from {node.module} import ...")

        self.assertEqual(
            violations,
            [],
            msg="Nowy control_layer nie może importować runtime tradingowego ani sieci.",
        )

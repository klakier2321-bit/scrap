from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.runtime_flags import load_runtime_flags, merge_runtime_flags


class RuntimeFlagsTests(unittest.TestCase):
    def test_load_defaults_when_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime_flags.json"
            self.assertEqual(
                load_runtime_flags(path),
                {
                    "kill_switch": False,
                    "runtime_freeze": False,
                },
            )

    def test_merge_persists_runtime_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime_flags.json"
            first = merge_runtime_flags(path, kill_switch=True)
            second = merge_runtime_flags(path, runtime_freeze=True)

            self.assertEqual(first["kill_switch"], True)
            self.assertEqual(second["kill_switch"], True)
            self.assertEqual(second["runtime_freeze"], True)
            self.assertEqual(load_runtime_flags(path), second)

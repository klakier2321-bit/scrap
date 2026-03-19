from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from monitoring import control_status


class ControlStatusTests(unittest.TestCase):
    def test_mask_sensitive_sanitizes_nested_text(self) -> None:
        payload = {
            "summary": "Bledy w /home/debian/crypto-system/data/ai_control/file.json dla admin@example.com",
            "nested": {
                "issue": "sekret token abcdefabcdefabcdefabcdef i url https://example.com/x",
            },
        }

        masked = control_status.mask_sensitive(payload)

        serialized = json.dumps(masked, ensure_ascii=False)
        self.assertNotIn("/home/debian/crypto-system", serialized)
        self.assertNotIn("admin@example.com", serialized)
        self.assertNotIn("https://example.com/x", serialized)

    def test_safe_filename_blocks_traversal(self) -> None:
        self.assertEqual(control_status._safe_filename("../etc/passwd"), "passwd")

    def test_write_outside_reports_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.json"
            with self.assertRaises(ValueError):
                control_status._atomic_write_json(outside, {"ok": True})

    def test_summary_does_not_expose_paths(self) -> None:
        report = {
            "generated_at": "2026-03-19T00:00:00+00:00",
            "overall_status": "warn",
            "summary": "Problem w /home/debian/crypto-system/data/ai_control/latest.json",
            "sources": [
                {
                    "source_name": "dry_run_snapshots",
                    "file_count": 1,
                    "latest_file_name": "latest.json",
                    "latest_generated_at": "2026-03-19T00:00:00+00:00",
                    "latest_status": "fresh",
                    "issues": ["Sciezka /tmp/test.json nie powinna wyciec."],
                    "latest_record": {"note": "/home/debian/crypto-system/secret"},
                }
            ],
        }

        summary = control_status.produce_summary_md(control_status.produce_anonymized_json(report))
        self.assertNotIn("/home/debian/crypto-system", summary)
        self.assertNotIn("/tmp/test.json", summary)


if __name__ == "__main__":
    unittest.main()

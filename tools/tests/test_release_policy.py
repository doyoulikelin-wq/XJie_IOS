from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class ReleasePolicyTests(unittest.TestCase):
    def test_ci_covers_xage_backend_and_never_swallows_failures(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main, XAGE]", workflow)
        self.assertIn("- 'backend/**'", workflow)
        self.assertIn("- 'quality/**'", workflow)
        self.assertIn("name: quality-gate", workflow)
        self.assertIn("set -o pipefail", workflow)
        self.assertNotIn("|| true", workflow)

    def test_release_script_requires_head_bound_gate_before_archive(self):
        script = (REPO_ROOT / "scripts" / "release_testflight.sh").read_text(encoding="utf-8")
        gate_position = script.index("run_regression_gate.py assert-release")
        archive_position = script.index("clean archive")
        export_position = script.index("-exportArchive")
        self.assertLess(gate_position, archive_position)
        self.assertLess(archive_position, export_position)

    def test_hooks_never_use_verify_bypass(self):
        hooks = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((REPO_ROOT / ".githooks").iterdir())
            if path.is_file()
        )
        self.assertIn("regression_guard.py", hooks)
        self.assertNotIn("--no-verify", hooks)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "python_test_gate.py"
SPEC = importlib.util.spec_from_file_location("python_test_gate", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def write_junit(path: Path, cases: list[tuple[str, str, str | None]]) -> None:
    root = ET.Element("testsuites", name="pytest tests")
    suite = ET.SubElement(root, "testsuite", tests=str(len(cases)))
    for module, name, skip_reason in cases:
        case = ET.SubElement(suite, "testcase", classname=module, name=name)
        if skip_reason is not None:
            ET.SubElement(case, "skipped", type="pytest.skip", message=skip_reason)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class PythonTestGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.required_node = next(iter(gate.REQUIRED_BACKEND_FULL_TESTS))
        module, _, name = self.required_node.partition("::")
        self.pass_case = (module, name, None)
        self.skip_cases = [
            (*node.partition("::")[::2], reason)
            for node, reason in gate.ALLOWED_BACKEND_FULL_SKIPS.items()
        ]
        self.selected_files = {
            gate.BACKEND_ROOT / (module.replace(".", "/") + ".py")
            for module, _, _ in [self.pass_case, *self.skip_cases]
        }

    def validate(self, cases, **overrides):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pytest.xml"
            write_junit(path, cases)
            arguments = {
                "profile": "full",
                "selected_files": self.selected_files,
                "minimum_tests": 1,
                "required_tests": {self.required_node},
                "allowed_skips": gate.ALLOWED_BACKEND_FULL_SKIPS,
                "expected_tests": {
                    f"{module}::{name}" for module, name, _ in [self.pass_case, *self.skip_cases]
                },
            }
            arguments.update(overrides)
            return gate.validate_backend_junit(path, **arguments)

    def test_exact_three_integration_skips_are_the_only_allowlist(self):
        self.assertEqual(
            gate.ALLOWED_BACKEND_FULL_SKIPS,
            {
                "tests.integration.test_api_chat_mock::test_chat_mock_placeholder": (
                    "requires dockerized postgres + redis stack"
                ),
                "tests.integration.test_api_glucose_import::test_glucose_import_flow_placeholder": (
                    "requires dockerized postgres + redis stack"
                ),
                "tests.integration.test_api_meals_flow::test_meals_photo_flow_placeholder": (
                    "requires dockerized postgres + redis stack"
                ),
            },
        )
        summary = self.validate([self.pass_case, *self.skip_cases])
        self.assertEqual(summary, {"executed": 4, "passed": 1, "skipped": 3})

    def test_unexpected_skip_fails_closed(self):
        cases = [
            self.pass_case,
            *self.skip_cases,
            ("tests.unit.test_safety_response", "test_new_skip", "temporary failure"),
        ]
        with self.assertRaisesRegex(gate.PythonTestGateError, "unexpected="):
            self.validate(cases)

    def test_allowlisted_skip_missing_or_reason_changed_requires_policy_update(self):
        module, name, _ = self.skip_cases[-1]
        no_longer_skipped = [*self.skip_cases[:-1], (module, name, None)]
        with self.assertRaisesRegex(gate.PythonTestGateError, "allowlist-not-skipped"):
            self.validate([self.pass_case, *no_longer_skipped])
        changed = list(self.skip_cases)
        module, name, _ = changed[0]
        changed[0] = (module, name, "some other dependency")
        with self.assertRaisesRegex(gate.PythonTestGateError, "reason-changed"):
            self.validate([self.pass_case, *changed])

    def test_mandatory_backend_test_missing_fails_closed(self):
        with self.assertRaisesRegex(gate.PythonTestGateError, "mandatory backend tests"):
            self.validate(
                [self.pass_case, *self.skip_cases],
                required_tests={"tests.unit.test_safety_response::test_required_but_missing"},
            )

    def test_backend_test_file_not_collected_fails_closed(self):
        missing_file = gate.BACKEND_ROOT / "tests/unit/test_not_collected.py"
        with self.assertRaisesRegex(gate.PythonTestGateError, "test files were not collected"):
            self.validate(
                [self.pass_case, *self.skip_cases],
                selected_files=self.selected_files | {missing_file},
            )

    def test_tool_inventory_rejects_missing_file_or_mandatory_method(self):
        self.assertEqual(gate.MINIMUM_TOOL_TESTS, 74)
        self.assertTrue((gate.TOOLS_TEST_ROOT / "test_verify_release_bundle.py").is_file())
        current_file = Path(__file__).resolve()
        gate.validate_tool_inventory(
            [self],
            expected_files={current_file},
            required_methods={self._testMethodName},
            minimum_tests=1,
            expected_ids={self.id()},
        )
        with self.assertRaisesRegex(gate.PythonTestGateError, "mandatory tool tests"):
            gate.validate_tool_inventory(
                [self],
                expected_files={current_file},
                required_methods={"test_missing_policy_guard"},
                minimum_tests=1,
                expected_ids={self.id()},
            )
        with self.assertRaisesRegex(gate.PythonTestGateError, "tool test files"):
            gate.validate_tool_inventory(
                [self],
                expected_files={current_file, current_file.with_name("test_missing.py")},
                required_methods={self._testMethodName},
                minimum_tests=1,
                expected_ids={self.id()},
            )

    def test_backend_exact_inventory_rejects_collection_disable_and_parameterization_shrink(self):
        module, _, _ = self.pass_case
        expected = {
            f"{case_module}::{name}"
            for case_module, name, _ in [self.pass_case, *self.skip_cases]
        }
        expected.update(
            {
                f"{module}.TestCollectionDisabled::test_hidden_contract",
                f"{module}::test_parameterized_contract[second-case]",
            }
        )
        with self.assertRaisesRegex(
            gate.PythonTestGateError,
            r"exact test inventory mismatch: missing=.*(?:TestCollectionDisabled|second-case)",
        ):
            self.validate(
                [self.pass_case, *self.skip_cases],
                expected_tests=expected,
            )

    def test_tool_exact_inventory_rejects_removed_testcase_and_duplicate_id(self):
        current_file = Path(__file__).resolve()
        removed = "test_removed_testcase.RemovedTestCase.test_required_contract"
        with self.assertRaisesRegex(gate.PythonTestGateError, "missing=.*RemovedTestCase"):
            gate.validate_tool_inventory(
                [self],
                expected_files={current_file},
                required_methods={self._testMethodName},
                minimum_tests=1,
                expected_ids={self.id(), removed},
            )
        with self.assertRaisesRegex(gate.PythonTestGateError, "duplicate test IDs"):
            gate.validate_tool_inventory(
                [self, self],
                expected_files={current_file},
                required_methods={self._testMethodName},
                minimum_tests=1,
                expected_ids={self.id()},
            )


if __name__ == "__main__":
    unittest.main()

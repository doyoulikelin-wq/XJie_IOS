from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_xcresult.py"
SPEC = importlib.util.spec_from_file_location("validate_xcresult", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def summary(*, total: int = 2, passed: int = 2, skipped: int = 0, failed: int = 0):
    return {
        "totalTestCount": total,
        "passedTests": passed,
        "skippedTests": skipped,
        "failedTests": failed,
        "expectedFailures": 0,
        "result": "Passed",
        "devicesAndConfigurations": [
            {"device": {"modelName": "iPhone SE (3rd generation)"}}
        ],
    }


def test_tree(results: tuple[tuple[str, str], ...] = (("testOne", "Passed"), ("testTwo", "Passed"))):
    return {
        "testNodes": [
            {
                "nodeType": "Test Plan",
                "testNodes": [
                    {
                        "nodeType": "Unit test bundle",
                        "testNodes": [
                            {
                                "nodeType": "Test Suite",
                                "testNodes": [
                                    {
                                        "nodeType": "Test Case",
                                        "nodeIdentifierURL": (
                                            "test://com.apple.xcode/Xjie/XjieTests/ExampleTests/"
                                            f"{name}()"
                                        ),
                                        "result": result,
                                    }
                                    for name, result in results
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


class XCResultValidatorTests(unittest.TestCase):
    def test_accepts_minimum_count_and_exact_required_test(self):
        report = validator.validate_payloads(
            summary(),
            test_tree(),
            minimum_tests=2,
            required_tests=["XjieTests/ExampleTests/testTwo"],
            required_device_model="iPhone SE (3rd generation)",
        )
        self.assertEqual(report["total"], 2)

    def test_zero_or_too_few_executed_tests_fail(self):
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                summary(total=0, passed=0),
                {"testNodes": []},
                minimum_tests=1,
                required_tests=[],
            )
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                summary(),
                test_tree(),
                minimum_tests=3,
                required_tests=[],
            )

    def test_skipped_or_failed_test_fails(self):
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                summary(total=2, passed=1, skipped=1),
                test_tree((("testOne", "Passed"), ("testTwo", "Skipped"))),
                minimum_tests=2,
                required_tests=[],
            )
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                summary(total=2, passed=1, failed=1),
                test_tree((("testOne", "Passed"), ("testTwo", "Failed"))),
                minimum_tests=2,
                required_tests=[],
            )

    def test_missing_required_test_fails_even_when_counts_are_green(self):
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                summary(),
                test_tree(),
                minimum_tests=2,
                required_tests=["XjieTests/ExampleTests/testRenamedOrNeverExecuted"],
            )

    def test_summary_and_tree_count_mismatch_fails(self):
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                summary(total=2, passed=2),
                test_tree((("testOne", "Passed"),)),
                minimum_tests=1,
                required_tests=[],
            )

    def test_wrong_or_missing_device_model_fails(self):
        wrong = summary()
        wrong["devicesAndConfigurations"][0]["device"]["modelName"] = "iPhone 17 Pro"
        with self.assertRaises(validator.XCResultValidationError):
            validator.validate_payloads(
                wrong,
                test_tree(),
                minimum_tests=2,
                required_tests=[],
                required_device_model="iPhone SE (3rd generation)",
            )

    def test_exact_profile_rejects_missing_extra_and_duplicate_tests(self):
        expected = [
            "XjieTests/ExampleTests/testOne",
            "XjieTests/ExampleTests/testTwo",
        ]
        report = validator.validate_payloads(
            summary(),
            test_tree(),
            minimum_tests=2,
            required_tests=[],
            expected_tests=expected,
        )
        self.assertEqual(report["expected_tests"], expected)

        for mutated_tree in (
            test_tree((("testOne", "Passed"), ("testUnexpected", "Passed"))),
            test_tree((("testOne", "Passed"), ("testOne", "Passed"))),
        ):
            with self.subTest(tree=mutated_tree), self.assertRaises(
                validator.XCResultValidationError
            ):
                validator.validate_payloads(
                    summary(),
                    mutated_tree,
                    minimum_tests=2,
                    required_tests=[],
                    expected_tests=expected,
                )

    def test_tracked_xctest_profiles_are_exact_and_self_consistent(self):
        profiles = validator.load_expected_test_profiles(
            validator.DEFAULT_EXPECTED_TESTS_PATH
        )
        validator.validate_swift_source_inventory(profiles)
        self.assertEqual(len(profiles["ios_unit"]), 158)
        self.assertEqual(len(profiles["ios_ui_full"]), 9)
        self.assertEqual(len(profiles["ios_ui_small"]), 2)
        self.assertEqual(len(profiles["ios_all"]), 167)

        valid_payload = {
            "schema_version": 1,
            "profiles": {
                "ios_unit": ["XjieTests/ExampleTests/testOne"],
                "ios_ui_full": ["XjieUITests/FlowTests/testFlow"],
                "ios_ui_small": ["XjieUITests/FlowTests/testFlow"],
                "ios_all": [
                    "XjieTests/ExampleTests/testOne",
                    "XjieUITests/FlowTests/testFlow",
                ],
            },
        }
        validator.validate_expected_test_profiles(valid_payload)
        for mutate in (
            lambda item: item.update(schema_version=2),
            lambda item: item["profiles"]["ios_unit"].append(
                "XjieTests/ExampleTests/testOne"
            ),
            lambda item: item["profiles"]["ios_ui_small"].append(
                "XjieUITests/OtherTests/testOther"
            ),
            lambda item: item["profiles"]["ios_all"].pop(),
        ):
            invalid = copy.deepcopy(valid_payload)
            mutate(invalid)
            with self.assertRaises(validator.XCResultValidationError):
                validator.validate_expected_test_profiles(invalid)


if __name__ == "__main__":
    unittest.main()

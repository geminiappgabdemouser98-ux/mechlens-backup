"""Offline tests of publish-blocking decisions and real pytest evidence collection."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.release_readiness import assess, load_json, markdown

ROOT = Path(__file__).resolve().parents[3]
COMMIT = "a" * 40
POLICY = {"schema_version": 1, "required_suites": ["acceptance"]}


def evidence():
    return {
        "schema_version": 1,
        "suite": "acceptance",
        "commit": COMMIT,
        "run_id": "17",
        "run_attempt": "2",
        "exit_code": 0,
        "dirty_worktree": False,
        "deselected": [],
        "collection_problems": [],
        "cases": [
            {
                "nodeid": "test_model.py::test_parity",
                "phases": [
                    {"when": when, "outcome": "passed", "xfail": None}
                    for when in ("setup", "call", "teardown")
                ],
            }
        ],
    }


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def assess(self, value=None, policy=None, checks_result="success"):
        if value is not None:
            (self.folder / "evidence.json").write_text(json.dumps(value))
        return assess(policy or POLICY, self.folder, COMMIT, "17", "2", checks_result)

    def test_complete_current_evidence_passes(self):
        report = self.assess(evidence())
        self.assertTrue(report["ready"])
        self.assertEqual(report["suites"][0]["case_count"], 1)
        self.assertIn("PASS", markdown(report))

    def test_missing_empty_and_malformed_evidence_block(self):
        self.assertFalse(self.assess()["ready"])
        for value in ([], {}, {**evidence(), "cases": []}, {**evidence(), "cases": "bad"}):
            with self.subTest(value=value):
                self.assertFalse(self.assess(value)["ready"])

    def test_wrong_commit_run_or_attempt_blocks(self):
        for field in ("commit", "run_id", "run_attempt"):
            with self.subTest(field=field):
                value = evidence()
                value[field] = "stale"
                self.assertFalse(self.assess(value)["ready"])

    def test_dirty_or_unrecorded_worktree_blocks(self):
        for state in (True, None):
            self.assertFalse(self.assess({**evidence(), "dirty_worktree": state})["ready"])

    def test_failed_cancelled_or_skipped_checks_block(self):
        for result in ("failure", "cancelled", "skipped", "unknown"):
            self.assertFalse(self.assess(evidence(), checks_result=result)["ready"])

    def test_skips_xfails_xpasses_failures_and_retries_block(self):
        for outcome, xfail in (
            ("skipped", None),
            ("skipped", "known bug"),
            ("passed", "unexpected pass"),
            ("failed", None),
            ("rerun", None),
        ):
            with self.subTest(outcome=outcome, xfail=xfail):
                value = evidence()
                value["cases"][0]["phases"][1].update(outcome=outcome, xfail=xfail)
                self.assertFalse(self.assess(value)["ready"])

    def test_setup_teardown_and_missing_call_block(self):
        for phase in (0, 2):
            value = evidence()
            value["cases"][0]["phases"][phase]["outcome"] = "failed"
            self.assertFalse(self.assess(value)["ready"])
        value = evidence()
        value["cases"][0]["phases"].pop(1)
        self.assertFalse(self.assess(value)["ready"])

    def test_collection_problem_deselection_and_nonzero_exit_block(self):
        for field, value in (
            ("collection_problems", ["error"]),
            ("deselected", ["test_slow"]),
            ("exit_code", 1),
            ("exit_code", False),
        ):
            candidate = evidence()
            candidate[field] = value
            self.assertFalse(self.assess(candidate)["ready"])

    def test_duplicate_suite_and_duplicate_cases_block(self):
        (self.folder / "duplicate.json").write_text(json.dumps(evidence()))
        self.assertFalse(self.assess(evidence())["ready"])
        (self.folder / "duplicate.json").unlink()
        value = evidence()
        value["cases"].append(copy.deepcopy(value["cases"][0]))
        self.assertFalse(self.assess(value)["ready"])

    def test_invalid_json_nonfinite_and_unknown_suite_block(self):
        for content in (
            "{",
            '{"suite": "acceptance", "metric": NaN}',
            '{"suite": "acceptance", "metric": 1e999}',
        ):
            (self.folder / "bad.json").write_text(content)
            self.assertFalse(self.assess(evidence())["ready"])
        (self.folder / "bad.json").unlink()
        value = evidence()
        value["suite"] = "unrequested"
        self.assertFalse(self.assess(value)["ready"])

    def test_empty_or_duplicate_policy_blocks(self):
        for required in ([], ["acceptance", "acceptance"], [{}]):
            self.assertFalse(
                self.assess(evidence(), {"schema_version": 1, "required_suites": required})["ready"]
            )

    def test_cli_writes_blocked_report_and_exits_nonzero(self):
        policy = self.folder / "policy.json"
        policy.write_text(json.dumps(POLICY))
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/release_readiness.py"),
                "--policy",
                str(policy),
                "--evidence-dir",
                str(self.folder / "missing"),
                "--commit",
                COMMIT,
                "--run-id",
                "17",
                "--run-attempt",
                "2",
                "--checks-result",
                "success",
                "--output-dir",
                str(self.folder / "report"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(load_json(self.folder / "report/readiness.json")["ready"])


class RecorderTests(unittest.TestCase):
    def test_real_pytest_records_failures_skips_xfails_and_deselection(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            test = folder / "test_sample.py"
            test.write_text(
                "import pytest\n"
                "def test_pass(record_property): record_property('max_delta', 0.000029)\n"
                "def test_failure(): assert False\n"
                "@pytest.mark.skip(reason='no token')\ndef test_skip(): pass\n"
                "@pytest.mark.xfail(reason='known')\ndef test_xfail(): assert False\n"
                "def test_excluded(): pass\n"
            )
            destination = folder / "result.json"
            environment = dict(
                os.environ,
                PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                PYTEST_ADDOPTS="",
                TL_RELEASE_EVIDENCE=str(destination),
                TL_RELEASE_SUITE="acceptance",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-c",
                    "/dev/null",
                    "--noconftest",
                    "-p",
                    "scripts.release_evidence",
                    str(test),
                    "-k",
                    "not excluded",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            recorded = load_json(destination)
            self.assertEqual(len(recorded["cases"]), 4)
            self.assertEqual(len(recorded["deselected"]), 1)
            self.assertEqual(recorded["exit_code"], 1)
            passed = next(c for c in recorded["cases"] if c["nodeid"].endswith("test_pass"))
            self.assertIn(["max_delta", 0.000029], passed["properties"])
            self.assertTrue(any(p["xfail"] for c in recorded["cases"] for p in c["phases"]))


class WorkflowTests(unittest.TestCase):
    def test_inventory_matches_workflow_matrix(self):
        import yaml

        checks = yaml.safe_load((ROOT / ".github/workflows/checks.yml").read_text())
        notebook_matrix = checks["jobs"]["notebook-checks"]["strategy"]["matrix"]
        notebooks = notebook_matrix["notebook"] + [
            entry["notebook"] for entry in notebook_matrix["include"]
        ]
        python_versions = checks["jobs"]["compatibility-checks"]["strategy"]["matrix"][
            "python-version"
        ]
        expected = {"norm-regression"}
        expected.update("acceptance-" + version for version in python_versions)
        expected.update("notebook-" + notebook for notebook in notebooks)
        self.assertEqual(
            set(load_json(ROOT / "release/readiness-policy.json")["required_suites"]), expected
        )

    def test_publisher_requires_readiness_and_gate_cannot_ignore_failure(self):
        import yaml

        release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
        self.assertIn("checks", release["jobs"]["release-python"]["needs"])
        self.assertEqual(
            release["jobs"]["checks"]["uses"], "./.github/workflows/release-readiness.yml"
        )
        workflow = yaml.safe_load((ROOT / ".github/workflows/release-readiness.yml").read_text())
        gate = workflow["jobs"]["readiness"]
        self.assertEqual(gate["needs"], "checks")
        self.assertEqual(gate["if"], "always()")
        step = next(
            step for step in gate["steps"] if "scripts/release_readiness.py" in step.get("run", "")
        )
        self.assertNotIn("continue-on-error", step)
        self.assertIn("--checks-result", step["run"])
        self.assertIn("--run-attempt", step["run"])
        self.assertNotIn("||", step["run"])
        self.assertNotIn("publish", " ".join(step.get("run", "") for step in gate["steps"]))


if __name__ == "__main__":
    unittest.main()

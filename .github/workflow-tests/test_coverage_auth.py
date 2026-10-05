"""Keep authenticated coverage publication required across reusable callers."""

import copy
import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = "codecov/codecov-action@303a32d7a59b442fa8d48b6a1cc6825c09c847a5"


def validate(policy, workflows):
    """Reject lost OIDC forwarding, unrelated grants or optional uploads."""
    assert policy["validation_oidc_workflows"] == ["python-ci.yml"]
    ci, quality, release = (
        workflows[name] for name in ("python-ci", "quality-gate", "release-pipeline")
    )
    for workflow in workflows.values():
        assert workflow["permissions"].get("id-token", "none") == "none"
    for workflow, selected in ((ci, "test"), (quality, "check-0"), (release, "checks")):
        for name, job in workflow["jobs"].items():
            assert job.get("permissions", {}).get("id-token", "none") == (
                "write" if name == selected else "none"
            )
    test = ci["jobs"]["test"]
    assert test["permissions"]["contents"] == "read"
    assert not test.get("continue-on-error", False)
    upload = next(step for step in test["steps"] if step.get("name") == "Upload coverage")
    assert upload["uses"] == ACTION
    assert upload["with"] == {"files": "./coverage.xml", "fail_ci_if_error": True, "use_oidc": True}
    assert "if" not in upload and not upload.get("continue-on-error", False)
    checks = next(step for step in test["steps"] if step.get("name") == "Test")
    assert "--cov-fail-under=80" in checks["run"] and not checks.get("continue-on-error", False)
    caller = quality["jobs"]["check-0"]
    assert caller["uses"] == "./.github/workflows/python-ci.yml"
    assert release["jobs"]["checks"]["uses"] == "./.github/workflows/quality-gate.yml"
    assert "check-0" in quality["jobs"]["gate"]["needs"]
    contracts = quality["jobs"]["workflow-contracts"]
    assert any(
        "-s .github/workflow-tests -p 'test_*.py'" in step.get("run", "")
        for step in contracts["steps"]
    )


class CoverageAuthTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / ".release-policy.json").read_text())
        self.workflows = {
            name: yaml.safe_load((ROOT / ".github/workflows" / (name + ".yml")).read_text())
            for name in ("python-ci", "quality-gate", "release-pipeline")
        }

    def test_current_coverage_auth_contract(self):
        validate(self.policy, self.workflows)

    def test_every_permission_hop_is_required(self):
        for workflow, job in (
            ("python-ci", "test"),
            ("quality-gate", "check-0"),
            ("release-pipeline", "checks"),
        ):
            changed = copy.deepcopy(self.workflows)
            changed[workflow]["jobs"][job]["permissions"].pop("id-token", None)
            with self.subTest(workflow=workflow), self.assertRaises(AssertionError):
                validate(self.policy, changed)

    def test_unrelated_jobs_cannot_issue_identity_tokens(self):
        changed = copy.deepcopy(self.workflows)
        changed["quality-gate"]["jobs"]["check-1"]["permissions"]["id-token"] = "write"
        with self.assertRaises(AssertionError):
            validate(self.policy, changed)

    def test_authentication_and_failure_handling_cannot_be_disabled(self):
        for field in ("use_oidc", "fail_ci_if_error"):
            changed = copy.deepcopy(self.workflows)
            upload = next(
                s
                for s in changed["python-ci"]["jobs"]["test"]["steps"]
                if s.get("name") == "Upload coverage"
            )
            upload["with"][field] = False
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate(self.policy, changed)

    def test_optional_upload_is_rejected(self):
        changed = copy.deepcopy(self.workflows)
        upload = next(
            s
            for s in changed["python-ci"]["jobs"]["test"]["steps"]
            if s.get("name") == "Upload coverage"
        )
        upload["continue-on-error"] = True
        with self.assertRaises(AssertionError):
            validate(self.policy, changed)

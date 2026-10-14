"""Exercise the vendored fuzz safety boundary in the consumer coverage suite.

These portable regression cases are adapted from the shared toolkit. Native
Atheris replay remains in the deterministic preflight CI job; these tests verify
that invalid evidence and unsafe inputs fail before any campaign can run.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import fuzz_python_preflight as python_preflight  # noqa: E402
import release_fuzz as fuzz  # noqa: E402


def policy():
    return {
        "mode": "release",
        "repository": "owner/repo",
        "visibility": "public",
        "versioning": {"example": True},
        "fuzzing": {"toolkit_ref": "a" * 40},
    }


def config():
    return {
        "schema": 1,
        "language": "go",
        "setup": [["go", "mod", "download"]],
        "targets": [
            {
                "name": "parse",
                "engine": "go",
                "command": ["go", "test", "-fuzz=^FuzzParse$"],
                "seconds": 60,
            }
        ],
    }


class FuzzSafetyContracts(unittest.TestCase):
    def test_isolated_environment_retains_jdk_location_without_ambient_jvm_options(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real_popen = subprocess.Popen

            def namespace_stub(command, **kwargs):
                self.assertIn("--net", command)
                self.assertIn(f"--setuid={os.getuid()}", command)
                return real_popen(command[command.index("/usr/bin/env") :], **kwargs)

            environment = {
                "JAVA_HOME": "/synthetic/jdk-17",
                "JAVA_TOOL_OPTIONS": "-Xmx99g",
                "JDK_JAVA_OPTIONS": "--invalid-option",
                "GH_TOKEN": "synthetic-test-value",
            }
            code = (
                "import json,os; print(json.dumps({k:os.environ.get(k) for k in "
                + repr(list(environment))
                + "}))"
            )
            output = root / "run.log"
            with (
                patch.dict(os.environ, environment),
                patch.object(fuzz.subprocess, "Popen", side_effect=namespace_stub),
            ):
                result, _ = fuzz.execute([sys.executable, "-c", code], root, output, 20, True)
            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(output.read_text()),
                {
                    "JAVA_HOME": "/synthetic/jdk-17",
                    "JAVA_TOOL_OPTIONS": None,
                    "JDK_JAVA_OPTIONS": None,
                    "GH_TOKEN": None,
                },
            )

    def test_isolated_command_preserves_real_virtual_environment_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            environment = root / ".fuzz-venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
            real_popen = subprocess.Popen
            commands = []

            def namespace_stub(command, **kwargs):
                commands.append(command)
                # Exercise the real env/interpreter subprocess without requiring
                # privileged Linux namespaces on a developer's macOS machine.
                return real_popen(command[command.index("/usr/bin/env") :], **kwargs)

            output = root / "run.log"
            with patch.object(fuzz.subprocess, "Popen", side_effect=namespace_stub):
                code, _ = fuzz.execute(
                    [".fuzz-venv/bin/python", "-c", "import sys; print(sys.prefix)"],
                    root,
                    output,
                    20,
                    True,
                )
            self.assertEqual(code, 0)
            self.assertEqual(output.read_text().strip(), str(environment))
            self.assertIn("--net", commands[0])
            self.assertIn(f"--setuid={os.getuid()}", commands[0])

    def test_only_public_default_branch_rc_dispatch_is_accepted(self):
        event = {
            "inputs": {"channel": "rc"},
            "repository": {"private": False, "full_name": "owner/repo", "default_branch": "main"},
        }
        fuzz.event_contract(event, "workflow_dispatch", "refs/heads/main", "owner/repo", "a" * 40)
        for name in ("push", "schedule", "pull_request", "pull_request_target", "workflow_run"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                fuzz.event_contract(event, name, "refs/heads/main", "owner/repo", "a" * 40)
        for channel in ("beta", "nightly", "stable", None):
            bad = copy.deepcopy(event)
            bad["inputs"]["channel"] = channel
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                fuzz.event_contract(
                    bad, "workflow_dispatch", "refs/heads/main", "owner/repo", "a" * 40
                )
        for private in (True, None, "false", 0):
            bad = copy.deepcopy(event)
            bad["repository"]["private"] = private
            with self.subTest(private=private), self.assertRaises(ValueError):
                fuzz.event_contract(
                    bad, "workflow_dispatch", "refs/heads/main", "owner/repo", "a" * 40
                )
        with self.assertRaises(ValueError):
            fuzz.event_contract(
                event, "workflow_dispatch", "refs/heads/feature", "owner/repo", "a" * 40
            )

    def test_policy_rejects_private_unpinned_and_nonrelease(self):
        self.assertIsNone(fuzz.configuration({}))
        fuzz.configuration(policy())
        for key, value in (
            ("visibility", "private"),
            ("mode", "validation-only"),
            ("ci_execution", "local"),
            ("versioning", None),
            ("fuzzing", {"toolkit_ref": "main"}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                fuzz.configuration({**policy(), key: value})

    def test_manifest_rejects_escape_unbounded_commands_and_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".github").mkdir()
            target = root / fuzz.MANIFEST
            target.write_text(json.dumps(config()))
            fuzz.manifest(root)
            invalid = []
            for key, value in (
                ("seconds", 0),
                ("seconds", True),
                ("seconds", 121),
                ("cwd", "../outside"),
                ("command", "sh -c true"),
                ("command", ["go", "test", "-fuzztime=0"]),
            ):
                bad = config()
                bad["targets"][0][key] = value
                invalid.append(bad)
            bad = config()
            bad["targets"] *= 2
            invalid.append(bad)
            bad = config()
            bad["targets"] = [
                {**bad["targets"][0], "name": f"target-{i}", "seconds": 120} for i in range(6)
            ]
            invalid.append(bad)
            for bad in invalid:
                target.write_text(json.dumps(bad))
                with self.subTest(config=bad), self.assertRaises(ValueError):
                    fuzz.manifest(root)
            (root / "escape").symlink_to(root.parent)
            bad = config()
            bad["targets"][0]["cwd"] = "escape"
            target.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                fuzz.manifest(root)

    def test_zero_work_success_is_not_fuzzing_evidence(self):
        self.assertFalse(fuzz.exercised("go", "PASS: no fuzz tests to fuzz"))
        self.assertFalse(fuzz.exercised("go", "fuzz: elapsed: 0s, execs: 0"))
        self.assertTrue(
            fuzz.exercised("go", "fuzz: elapsed: 3s, execs: 1234 (411/sec), new interesting: 2")
        )
        self.assertTrue(fuzz.exercised("atheris", "Done 49210 runs in 61 second(s)"))
        self.assertFalse(fuzz.exercised("libfuzzer", "Done 0 runs in 0 second(s)"))

    def test_run_proof_rejects_missing_wrong_source_duplicate_or_skipped_campaign(self):
        job = {
            "name": fuzz.JOB,
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        fuzz.check_run_jobs([job], "rc", "a" * 40)
        for jobs in (
            [],
            [job, job],
            [{**job, "head_sha": "b" * 40}],
            [{**job, "conclusion": "skipped"}],
            [{**job, "status": "in_progress"}],
        ):
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                fuzz.check_run_jobs(jobs, "rc", "a" * 40)
        for channel in ("beta", "stable", "nightly"):
            fuzz.check_run_jobs([], channel, "a" * 40)
            with self.assertRaises(ValueError):
                fuzz.check_run_jobs([job], channel, "a" * 40)

    def test_report_binds_every_target_manifest_source_and_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".github").mkdir()
            (root / fuzz.MANIFEST).write_text(json.dumps(config()))
            report = {
                "schema": 1,
                "repository": "owner/repo",
                "source_sha": "a" * 40,
                "run_id": 42,
                "run_attempt": 2,
                "channel": "rc",
                "private": False,
                "manifest_sha256": hashlib.sha256((root / fuzz.MANIFEST).read_bytes()).hexdigest(),
                "status": "passed",
                "network": "isolated",
                "targets": [{"name": "parse", "seconds": 60, "exit_code": 0}],
            }
            path = root / fuzz.REPORT
            path.write_text(json.dumps(report))
            fuzz.verify_report(root, root, "owner/repo", "a" * 40, 42, 2)
            for key, value in (
                ("source_sha", "b" * 40),
                ("run_attempt", 1),
                ("targets", []),
                ("targets", [{"name": "parse", "seconds": 60, "exit_code": False}]),
                ("status", "failed"),
                ("private", 0),
            ):
                path.write_text(json.dumps({**report, key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    fuzz.verify_report(root, root, "owner/repo", "a" * 40, 42, 2)

    def test_schema_two_requires_actual_work_and_declared_instrumentation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".github").mkdir()
            config = {
                "schema": 1,
                "language": "python",
                "setup": [],
                "targets": [
                    {
                        "name": "parse",
                        "engine": "atheris",
                        "command": ["python", "fuzz.py"],
                        "seconds": 1,
                        "instrumentation": [{"module": "owned", "functions": ["parse"]}],
                    }
                ],
            }
            source = root / fuzz.MANIFEST
            source.write_text(json.dumps(config))
            proof = {
                "target": "parse",
                "engine": "atheris",
                "executions": 3,
                "instrumentation": [{"module": "owned", "function": "parse"}],
            }
            report = {
                "schema": 2,
                "repository": "o/r",
                "source_sha": "a" * 40,
                "run_id": 1,
                "run_attempt": 1,
                "channel": "rc",
                "private": False,
                "status": "passed",
                "network": "isolated",
                "manifest_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "targets": [
                    {
                        "name": "parse",
                        "seconds": 1,
                        "exit_code": 0,
                        "engine": "atheris",
                        "executions": 100,
                    }
                ],
                "preflight": {"python_targets": [proof], "commands": 0},
            }
            for count, proofs, accepted in (
                (100, [proof], True),
                (0, [proof], False),
                (True, [proof], False),
                (100, [], False),
                (100, [{**proof, "executions": 0}], False),
                (100, [{**proof, "executions": True}], False),
                (100, [{**proof, "executions": None}], False),
            ):
                report["targets"][0]["executions"] = count
                report["preflight"]["python_targets"] = proofs
                (root / fuzz.REPORT).write_text(json.dumps(report))
                if accepted:
                    fuzz.verify_report(root, root, "o/r", "a" * 40, 1, 1)
                else:
                    with self.assertRaises(ValueError):
                        fuzz.verify_report(root, root, "o/r", "a" * 40, 1, 1)
            report["schema"] = 1
            (root / fuzz.REPORT).write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "schema-2"):
                fuzz.verify_report(root, root, "o/r", "a" * 40, 1, 1)

    def test_preflight_diff_rejects_arguments_at_the_process_boundary(self):
        import change_scope

        for revisions in (
            ("--output=/tmp/unsafe", "b" * 40, ".."),
            ("a" * 40, "--ext-diff", "..."),
            ("a" * 40, "b" * 40, " -- "),
        ):
            with (
                patch.object(change_scope, "event_revisions", return_value=revisions),
                patch.object(fuzz.subprocess, "check_output") as query,
            ):
                with self.assertRaises(ValueError):
                    fuzz.preflight_changed_paths(ROOT, "pull_request", {})
                query.assert_not_called()

    def test_corpus_retains_regular_inputs_with_hard_storage_caps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "cache/fuzz/example/FuzzParse"
            source.mkdir(parents=True)
            (source / "a").write_bytes(b"first")
            (source / "b").write_bytes(b"second")
            (source / "external").symlink_to(root / "secret")
            (root / "secret").write_bytes(b"never copy")
            with patch.object(fuzz, "CORPUS_BYTES", 6):
                report = fuzz.retain_corpus(root / "cache/fuzz", root / "out")
            self.assertEqual(report, {"files": 1, "bytes": 5, "truncated": True})
            self.assertEqual((root / "out/example/FuzzParse/a").read_bytes(), b"first")
            self.assertFalse((root / "out/example/FuzzParse/external").exists())

    def test_declared_preflight_corpus_is_required_and_walk_errors_propagate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = {"name": "parse", "corpus": "missing"}
            with self.assertRaisesRegex(ValueError, "existing directory"):
                fuzz.replay_python_target(root, root, target, 100)
            self.assertEqual(
                fuzz.retain_corpus(root / "absent-go-cache", root / "optional")["files"], 0
            )
            source = root / "source"
            source.mkdir()

            def unreadable(_source, *, onerror, **_kwargs):
                onerror(PermissionError("unreadable corpus"))
                return iter(())

            with patch.object(fuzz.os, "walk", side_effect=unreadable):
                with self.assertRaisesRegex(PermissionError, "unreadable corpus"):
                    fuzz.retain_corpus(source, root / "required", required=True)

    def test_required_corpus_rejects_missing_file_symlink_and_empty_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "file").write_bytes(b"seed")
            (root / "empty").mkdir()
            (root / "link").symlink_to(root / "empty", target_is_directory=True)
            for name in ("missing", "file", "empty", "link"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    fuzz.retain_corpus(root / name, root / (name + "-out"), required=True)
            (root / "escape").symlink_to(root.parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "outside source"):
                fuzz.confined(root, "escape")
            (root / "seeds").mkdir()
            (root / "seeds/empty-seed").write_bytes(b"")
            self.assertEqual(
                fuzz.retain_corpus(root / "seeds", root / "good", required=True)["files"], 1
            )
            for linked in (root / "file", root / "empty"):
                link = root / "seeds/linked"
                link.symlink_to(linked, target_is_directory=linked.is_dir())
                with (
                    self.subTest(linked=linked),
                    self.assertRaisesRegex(ValueError, "contain symlinks"),
                ):
                    fuzz.retain_corpus(root / "seeds", root / "rejected", required=True)
                link.unlink()

    def test_go_target_retains_generated_cache_outside_testdata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = root / "cache/fuzz/example/FuzzParse"
            generated.mkdir(parents=True)
            (generated / "interesting").write_text('go test fuzz v1\n[]byte("x")\n')

            def execute(_command, _cwd, output, _timeout, _isolated):
                output.write_text("fuzz: elapsed: 1s, execs: 23, new interesting: 1\n")
                return 0, 1.0

            with (
                patch.object(fuzz, "execute", side_effect=execute),
                patch.object(fuzz.subprocess, "check_output", return_value=str(root / "cache")),
            ):
                report = fuzz.run_target(
                    root,
                    root,
                    {
                        "name": "parse",
                        "seconds": 1,
                        "engine": "go",
                        "command": ["go", "test", "-fuzz=FuzzParse"],
                    },
                )
            self.assertEqual(report["executions"], 23)
            self.assertEqual(report["generated_corpus"]["files"], 1)
            self.assertTrue(
                (root / "parse/go-generated-corpus/example/FuzzParse/interesting").is_file()
            )

    def test_libfuzzer_metrics_use_completed_engine_work(self):
        result = fuzz.engine_metrics(
            "atheris", "#123 DONE cov: 10 ft: 20 corp: 3/10b\nDone 123 runs in 1 second(s)"
        )
        self.assertEqual(
            result,
            {"engine": "atheris", "executions": 123, "coverage_edges": 10, "coverage_features": 20},
        )
        self.assertEqual(fuzz.engine_metrics("atheris", "no target")["executions"], 0)

    def test_go_wrapper_queries_selected_go_in_declared_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "engine").mkdir()
            (root / "engine/go.mod").write_text("module example.invalid/engine\ngo 1.26\n")

            def execute(_command, _cwd, output, _timeout, _isolated):
                output.write_text("fuzz: elapsed: 1s, execs: 23, new interesting: 0\n")
                return 0, 1.0

            with (
                patch.object(fuzz, "execute", side_effect=execute),
                patch.object(
                    fuzz.subprocess, "check_output", return_value=str(root / "cache")
                ) as query,
            ):
                report = fuzz.run_target(
                    root,
                    root,
                    {
                        "name": "parse",
                        "seconds": 1,
                        "engine": "go",
                        "command": ["python3", "engine/build.py", "fuzz"],
                    },
                    go_version_file="engine/go.mod",
                )
            query.assert_called_once_with(
                ["go", "env", "GOCACHE"], cwd=root / "engine", text=True, timeout=30
            )
            self.assertEqual(report["generated_corpus"]["files"], 0)

    def test_instrumentation_requires_loaded_project_functions_and_idempotence(self):
        def owned():
            return 1

        declaration = [{"module": "audit_owned", "functions": ["owned"]}]
        with patch.dict(sys.modules, {"audit_owned": SimpleNamespace(owned=owned)}):
            good = SimpleNamespace(instrument_func=lambda function: function)
            self.assertEqual(
                len(python_preflight.verify_instrumentation(declaration, ROOT, good)), 1
            )

            def missing(function):
                function.__code__ = (lambda: 2).__code__

            with self.assertRaisesRegex(ValueError, "Missing production instrumentation"):
                python_preflight.verify_instrumentation(
                    declaration, ROOT, SimpleNamespace(instrument_func=missing)
                )
            with self.assertRaisesRegex(ValueError, "project-local"):
                python_preflight.verify_instrumentation(declaration, ROOT / "other", good)
        with self.assertRaisesRegex(ValueError, "not loaded"):
            python_preflight.verify_instrumentation(declaration, ROOT, good)

    def test_preflight_change_selection_is_public_scoped_and_fail_open_on_missing_diff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            event = root / "event.json"
            event.write_text(
                json.dumps(
                    {
                        "repository": {"private": False, "full_name": "o/r"},
                        "pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}},
                    }
                )
            )
            with patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_PATH": str(event),
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_REPOSITORY": "o/r",
                },
            ):
                for paths, expected in (
                    (b"docs/guide.md\0", False),
                    (b"app/parser.py\0", True),
                    (b".github/fuzz.json\0", True),
                    (b"scripts/change_scope.py\0", True),
                    (b"app2/parser.py\0", False),
                ):
                    with patch.object(fuzz.subprocess, "check_output", return_value=paths):
                        self.assertEqual(
                            fuzz.preflight_needed(root, {"preflight-paths": ["app"]}), expected
                        )
                with patch.object(
                    fuzz.subprocess,
                    "check_output",
                    side_effect=subprocess.CalledProcessError(1, "git"),
                ):
                    self.assertTrue(fuzz.preflight_needed(root, {"preflight-paths": ["app"]}))
                with patch.object(fuzz.subprocess, "check_output") as query:
                    self.assertTrue(fuzz.preflight_needed(root, {"preflight-paths": ["."]}))
                    query.assert_not_called()
                event.write_text(json.dumps({"repository": {"private": True, "full_name": "o/r"}}))
                with self.assertRaisesRegex(ValueError, "public repository"):
                    fuzz.preflight_needed(root, {})

    def test_nonpython_preflight_never_runs_campaign_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(fuzz, "execute") as execute:
                evidence = fuzz.run_preflight(
                    root,
                    root / "preflight",
                    {"language": "rust", "setup": [["expensive-build"]]},
                    setup=True,
                )
            execute.assert_not_called()
            self.assertEqual(evidence, {"python_targets": [], "commands": 0})

    def test_go_version_file_requires_a_confined_existing_regular_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".github").mkdir()
            (root / "engine").mkdir()
            (root / "engine/go.mod").write_text("module example.invalid/engine\ngo 1.26\n")
            (root / "link").symlink_to(root / "engine/go.mod")
            config = {
                "schema": 1,
                "language": "go",
                "setup": [],
                "targets": [
                    {
                        "name": "parse",
                        "engine": "go",
                        "command": ["go", "test", "-fuzz=FuzzParse"],
                        "seconds": 1,
                    }
                ],
            }
            for path in (".", "engine", "missing.mod", "link"):
                (root / fuzz.MANIFEST).write_text(json.dumps({**config, "go-version-file": path}))
                with (
                    self.subTest(path=path),
                    self.assertRaisesRegex(ValueError, "existing regular file"),
                ):
                    fuzz.manifest(root)
            (root / fuzz.MANIFEST).write_text(
                json.dumps({**config, "go-version-file": "engine/go.mod"})
            )
            self.assertEqual(fuzz.manifest(root)["go-version-file"], "engine/go.mod")

    def test_setup_only_python_proof_cannot_substitute_for_native_seed_replay(self):
        for log, accepted in (
            ("Setup only\n", False),
            ("Done 0 runs in 0 second(s)\n", False),
            ("Done 3 runs in 0 second(s)\n", True),
        ):
            with self.subTest(log=log), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)

                def execute(command, _cwd, output, *_args):
                    Path(command[command.index("--output") + 1]).write_text(
                        json.dumps({"target": "parse"})
                    )
                    output.write_text(log)
                    return 0, 0.0

                target = {"name": "parse", "command": ["python", "harness.py"]}
                with patch.object(fuzz, "bounded_preflight", side_effect=execute):
                    if accepted:
                        proof = fuzz.replay_python_target(root, root, target, 100)
                        self.assertEqual(proof["executions"], 3)
                        self.assertEqual(
                            proof, json.loads((root / "parse/instrumentation.json").read_text())
                        )
                    else:
                        with self.assertRaisesRegex(ValueError, "positive engine execution"):
                            fuzz.replay_python_target(root, root, target, 100)

    def test_every_engine_rejects_empty_declared_corpus_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "empty").mkdir()
            for engine in ("go", "atheris", "libfuzzer"):
                target = {
                    "name": engine,
                    "engine": engine,
                    "seconds": 1,
                    "command": ["never-executed"],
                    "corpus": "empty",
                }
                with self.subTest(engine=engine), patch.object(fuzz, "execute") as execute:
                    with self.assertRaisesRegex(ValueError, "at least one regular seed"):
                        fuzz.run_target(root, root, target)
                    execute.assert_not_called()

    def test_python_preflight_rejects_missing_declarations_before_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = {
                "language": "python",
                "setup": [["must-not-install"]],
                "targets": [{"engine": "atheris", "command": ["python", "harness.py"]}],
            }
            with patch.object(fuzz, "execute") as execute:
                with self.assertRaisesRegex(ValueError, "production instrumentation declarations"):
                    fuzz.run_preflight(root, root / "preflight", data, setup=True)
                execute.assert_not_called()

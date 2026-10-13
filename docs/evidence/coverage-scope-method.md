# Reproducing the maintained-source coverage bound

This recipe inventories the reviewed maintained source without executing project
scripts. Copy the Python block to `/tmp/audit-scope.py`. Install the official
[shfmt 3.14.1 release](https://github.com/mvdan/sh/releases/tag/v3.14.1) and verify
the published digest for your platform. The recorded binary is Darwin ARM64;
other platforms have different binary digests. Use Python with PyYAML installed.

```bash
SHFMT=/absolute/path/to/shfmt python /tmp/audit-scope.py "$PWD" > /tmp/coverage-scope.json
```

The script first verifies the per-file hashes of the measured Python source. It
counts all shell AST statements, including compound statements and substitutions,
in tracked scripts and workflow run blocks. It recursively inventories the SSH,
trap and heredoc forms actually present here. Double-quoted SSH command literals
are decoded before parsing their remote shell body; they are never executed.
Embedded Python AST statements, multiline awk/sed allowances, find-exec commands
the two local_checks policy commands, the dormant release.py fallback command,
and the Pump Python configuration template receive zero coverage credit. Their
script targets were already inventoried; each wrapper is conservatively counted
again as a separate shell statement.

The result is a conservative cross-language lower bound, not measured shell
coverage. Python executable statements and shell AST statements use different
language-appropriate units; compound shell nodes and extra expression allowances
deliberately increase the denominator. External packages/actions/interpreters,
test fixtures and documentation examples are outside maintained production code.
Tracked extensions, extensionless scripts and embedded command forms were also
reviewed manually. No additional maintained language, local composite action,
Dockerfile or Compose file is present in these snapshots. This recipe is tailored
to the current source, not a universal language detector. Reassess it when adding
languages or new embedded execution forms. No hardware or branch-coverage claim
is made. Re-running after a documentation-only commit preserves source hashes,
records and totals; only the recorded commit field changes.

```python
from pathlib import Path
import ast, hashlib, json, re, shlex, subprocess, sys, os, shutil
import yaml

SH = Path(os.environ.get("SHFMT") or shutil.which("shfmt") or "shfmt")
assert subprocess.check_output([str(SH), "-version"], text=True).strip() == "v3.14.1"


def nodes(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from nodes(v)
    elif isinstance(x, list):
        for v in x:
            yield from nodes(v)


def scan_shell(src, key, records, depth=0):
    if depth > 5:
        raise ValueError("Nested shell too deep")
    clean = re.sub(r"\$\{\{.*?\}\}", "EXPRESSION", src, flags=re.S)
    p = subprocess.run(
        [str(SH), "-ln", "bash", "-tojson"], input=clean, text=True, capture_output=True
    )
    if p.returncode:
        raise ValueError((key, p.stderr, clean))
    tree = json.loads(p.stdout)
    ns = list(nodes(tree))
    total = sum("Cmd" in n for n in ns)
    records.append(
        {
            "path": key,
            "language": "Shell AST statements (including compound statements)",
            "zero_coverage_statements": total,
            "sha256": hashlib.sha256(src.encode()).hexdigest(),
        }
    )
    for n in ns:
        if "Hdoc" in n:
            h = n["Hdoc"]
            body = "".join(q.get("Value", "EXPANSION") for q in h["Parts"])
            k = f"{key}:heredoc@{h['Pos']['Line']}"
            if body.lstrip().startswith(("import ", "from ")):
                records.append(
                    {
                        "path": k,
                        "language": "embedded Python AST statements",
                        "zero_coverage_statements": sum(
                            isinstance(v, ast.stmt) for v in ast.walk(ast.parse(body))
                        ),
                        "sha256": hashlib.sha256(body.encode()).hexdigest(),
                    }
                )
            else:
                scan_shell(body, k, records, depth + 1)
        if n.get("Type") != "CallExpr":
            continue
        args = n.get("Args", [])

        def literal(w):
            raw = clean.encode()[w["Pos"]["Offset"] : w["End"]["Offset"]].decode()
            val = shlex.split(raw)
            value = val[0] if len(val) == 1 else raw
            if raw.startswith(chr(34)) and raw.endswith(chr(34)):
                value = value.replace("\\$", "$").replace("\\`", "`").replace("\\\n", "")
            return value

        words = [literal(w) for w in args]
        if not words:
            continue
        key2 = f"{key}:command@{n['Pos']['Line']}"
        if words[0] == "ssh" and len(words) == 3:
            scan_shell(words[-1], key2 + ":ssh", records, depth + 1)
        elif words[0] == "trap" and len(words) > 1:
            scan_shell(words[1], key2 + ":trap", records, depth + 1)
        elif "-c" in words and any("python" in w for w in words[: words.index("-c")]):
            code = words[words.index("-c") + 1]
            records.append(
                {
                    "path": key2 + ":python-c",
                    "language": "embedded Python AST statements",
                    "zero_coverage_statements": sum(
                        isinstance(v, ast.stmt) for v in ast.walk(ast.parse(code))
                    ),
                    "sha256": hashlib.sha256(code.encode()).hexdigest(),
                }
            )
        elif words[0] in ("awk", "sed"):
            # Conservative expression-unit allowance in addition to shell command itself.
            text = " ".join(words[1:])
            unit = (
                1
                + len(re.findall(r";|\{|\}", text))
                + sum(bool(line.strip()) for line in text.splitlines())
            )
            records.append(
                {
                    "path": key2 + ":text-tool",
                    "language": "sed/awk conservative expression units",
                    "zero_coverage_statements": unit,
                    "sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
        if words[0] == "find":
            count = sum(word in ("-exec", "-execdir", "-ok", "-okdir") for word in words)
            if count:
                records.append(
                    {
                        "path": key2 + ":find-exec",
                        "language": "find embedded command allowance",
                        "zero_coverage_statements": count,
                        "sha256": hashlib.sha256(" ".join(words).encode()).hexdigest(),
                    }
                )


for root_arg in sys.argv[1:]:
    root = Path(root_arg).resolve()
    files = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
    records = []
    for f in files:
        p = root / f
        if not p.is_file():
            continue
        try:
            src = p.read_text()
        except UnicodeError:
            continue
        if f.endswith(".sh") or re.match(r"#!.*\b(?:bash|sh|dash|ash)\b", src):
            scan_shell(src, f, records)
        if f == "local_config.example.py":
            records.append(
                {
                    "path": f,
                    "language": "unmeasured Python configuration template AST statements",
                    "zero_coverage_statements": sum(
                        isinstance(v, ast.stmt) for v in ast.walk(ast.parse(src))
                    ),
                    "sha256": hashlib.sha256(src.encode()).hexdigest(),
                }
            )
        if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")):
            wf = yaml.load(src, Loader=yaml.BaseLoader)
            for job, body in wf.get("jobs", {}).items():
                for i, step in enumerate(body.get("steps", [])):
                    if "run" in step:
                        scan_shell(step["run"], f"{f}:jobs.{job}.steps[{i}].run", records)
        if p.name in ("docker-compose.yml", "compose.yml", "docker-compose.yaml", "compose.yaml"):
            compose = yaml.load(src, Loader=yaml.BaseLoader)
            for service, cfg in compose.get("services", {}).items():
                for field in ("command", "entrypoint"):
                    if field in cfg:
                        value = json.dumps(cfg[field], sort_keys=True)
                        records.append(
                            {
                                "path": f"{f}:services.{service}.{field}",
                                "language": "Compose declarative command allowance",
                                "zero_coverage_statements": 1,
                                "sha256": hashlib.sha256(value.encode()).hexdigest(),
                            }
                        )
        if p.name.startswith("Dockerfile"):
            logical = re.sub(r"\\\n\s*", " ", src)
            lines = [
                line
                for line in logical.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            records.append(
                {
                    "path": f,
                    "language": "Docker declarative instruction allowance (in addition to RUN shell)",
                    "zero_coverage_statements": len(lines),
                    "sha256": hashlib.sha256(src.encode()).hexdigest(),
                }
            )
            for i, line in enumerate(lines):
                if line.startswith("RUN "):
                    scan_shell(line[4:], f"{f}:RUN[{i}]", records)
    policy = json.loads((root / ".release-policy.json").read_text())
    for i, command in enumerate(policy.get("local_checks", [])):
        scan_shell(command, f".release-policy.json:local_checks[{i}]", records)
    # Count the dormant fallback as well as the configured wrappers. The called
    # scripts are already inventoried separately; no wrapper receives credit.
    client = ast.parse((root / "scripts/release.py").read_text())
    local_checks = next(
        node
        for node in client.body
        if isinstance(node, ast.FunctionDef) and node.name == "local_checks"
    )
    defaults = [
        node.args[1]
        for node in ast.walk(local_checks)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and len(node.args) == 2
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "local_checks"
    ]
    assert len(defaults) == 1
    for i, command in enumerate(ast.literal_eval(defaults[0])):
        scan_shell(command, f"scripts/release.py:local_checks_fallback[{i}]", records)
    cov = json.loads((root / "docs/evidence/python-coverage-2026-10-12.json").read_text())
    for entry in cov["source_files"]:
        assert hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], (
            entry["path"]
        )
    extra = sum(x["zero_coverage_statements"] for x in records)
    lower = (
        cov["statement_totals"]["covered_lines"]
        / (cov["statement_totals"]["num_statements"] + extra)
        * 100
    )
    d = {
        "measured_on": "2026-10-12",
        "parser": {
            "name": "shfmt",
            "version": "3.14.1",
            "binary_sha256": hashlib.sha256(SH.resolve().read_bytes()).hexdigest(),
            "source_url": "https://github.com/mvdan/sh/releases/tag/v3.14.1",
        },
        "method": "Count every Bash AST Stmt node, including compound statements and nested command substitutions, across all tracked shell files (including extensionless shebang scripts) and every GitHub Actions run step. Replace Actions expressions with a non-executable placeholder before parsing. Recursively count heredoc shell, SSH/trap command strings, and count embedded Python heredoc/-c AST statements separately at zero coverage. Add conservative sed/awk expression units (punctuation plus nonempty lines), find-exec commands, local_checks policy and fallback command strings, and the unmeasured Python configuration template. Count all Docker instructions plus RUN shell. Each declarative Compose command/entrypoint receives another zero-coverage unit. No non-Python execution credit is used.",
        "python_covered_statements": cov["statement_totals"]["covered_lines"],
        "python_statements": cov["statement_totals"]["num_statements"],
        "additional_zero_coverage_units": extra,
        "aggregate_conservative_lower_bound_percent": round(lower, 4),
        "records": records,
        "limitations": [
            "Coverage.py executable source statements and shell AST statements use different language-appropriate units; this is an explicitly conservative portfolio scope calculation, not a shell-coverage measurement.",
            "External interpreters, installed libraries, tools and remote reusable workflows/actions are dependencies rather than project-maintained source. Test/fixture source and documentation examples are not production source.",
            "YAML/TOML/JSON configuration is data; executable workflow run steps and Docker RUN bodies are included. Docker instructions receive an extra zero-coverage allowance.",
            "Do not apply this bound to native dependency memory safety or branch coverage.",
        ],
    }
    d["reviewed_source_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    d["manual_scope_review"] = [
        "Tracked file extensions and extensionless shebangs were reviewed. There are no additional maintained programming languages, local composite actions, Dockerfiles or Compose files in this source snapshot.",
        "All workflow run steps use shell syntax. Executable SSH/trap strings, embedded Python, awk/sed expressions and find-exec forms were reviewed. release.py executes the reviewed local_checks policy wrappers or its dormant fallback; all three command strings are included. Other shell invocations select already inventoried scripts by path.",
        "No external dependency source, test fixtures or documentation examples receive production-source coverage credit. The Pump Python configuration template is conservatively counted at zero coverage.",
    ]
    print(json.dumps(d, indent=2))
```

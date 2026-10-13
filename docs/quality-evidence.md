# Quality evidence and reproducibility

## Scope and policy

All major new functionality MUST have automated tests. Every corrected defect MUST
add a regression test that fails for the defect, unless the pull request explains
why automation is infeasible and records an equivalent check. A reviewer checks
that explanation. Resolve compiler, type-checker and linter warnings; a narrow
exception requires a reason and evidence. Never change a denominator or threshold
to conceal a failure.

Coverage percentages count executable statements in the declared source inventory,
not test code. Record the exact source SHA, Python/tool versions, numerator and
denominator, exclusions and command. Independently executed release-contract tests
can supply component evidence; the presence of tests is not proof of coverage.
An application-only percentage must never be described as whole-project coverage.

## Measurement on 2026-10-12

87.15% (5288 of 6068 statements), covering all 31 applicable Python source files, including modified local aiovelib; 937 tests passed with Python warnings treated as errors.
The [machine-readable inventory](evidence/python-coverage-2026-10-12.json)
records exact file hashes, tools, commands, missing statements and exclusions.
The new signature verifier is included: 98 of 111 statements (88.29%).
`.coveragerc` explicitly enumerates non-package source directories and enables
child-process measurement; otherwise never-imported helpers and real D-Bus
fixtures can silently disappear from the reported scope. CI and scripts/ci.sh
run the application, release and workflow suites together with an 80% gate.
Tests, local environments, build outputs and the operator configuration template
are excluded; no shipped Python module is omitted. Shell installers have behavior
checks in tests/test_update.py; their statement coverage is not measured here.
The separate cross-language bound below gives them no execution credit.

The [native archive comparison](evidence/native-archive-repeatability-2026-10-12.json)
records two byte-identical builds of the actual declared native inputs, with
input hashes and executable flags. It does not claim that wheels or cross-platform
builds have been compared.

## Conservative cross-language bound

The [complete maintained-source inventory](evidence/coverage-scope-2026-10-12.json)
combines 5288 measured covered Python statements with 6068 total Python
statements and 509 additional zero-credit units. The resulting lower bound is
**80.4014%**. Additional units include shell files, extensionless service scripts,
workflow run blocks, embedded Python/SSH/trap bodies, multiline awk/sed expressions
find-exec commands, and the two policy plus one dormant fallback local-check
wrappers. The Pump configuration template is also counted at zero
coverage where present. No shell execution or hardware coverage is claimed.

The [reproduction method](evidence/coverage-scope-method.md) records parser versions,
source hashes, manual scope checks and limitations. Python executable statements
and shell AST statements use different language-appropriate units; compound
shell nodes and extra expression allowances intentionally enlarge the denominator.
The source and tests are unchanged by this accounting. Reassess the inventory
when introducing another language or executable command form.

## Reproducible packaging

The native archive builder normalizes gzip time, tar ownership/time and file modes;
input names are sorted and only tracked declared regular files are selected.
Repeated builds from identical input bytes and executable bits should be identical.
Run tests/test_package_repeatability.py to check this property and rejection of
symlink inputs. A pinned dependency lock makes resolution repeatable, but does not
alone prove a Python wheel reproducible across different platforms/toolchains.

Before a release, compare two independently built native archives with SHA-256,
record their input commit and build environment, and verify archive contents.
Do not infer signature verification from this comparison. Physical installation,
actual D-Bus firmware compatibility and actuator commissioning require separate
acceptance evidence.

## Historical evidence

The dated evidence inventory lists actual commits and regression-test changes.
Automated title/file matching is a discovery aid, not proof that a test reproduces
a defect or that half of all fixes meet the criterion. Reviewed samples and the
complete candidate denominator must be distinguished. Historical behavior is not
retroactively guaranteed by this new policy.

The [six-month discovery history](evidence/regression-history-2026-10-12.json)
retains the original commits and heuristic candidates. It is superseded for
acceptance by the [defect-level review](evidence/defect-level-review-2026-10-12.json).
That review verifies regression assertions for 46 fixes out of at most 82
identified defect units, a conservative lower bound of 56.10%. Ambiguous
feature boundaries and current corrections receive zero credit but remain in
the denominator. Later tests are dated explicitly; passing counts alone do not
establish a regression test. Independent review covered selected rows and
counting boundaries, not a second complete audit.

## Warning policy

Python test warnings are errors (`filterwarnings = error`), including dependency
deprecations and resource warnings; no blanket runtime-warning suppression is
configured. Ruff enables error, undefined-name, warning, import, upgrade, blind
exception, async and Ruff-specific diagnostics for application code. Generated
release components retain the reviewed toolkit's configuration and upstream
checks. A narrow exception must identify an unavoidable protocol or compatibility
requirement; a new warning is not fixed by dropping it from the report.

The modified aiovelib is included in functional lint and coverage. Its preserved
upstream tab layout/legacy naming and shared class registries have explicit style
exceptions; D-Bus decorators require string protocol signatures (`v`, `s`,
`a{sv}`), so those annotations are exempt from Python forward-reference checks.
The availability probe import selects a compatible D-Bus backend. Formatting alone
is excluded for this copied library; whole-file functional lint is not excluded.

The [additional defect-level history review](evidence/defect-level-review-2026-10-12.json)
separates runtime, installer and CI causes and records conservative upper-bound
units for ambiguous compound changes. The ratio is not inferred from commit counts.

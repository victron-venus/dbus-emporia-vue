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

82.43% (4416 of 5357 statements), covering all 27 applicable Python source files, including modified local aiovelib; 746 tests passed across the full suite and the added real-library check.
The [machine-readable inventory](evidence/python-coverage-2026-10-12.json)
records exact file hashes, tools, commands, missing statements and exclusions.
`.coveragerc` explicitly enumerates non-package source directories and enables
child-process measurement; otherwise never-imported helpers and real D-Bus
fixtures can silently disappear from the reported scope. CI and scripts/ci.sh
run the application, release and workflow suites together with an 80% gate.
Tests, local environments, build outputs and the operator configuration template
are excluded; no shipped Python module is omitted. Shell installers have behavior
checks in tests/test_update.py; their statement coverage is not measured here.

The [native archive comparison](evidence/native-archive-repeatability-2026-10-12.json)
records two byte-identical builds of the actual declared native inputs, with
input hashes and executable flags. It does not claim that wheels or cross-platform
builds have been compared.

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

The [six-month history and reviewed pairs](evidence/regression-history-2026-10-12.json)
retain the complete commit list and distinguish reviewed regression additions from
heuristic candidates. A representative/all-fix denominator review remains open;
the 50% historical criterion is not asserted from title matching.

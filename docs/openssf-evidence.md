# OpenSSF Best Practices evidence: dbus-emporia-vue

This index supports review against the [OpenSSF Passing criteria](https://www.bestpractices.dev/en/criteria/0). It is not an awarded badge, a security guarantee or a completed self-attestation. Initial source inventory: `4f931077d75154144eaf0eb90330398df73f213e`. Re-check the final merged commit and its CI before submitting an assessment.

## Project and contribution process

Publishes Emporia/Home Assistant power channels as Victron D-Bus AC loads.

- [Public repository and history](https://github.com/victron-venus/dbus-emporia-vue) provide source, commits and interim changes.
- [README](../README.md) describes installation, configuration and usage.
- [Contribution process](../CONTRIBUTING.md) documents reports, review, style and the policy to add automated tests for major changes.
- [Issues](https://github.com/victron-venus/dbus-emporia-vue/issues) and [pull requests](https://github.com/victron-venus/dbus-emporia-vue/pulls) provide searchable public discussion and change review.
- [Security policy](../SECURITY.md) documents confidential reporting, response goals, trust boundaries and delivery practices.

The root [LICENSE](../LICENSE) records the project license. Third-party components retain their own notices.

## Implementation and interfaces

[Architecture and trust boundaries](architecture.md) explains the component flow
and operator, network, D-Bus and release boundaries.

- [main.py](../main.py)
- [emporia.py](../emporia.py)
- [sources.py](../sources.py)
- [config.json.example](../config.json.example)

Interface documentation must explain accepted configuration and inputs, outputs, failure handling and relevant permission boundaries. Verify it against the implementation when changing behavior; source links alone do not establish that every interface is documented.

## Build, test and analysis evidence

The local validation entry point is [scripts/ci.sh](../scripts/ci.sh). Its actual test and compiler/linter commands, not the presence of a workflow name, define the available coverage.

[GitHub Actions](https://github.com/victron-venus/dbus-emporia-vue/actions) provides run logs and results. The checked-in workflow definitions are:

- [auto-approve.yml](../.github/workflows/auto-approve.yml)
- [auto-merge.yml](../.github/workflows/auto-merge.yml)
- [codeql.yml](../.github/workflows/codeql.yml)
- [coderabbit-autofix.yml](../.github/workflows/coderabbit-autofix.yml)
- [coderabbit-review.yml](../.github/workflows/coderabbit-review.yml)
- [dependency-review.yml](../.github/workflows/dependency-review.yml)
- [python-ci.yml](../.github/workflows/python-ci.yml)
- [quality-gate.yml](../.github/workflows/quality-gate.yml)
- [release-build.yml](../.github/workflows/release-build.yml)
- [release-pipeline.yml](../.github/workflows/release-pipeline.yml)
- [release-security.yml](../.github/workflows/release-security.yml)
- [scorecards.yml](../.github/workflows/scorecards.yml)

Do not equate a green metadata or release job with successful application tests. Record actual test results, coverage limitations and security-analysis results for the submitted revision. Test execution does not establish physical-device behavior.

## Assessment evidence reviewed on 2026-10-12

Private vulnerability reporting is enabled. The full GitHub issues inventory
contained no non-PR reports, and the advisory inventory was empty. The owner
confirmed no reports, bugs, suggestions or vulnerabilities outside GitHub during
the preceding 12 months, and confirmed secure-design and common-vulnerability
knowledge for this project. No response-time percentage is inferred from an
empty report set.

Release notes were checked for actual change descriptions and upgrade/security
guidance. Open Dependabot and secret-alert inventories were empty. Four remaining
Scorecard findings concern maintenance, branch protection, fuzzing and the badge;
they are process findings, not established exploitable runtime defects. These
inventories are time-specific and must be reviewed again before submission.

The proposed [.bestpractices.json](../.bestpractices.json) contains this project's
Passing answers and public evidence links. Import only after the reviewed changes
merge and required CI succeeds. The live assessment is the source of truth for
any awarded level; a README badge does not itself establish compliance.

## Release-note source

[CHANGELOG.md](../CHANGELOG.md) contains the current development line's change summary, upgrade impact and security notes. The release policy opts into commit-pinned notes; publication rejects missing or incomplete current-version sections. The 2026-10-12 historical review checked descriptions and retained original build provenance; new releases still require a source-specific review.

The release implementation is generated from the immutable toolkit revision in
[.release-policy.json](../.release-policy.json). It rejects missing source-specific
notes, ambiguous or empty guidance, mutable action pins, mismatched source/version
receipts and unsafe staging inputs. Consumer regression tests exercise those
contracts. [Recipient signature verification](release-signatures.md) authenticates
the full original artifact inventory and reviewed source archive. Signing runs
only after compilation and quality checks, in a separate job with scoped OIDC
permission. A real signed release still needs to be published and independently
verified; historical releases remain unsigned.

The CodeQL configuration also analyzes GitHub Actions in its own analysis category; existing application-language analyses remain enabled.

## Silver work and remaining owner facts — 2026-10-12

[Governance](../GOVERNANCE.md), [conduct](../CODE_OF_CONDUCT.md),
[roadmap](../ROADMAP.md), [quality evidence](quality-evidence.md), and the
[security assurance argument](security-assurance.md) describe the implemented
process and scoped evidence. The owner confirmed that no continuity mechanism
is currently in place: access_continuity remains Unmet. The owner also confirmed
no reports outside GitHub in the preceding 12 months; this does not replace the
separate GitHub history review recorded above or create retrospective response records.
Published signing verification remains open. The conservative cross-language
coverage bound exceeds 80% (see [quality evidence](quality-evidence.md)). The
[defect-level history review](evidence/defect-level-review-2026-10-12.json) records
a conservative regression-test lower bound above 50%.
The [live OpenSSF assessment](https://www.bestpractices.dev/projects/15437) is registered.
The README badge displays its current status; no Silver award is claimed.

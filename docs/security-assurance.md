# Security assurance argument

## Goal, scope and assumptions

The goal is to preserve integrity and availability of the documented dbus-emporia-vue
service under malformed telemetry, unavailable dependencies and routine updates.
The OS, configured D-Bus policy, administrator-controlled files and authenticated
Home Assistant/provider endpoints are trusted within their stated boundaries.
A compromised host or unrestricted administrator is outside this argument.
Use independent physical protections for equipment; software tests are not a
safety certification.

## Claims and evidence

- Claim: absent/stale source values are not silently reported as measured zero.
  Argument: source parsing and freshness tracking distinguish usable observations
  from failed or stale requests. Evidence: sources.py, emporia.py, main.py;
  tests/test_sources.py, test_emporia.py and test_main.py.
- Claim: one failed channel or a transient disconnect does not corrupt independent
  channels. Argument: connection/lifecycle handling isolates failures and retries
  with explicit state. Evidence: main.py and tests/test_main.py; actual D-Bus
  integration tests require the documented isolated bus fixture.
- Claim: credentials and downloaded input are not trusted merely because present.
  Argument: source-specific parsing, transport configuration and failure handling
  provide explicit boundaries. Evidence: emporia.py, parse_ha.py and tests for
  rejected inputs. Provider behavior and production host configuration remain
  external assumptions, not guaranteed by mocks.

- Claim: source changes and updates remain reviewable. Argument: public history,
  contributor policy, required CI and release input manifests identify the code
  under review. Evidence: CONTRIBUTING.md, RELEASING.md, release contract tests.
  The release policy enables a separate post-build Sigstore signing job. The
  verifier authenticates the expected repository, branch and reviewed commit
  before reading the inventory, then checks all original assets and source bytes.
  Evidence: docs/release-signatures.md, scripts/release_signing.py and its negative
  contract tests. Actual published signed-release verification remains required.

## Residual obligations

Review the exact deployed TLS/credential configuration and permission model.
Re-run relevant negative tests after changing a boundary. Keep dependencies
monitored and replace compromised credentials; never claim that deleting a
credential from Git revokes it. Use SECURITY.md for coordinated disclosure.

The coverage and regression inventories support this argument only within their
declared scope. Remaining OpenSSF obligations include verified continuity,
published signed-release verification and all-language coverage evidence.
The defect-level regression review now records a conservative lower bound. The 2026-10-12 review found no GitHub issue/advisory reports,
and the owner confirmed no outside-GitHub reports during the prior 12 months. Python coverage is
measured in docs/quality-evidence.md; hardware and shell coverage are not implied. No Passing or Silver award is asserted here.

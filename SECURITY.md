# Security policy

## Reporting a vulnerability

Send vulnerability details privately using [GitHub's Report a vulnerability form](https://github.com/victron-venus/dbus-emporia-vue/security/advisories/new). Include the affected commit or release, reproduction steps, impact and a suggested mitigation if known. Remove live secrets and personal information. Do not open a public issue with exploit details. If private reporting is temporarily unavailable, open a public issue requesting a confidential contact without disclosing the vulnerability.

Maintainers aim to acknowledge reports within 14 days, investigate promptly and coordinate disclosure with the reporter. Critical confirmed vulnerabilities receive priority. Confirmed exploitable medium-or-higher issues should be corrected within 60 days of confirmation. Coordinate normal public disclosure with a fix or effective mitigation. If active exploitation or another urgent risk requires earlier warning, promptly publish the affected scope and available protective steps while remediation continues. Release notes should identify any assigned CVE or equivalent advisory identifier for fixes. These are maintenance policies, not claims about historical response times.

## Supported code

Security fixes are developed on the current default branch and released through the repository's normal delivery process. Older releases are not guaranteed backports; reproduce against the current code where practical and include the original affected version in the report. A prerelease or development build is not a promise of production or hardware acceptance.

## Trust boundaries

Home Assistant and Emporia access credentials authorize access to household energy data. Keep configuration private and restrict D-Bus access. Untrusted or stale telemetry must not be treated as a measured zero.

## Secure development and delivery

Validate external values at trust boundaries, reject unsupported or malformed commands, avoid shell interpolation, preserve certificate verification, and use maintained cryptographic libraries rather than custom cryptography. Apply least privilege to service accounts, repository tokens and filesystem permissions. Follow [CONTRIBUTING.md](CONTRIBUTING.md) for validation and review.

Obtain source and published artifacts through the repository's HTTPS URLs. Verify published checksums or provenance when provided, over an authenticated channel. Keep local configuration, credentials and private keys out of source control and logs. Report suspected exposure through the private channel so credentials can be revoked and replaced; deleting a file alone does not revoke it.

[OpenSSF evidence and remaining verification](docs/openssf-evidence.md) is maintained separately from this policy.

## Reporter credit and response records

Offer public credit to reporters of confirmed vulnerabilities. Publish it only
after the reporter approves the exact attribution; use anonymous attribution if
they do not respond or request anonymity. Ask their preference before publication
and retain the decision with the private report. Track acknowledgement,
triage, mitigation, release and disclosure dates; escalate delayed critical fixes
to repository administrators. This is the required process going forward, not an
assertion about reports received before it.

See the [security assurance argument](docs/security-assurance.md) for scoped
claims, implementation references and remaining obligations.

## Release authentication and cryptography

The release policy enables Sigstore keyless signing in a dedicated job after
quality checks and compilation. Follow [recipient verification](docs/release-signatures.md)
using a separately trusted reviewed source commit before extracting artifacts.
The signed inventory covers the original build outputs, receipts and source archive.
Historical releases without the signature pair remain unsigned.

The [Cosign signature format](https://github.com/sigstore/cosign/blob/main/specs/SIGNATURE_SPEC.md)
uses ECDSA P-256 and SHA-256. Its ephemeral keys use the maintained implementation's
cryptographic randomness; no long-lived signing key is stored in this project.
Application TLS also delegates algorithms, certificate verification and random
values to maintained Python/OpenSSL libraries. Do not disable TLS validation or
replace secure defaults on the deployed host. Emporia provider authentication,
where present, is delegated to pycognito's SRP/HMAC-SHA256 implementation.

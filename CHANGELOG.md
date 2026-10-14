# Changelog

## [1.0.11] - 2026-10-14

### Changed

- Validate each public release candidate with bounded, network-isolated fuzz campaigns against its exact source revision.
- Require positive engine execution counts, instrumented production code and validated seed corpora; retain source-bound reports and diagnostic evidence.
- Run deterministic seed and configuration checks in ordinary CI without starting mutation campaigns on betas.

### Upgrade

Use the existing installation procedure, preserve local configuration and keep the previous accepted package for rollback. This maintenance release updates release validation and does not change the application configuration format. Deployment and applicable device or integration acceptance remain separate from publication.

### Security

The release gate rejects absent or invalid fuzz evidence and unsafe corpus filesystem properties. No application vulnerability or new target-device acceptance is claimed by these tooling changes.

## [1.0.10] - Development line

### Maintenance

- Require bounded fuzzing on public release candidates, with source-bound reports and retained diagnostics; beta and ordinary CI do not run mutation campaigns.
- Reject malformed or excessively nested Home Assistant JSON, numeric overflow and non-finite converted power.
- Resolve release channel validation imports in both package and script execution modes.

### Upgrade

Use the documented update procedure and retain local configuration. Automated tests do not establish target-device acceptance.

### Security

Release qualification now requires isolated fuzzing against the candidate source. Report findings through SECURITY.md.

## [1.0.9] - Development line

### Release overview

Publishes Emporia/Home Assistant power channels as Victron D-Bus AC loads. The existing README documents configuration and external interfaces for this development line.

### Maintenance

- Support explicit `DESTDIR` package staging and uninstall without live service actions, preserving operator-owned configuration.
- Treat Python test warnings as failures and apply broad Python lint checks with documented, narrow compatibility exceptions.

- Enable isolated keyless release signing and authenticated verification of the complete artifact inventory and reviewed source archive.

- Restore the upstream MIT copyright notice and record provenance for the
  modified bundled aiovelib library.

- Measure application, release helpers and modified local library code with one
  explicit Python source inventory and an 80% statement-coverage gate.
- Exercise deterministic native packaging, untracked-file exclusion, required
  inputs, version validation and refusal to reuse stale output directories.
- Document governance, conduct, roadmap, security assurance and dated quality
  evidence, including the outstanding continuity requirement.

- Synchronize Ruff 0.17.0 and boto3/botocore 1.43.112 with the hash-locked dependency files used by CI.
- Refresh shared CI workflow pins while preserving the default GitHub-hosted runner selection.

- Skip malformed Home Assistant channel entries and isolate D-Bus connection
  failures to the affected channel. Keep failed cleanup owned for shutdown and
  preserve task cancellation while attempting later valid channels.
- Separate cloud usage/status parsing and device-transition logging from request
  handling while preserving nested-device traversal, invalid-data rejection,
  authentication recovery and retry timing.
- Publish reviewed release notes from the exact source commit used to build each candidate, preserving build provenance.
- Document contribution checks, confidential security reporting and the project-specific trust boundaries.

### Upgrade

These maintenance changes do not introduce a configuration or data migration. Retain local configuration and credentials when using the documented update procedure. Validate the candidate on an isolated system before production use; automated checks do not establish hardware acceptance.

### Security

- Restrict configuration-generator endpoints to HTTP(S)/WS(S), refuse authenticated redirects, and atomically write token-bearing configuration with owner-only permissions. Existing symlink destinations are rejected.

Private vulnerability reporting and response policy are documented in SECURITY.md. This maintenance update strengthens release evidence and review instructions; it does not replace deployment authentication, network isolation or independent equipment safeguards. No new project CVE is announced by these changes.

## 1.0.7

- Reuse a worker-owned HTTPS connection pool for Emporia readings, while preserving token refresh, TLS verification, and bounded error retries.
- Prioritize power between individual daily/monthly energy requests. Add `emporia.energy_timeout_seconds` (default 3 seconds for connect and read separately).
- Detect lost D-Bus connections and exit for supervisor recovery. Reject occupied service names instead of silently joining the ownership queue.
- Revalidate quiet Home Assistant channels using targeted REST reads instead of downloading every HA entity every five seconds. Keep one request in flight and accept valid delayed responses without overwriting newer events.
- Apply source timestamp freshness to ordinary HA channels as well as the selected submeter. `ha_stale_after_seconds` defaults to 30; set it to `null` for the previous ordinary-channel behavior. The selected submeter retains its own freshness requirement.
- Preserve startup snapshots across bursts of more than 50 HA events. Add transport-level regression tests with a private D-Bus daemon and a local HTTP keep-alive server.
- HA mode now requires `requests` for targeted revalidation; dependency checks run before stopping an installed service. Existing channel names, instances, credentials, and energy paths are preserved.

## 1.0.4

- Handle SIGTERM and SIGINT by cancelling and joining the main workers instead of raising SystemExit in an unobserved task.
- Bound WebSocket close, release every channel's private D-Bus connection, and remove signal handlers even when cleanup fails.
- Test real process signals with stubbed network and D-Bus I/O, including cleanup failure paths.

## 1.0.3

- Prevent an older initial HA snapshot from overwriting an interleaved state-trigger update.
- Prefer explicit HA state timestamps when both are available; otherwise retain the received event, including unavailable power and measured zero.
- Keep timestamp comparison local to initialization and preserve the existing connection deadline, message cap, and reconnect policy.
- Test older/newer snapshot ordering, absent timestamps, initial-query failure, and installation from arbitrarily named worktrees.

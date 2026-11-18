# Documentation

A Venus OS D-Bus service that reads an Emporia Vue energy monitor and publishes
its channels to the GX device, documented from the three supported setups onward.

## Choose a setup

- [Read from Home Assistant](examples/1-from-home-assistant/README.md) — for an Emporia integration that already works in Home Assistant.
- [Read directly from the Emporia Vue API](examples/2-from-emporia-api/README.md) — the GX device reads the Vue account itself.
- [Read Emporia API and send readings to Home Assistant](examples/3-emporia-api-to-home-assistant/README.md) — both at once, through the GX device.
- [Scenario 3 reference: Emporia API to Home Assistant through GX MQTT](home-assistant-mqtt.md) — the reference for the third setup.
- [Configuration reference](configuration.md) — the settings each setup needs.

## Operate it

- [Install and operate the service](installation.md) — installation once a setup is chosen.
- [Staged native installation](staged-installation.md) — capturing the declared native payload without a Venus device.
- [Architecture and trust boundaries](architecture.md) — what each module owns and where the trust boundary sits.
- [Tariff export](tariff-export.md) — the companion `export_tariff.py` script and the existing tariff file it reads.

## Evidence

- [Quality evidence and reproducibility](quality-evidence.md) — the testing rules new functionality and fixes must meet.
- [Reproducing the maintained-source coverage bound](evidence/coverage-scope-method.md) — inventorying reviewed source without executing it.
- [Security assurance argument](security-assurance.md) — the integrity and availability goal for the documented service.
- [Static-analysis review notes](STATIC_ANALYSIS.md) — how findings in the executable source are triaged.
- [OpenSSF Best Practices evidence: dbus-emporia-vue](openssf-evidence.md) — the index behind the Passing assessment.

## Releases

- [Release operations](release-packaging.md) — what `release.sh` delegates and which events validate what.
- [Signed stable release and target acceptance](release-acceptance.md) — the stable baseline and its acceptance.
- [Verify a signed release](release-signatures.md) — checking a signed artefact.
- [Release version inputs](release-versioning.md) — the `versioning` fields that identify a release.
- [CI and release operations](release-workflow.md) — `.release-policy.json` and the required status.
- [CI orchestration](CI-ORCHESTRATION.md) — how the quality gate and release pipeline divide the events.
- [Version plans and manifest synchronization](VERSIONING.md) — the versioning opt-in.
- [Release-candidate fuzz testing](fuzzing.md) — the illustrated RC fuzzing process.
- [Fuzzing release candidates](rc-fuzzing.md) — the reusable bounded fuzz workflow.
- [Early final-build runner check](runner-preflight.md) — why the check runs before the final build.

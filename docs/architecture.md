# Architecture and trust boundaries

`main.py` loads channels and coordinates their lifecycle. `sources.py` validates
and normalizes source values; `emporia.py` handles provider authentication,
requests and retry state. Home Assistant WebSocket snapshots/events and Emporia
cloud readings feed independent channel state. The locally modified
`aiovelib/aiovelib` publishes each configured AC-load service on a private D-Bus
connection. `parse_ha.py`, `ha_config_gen.py`, and tariff tools support operator
configuration and export; they do not authorize physical control.

The administrator controls provider tokens and channel mappings. Network values
are external input: malformed values must not become valid zero readings, stale
channels must become unavailable, and one failed channel connection must not
prevent independent channels from starting. Initial snapshots must not overwrite
newer events. The Venus OS host, system bus and its access policy are trusted;
host compromise is outside the application's protection boundary.

The configuration generator accepts only validated HTTP(S)/WS(S) endpoints,
rejects redirects for bearer-authenticated requests, and writes private
configuration atomically. `update.sh`, `setup` and service scripts maintain the
persistent installation and supervised startup. Installer tests check partial
updates, failure before service replacement and preservation of supervisors.

## Delivery boundary

The Python application and native archive use the dependency locks and declared
package inventory. CI combines application, release and workflow tests; the
coverage inventory explicitly includes never-imported helpers. Release checks,
builds, signing and publication have separate responsibilities. Signing occurs
only after successful checks/builds, and publication verifies the source identity
and original artifact inventory. See [signature verification](release-signatures.md)
and [quality evidence](quality-evidence.md).

The [security assurance argument](security-assurance.md) links these boundaries
to implementation and negative tests. Mocks and desktop fixtures do not establish
physical equipment behavior or every deployed Venus OS firmware configuration.

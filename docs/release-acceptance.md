# Signed stable release and target acceptance

[Stable v1.0.9](https://github.com/victron-venus/dbus-emporia-vue/releases/tag/v1.0.9)
was published by [the successful promotion run](https://github.com/victron-venus/dbus-emporia-vue/actions/runs/38340604967)
from accepted `v1.0.9-rc.2`, source `e178c8fe22e1110b96243b4c644ebb298418c680`.

## Recipient verification

All eight published assets were downloaded and compared with the accepted RC2;
every asset was byte-identical. Cosign 3.1.3 and the reviewed source verifier
accepted the expected repository, workflow, ref, source and complete inventory
of four signed payloads. Verification with an incorrect expected source failed.
[The signature guide](release-signatures.md) documents how recipients repeat
these checks. Historical unsigned releases are not retroactively authenticated.

## Target acceptance and limits

The [exact RC2 acceptance record](https://github.com/victron-venus/dbus-emporia-vue/pull/98#issuecomment-6137363534)
describes the installed-file comparison and runtime observation on a Cerbo GX,
Venus OS v3.75, ARMv7, Python 3.12.13. Installed application files matched the
accepted release mapping; process identity and connected D-Bus services remained
stable while telemetry advanced. The unchanged stable assets preserve that
acceptance; they do not establish behavior on every firmware or configuration.

The final observation window included a recovered upstream power-read timeout.
All 19 checked services reported connected at the final observation; the process
identity was unchanged.
The separately verified ARMv7 vendor archive is not a signed RC release asset.
Cold boot was not tested.

These checks do not establish uninterrupted upstream availability, exercise
all failure modes, or certify physical equipment safety. Reapply the
[release policy](../RELEASING.md) to future candidates, changed dependencies,
installation procedures and supported targets. Keep recovery material until
the deployment is accepted under the operator's maintenance policy.

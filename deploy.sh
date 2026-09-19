#!/bin/bash
#
# Deploy dbus-emporia-vue to Venus OS
#
# Packs the declared runtime and optional config.json, streams them to the
# device and runs the repo's own self-update script (update.sh) there, so all
# install logic lives in exactly one place - the same path the auto-deploy
# webhook uses for release tarballs.
#
# Prerequisites:
#   - SSH config with host 'Cerbo' pointing to Venus OS device
#   - SSH key authentication configured
#
# Usage: ./deploy.sh [SSH_HOST]
#

set -euo pipefail

SSH_HOST="${1:-Cerbo}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="/data/.dbus-emporia-vue-deploy"
SEPARATOR="=============================================="

echo "$SEPARATOR"
echo "  Deploying dbus-emporia-vue to Venus OS"
echo "$SEPARATOR"
echo "SSH Host: $SSH_HOST"
echo ""

# Check local syntax before shipping (fail fast on the dev machine)
echo ">>> Checking Python syntax..."
python3 -m py_compile "$SCRIPT_DIR/main.py" "$SCRIPT_DIR/emporia.py" "$SCRIPT_DIR/sources.py" "$SCRIPT_DIR/parse_ha.py"
echo "    Syntax OK"

# Optional workstation configuration generation; an existing device config is
# preserved when neither a local config nor HA credentials were supplied.
if [[ ! -f "$SCRIPT_DIR/config.json" && -n "${HA_URL:-}" && -n "${HA_TOKEN:-}" ]]; then
    (cd "$SCRIPT_DIR" && python3 ha_config_gen.py)
fi

# Package the runtime and run update.sh on the device. `set -e` on the remote
# aborts the whole chain if update.sh fails, so the deploy is atomic-ish.
#
PAYLOAD_FILES="$(mktemp)"
trap 'rm -f "$PAYLOAD_FILES"' EXIT
python3 - "$SCRIPT_DIR" "$PAYLOAD_FILES" <<'PYTHON'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
from package_release import package_inputs

_, selected = package_inputs(root, json.loads((root / ".release-package.json").read_text()))
if (root / "config.json").is_file():
    selected.append("config.json")
for name in selected:
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"Refusing non-regular runtime input: {name}")
Path(sys.argv[2]).write_bytes(b"".join(("./" + name).encode() + b"\0" for name in selected))
PYTHON
echo ">>> Streaming runtime to $SSH_HOST and running update.sh..."
# macOS bsdtar otherwise writes AppleDouble (._*) and pax LIBARCHIVE.xattr.*
# headers (com.apple.provenance) that Venus/busybox tar warns about on extract.
COPYFILE_DISABLE=1 tar \
    --no-xattrs \
    -czf - -C "$SCRIPT_DIR" --null -T "$PAYLOAD_FILES" \
    | ssh "$SSH_HOST" "set -e; rm -rf $DEPLOY_DIR; mkdir -p $DEPLOY_DIR; \
        tar -xz -C $DEPLOY_DIR --strip-components=1; \
        PUSH_LOCAL_CONFIG=1 sh $DEPLOY_DIR/update.sh; \
        rm -f /tmp/dbus-emporia-vue.heartbeat; \
        waited=0; while [ \$waited -lt 60 ] && ! [ -f /tmp/dbus-emporia-vue.heartbeat ]; do sleep 1; waited=\$((waited + 1)); done; \
        test -f /tmp/dbus-emporia-vue.heartbeat; \
        rm -rf $DEPLOY_DIR"

# Wait for supervise to bring the service back up (svc -u is async)
echo ">>> Service status:"
STATUS=""
for _attempt in $(seq 1 15); do
    sleep 1
    if STATUS="$(ssh "$SSH_HOST" "svstat /service/dbus-emporia-vue 2>&1")"; then
        if [[ "$STATUS" == *": up (pid "* ]]; then
            printf '%s\n' "$STATUS"
            break
        fi
    fi
done
if [[ "$STATUS" != *": up (pid "* ]]; then
    echo "Service did not start: $STATUS" >&2
    exit 1
fi

# The service dir must be a symlink into the install tree. A real directory
# here means stale code got resurrected (legacy /opt copy or boot-order race)
# and will keep running no matter what update.sh installs elsewhere.
if ! ssh "$SSH_HOST" "test -L /service/dbus-emporia-vue"; then
    echo "ERROR: /service/dbus-emporia-vue is not a symlink - split-brain install" >&2
    exit 1
fi

echo ""
echo "$SEPARATOR"
echo "  Deployment Complete!"
echo "$SEPARATOR"

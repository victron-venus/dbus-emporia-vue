#!/bin/sh
#
# dbus-emporia-vue self-update script.
#
# Ships inside the release tarball and runs ON the Venus OS device to install
# the release into INSTALL_DIR (default /data/dbus-emporia-vue). It is invoked
# by SetupHelper or manually:
#
#     sh update.sh [INSTALL_DIR]
#
# This script owns all layout knowledge (runtime files, daemontools services,
# /service symlinks, device-local file preservation, restart order) so that
# callers never need to hardcode where files go. Adding a new
# module or a new daemontools service requires a change here only.
#
set -eu

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${1:-/data/dbus-emporia-vue}"

# Unit commands and boot hooks use this canonical persistent location.
if [ "$INSTALL_DIR" != "/data/dbus-emporia-vue" ]; then
    echo "Unsupported install directory: use /data/dbus-emporia-vue" >&2
    exit 2
fi

# Device-local configuration is preserved; credential and token files are never copied.
LOCAL_ONLY="config.json"

# Runtime items shipped at the repo root and installed at INSTALL_DIR root.
RUNTIME_ITEMS="update.sh main.py emporia.py sources.py parse_ha.py aiovelib version setup register-package.sh gitHubInfo config.json.example requirements.txt requirements.lock"

# Reserved for obsolete runtime files from future migrations.
STALE_TOP_LEVEL=""

sep() { echo "=== dbus-emporia-vue update: $*"; }

# Fail before stopping the existing service if the firmware lacks dependencies.
# Provision packages separately; never modify the system Python during an update.
export PYTHONPATH="$INSTALL_DIR/vendor${PYTHONPATH:+:$PYTHONPATH}"
CHECK_CONFIG="$INSTALL_DIR/config.json"
if [ "${PUSH_LOCAL_CONFIG:-0}" = "1" ] && [ -f "$SRC_DIR/config.json" ]; then
    CHECK_CONFIG="$SRC_DIR/config.json"
fi
PYTHONDONTWRITEBYTECODE=1 python3 - "$CHECK_CONFIG" <<'PYTHON'
import json
import sys
from pathlib import Path

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Venus OS system Python 3.12.x is required")
import dbus_fast, websockets

config_path = Path(sys.argv[1])
if config_path.is_file():
    config = json.loads(config_path.read_text())
    source = config.get("source", "home_assistant")
    if source not in {"emporia", "home_assistant"}:
        raise SystemExit("source must be emporia or home_assistant")
    if source == "emporia":
        import pyemvue, botocore
PYTHON

command -v svc >/dev/null
command -v svstat >/dev/null

# Stage the release before stopping anything. SetupHelper runs this script from
# the installed package tree, which must not be deleted while it is our source.
# /tmp is volatile on Venus OS and avoids writing an extra release to flash.
STAGING_DIR=$(mktemp -d /tmp/dbus-emporia-vue-update.XXXXXX)
trap 'rm -rf "$STAGING_DIR"' EXIT
trap 'exit 1' HUP INT TERM
mkdir -p "$STAGING_DIR/source" "$STAGING_DIR/backup"
for item in $RUNTIME_ITEMS $LOCAL_ONLY service services; do
    [ ! -e "$SRC_DIR/$item" ] || cp -a "$SRC_DIR/$item" "$STAGING_DIR/source/$item"
done
# Supervise state belongs to the old process, not the release payload.
find "$STAGING_DIR/source" -type d -name supervise -prune -exec rm -rf {} \;
SRC_DIR="$STAGING_DIR/source"
cd "$STAGING_DIR"

# Validate the owned service layout before stopping a healthy worker. Ordinary
# updates preserve the service/log directories and their live supervisors.
SERVICE_TARGET="$INSTALL_DIR/service/dbus-emporia-vue"
SERVICE_LINK="/service/dbus-emporia-vue"
UNIT_SOURCE="$SRC_DIR/service/dbus-emporia-vue"
[ -d "$UNIT_SOURCE" ] || UNIT_SOURCE="$SRC_DIR/services/dbus-emporia-vue"
for run_file in run log/run; do
    if [ ! -f "$UNIT_SOURCE/$run_file" ]; then
        echo "Missing service definition: $UNIT_SOURCE/$run_file" >&2
        exit 1
    fi
done
if [ -L "$SERVICE_LINK" ]; then
    if [ "$(readlink "$SERVICE_LINK")" != "$SERVICE_TARGET" ]; then
        echo "Refusing to replace an unexpected service symlink: $SERVICE_LINK" >&2
        exit 1
    fi
elif [ -e "$SERVICE_LINK" ]; then
    echo "Legacy service directory requires migration before updating: $SERVICE_LINK" >&2
    exit 1
fi
for directory in "$INSTALL_DIR/service" "$SERVICE_TARGET" "$SERVICE_TARGET/log"; do
    if [ -L "$directory" ] || { [ -e "$directory" ] && [ ! -d "$directory" ]; }; then
        echo "Unexpected service directory layout: $directory" >&2
        exit 1
    fi
done
LEGACY_OPT="/opt/victronenergy/dbus-emporia-vue"
if [ -e "$LEGACY_OPT" ] || [ -L "$LEGACY_OPT" ]; then
    echo "Legacy firmware installation requires migration before updating: $LEGACY_OPT" >&2
    exit 1
fi

# Stop only the application; its existing logger and supervisors stay alive.
# Verify termination before replacing Python files. A stuck worker gets one
# supervisor-scoped kill after twenty seconds; unrelated processes are untouched.
stop_worker() {
    [ -e "$SERVICE_LINK" ] || return 0
    svc -d "$SERVICE_LINK" || return 1
    waited=0
    while [ "$waited" -lt 25 ]; do
        status=$(svstat "$SERVICE_LINK" 2>/dev/null || true)
        case "$status" in *": down "*) return 0 ;; esac
        if [ "$waited" -eq 20 ]; then
            svc -k "$SERVICE_LINK" || return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    echo "Service did not stop; runtime files were not changed: $SERVICE_LINK" >&2
    return 1
}
stop_worker

mkdir -p "$INSTALL_DIR"
sep "installing from $SRC_DIR into $INSTALL_DIR"

# 2. Back up device-local files so the wholesale copy below can restore them.
TMP_BACKUP="$STAGING_DIR/backup"
mkdir -p "$TMP_BACKUP"
for f in $LOCAL_ONLY; do
    [ -f "$INSTALL_DIR/$f" ] && cp -p "$INSTALL_DIR/$f" "$TMP_BACKUP/"
done

# 3. Install runtime items (replace wholesale to also drop stale files).
for item in $RUNTIME_ITEMS; do
    [ -n "$item" ] || continue
    if [ -e "$SRC_DIR/$item" ]; then
        rm -rf "${INSTALL_DIR:?}/$item"
        cp -a "$SRC_DIR/$item" "$INSTALL_DIR/$item"
    fi
done

# Replace only the two owned run scripts, using rename in each destination
# directory. Open files, log pipes, directory ownership and supervise state
# survive the update. A running multilog uses the new script on its next start.
mkdir -p "$SERVICE_TARGET/log"
for run_file in run log/run; do
    destination="$SERVICE_TARGET/$run_file"
    temporary=$(mktemp "$(dirname "$destination")/.run.XXXXXX")
    if [ -f "$destination" ]; then
        cp -p "$destination" "$temporary"
    fi
    cat "$UNIT_SOURCE/$run_file" > "$temporary"
    chmod 755 "$temporary"
    mv -f "$temporary" "$destination"
done
rm -f "$SERVICE_TARGET/down" "$SERVICE_TARGET/log/down"

# 5. Restore device-local files and drop stale flat-file leftovers.
for f in $LOCAL_ONLY; do
    [ -f "$TMP_BACKUP/$f" ] && cp -p "$TMP_BACKUP/$f" "$INSTALL_DIR/$f"
done
rm -rf "$TMP_BACKUP"
for f in $STALE_TOP_LEVEL; do
    rm -rf "${INSTALL_DIR:?}/$f"
done

# 5b. Optional: push the developer's config.json instead of keeping the
#     device copy (used by deploy.sh, where the dev machine is authoritative).
if [ "${PUSH_LOCAL_CONFIG:-0}" = "1" ] && [ -f "$SRC_DIR/config.json" ]; then
    SETUP_OPTIONS_DIR="/data/setupOptions/dbus-emporia-vue"
    mkdir -p "$SETUP_OPTIONS_DIR"
    cp -p "$SRC_DIR/config.json" "$INSTALL_DIR/config.json"
    cp -p "$SRC_DIR/config.json" "$SETUP_OPTIONS_DIR/config.json"
    sep "pushed config.json (PUSH_LOCAL_CONFIG=1)"
fi

# A valid existing symlink must retain its inode too. Never replace a live
# service directory or move another service out of the way.
if [ ! -L "$SERVICE_LINK" ]; then
    ln -s "$SERVICE_TARGET" "$SERVICE_LINK"
fi

# Refresh the boot hook before an existing exit statement. On boot it creates
# a missing canonical link, without deleting a directory or unexpected link.
RC_LOCAL="/data/rc.local"
if [ ! -f "$RC_LOCAL" ]; then
    printf '#!/bin/sh\n' > "$RC_LOCAL"
    chmod +x "$RC_LOCAL"
fi
sed -i '/# === dbus-emporia-vue service persistence ===/,/# === end dbus-emporia-vue ===/d' "$RC_LOCAL" 2>/dev/null || true
RC_BLOCK="$STAGING_DIR/rc.block"
cat > "$RC_BLOCK" << 'RCEOF'

# === dbus-emporia-vue service persistence ===
if [ ! -e /service/dbus-emporia-vue ] && [ ! -L /service/dbus-emporia-vue ]; then
    ln -s /data/dbus-emporia-vue/service/dbus-emporia-vue /service/dbus-emporia-vue
fi
if [ -L /service/dbus-emporia-vue ] && [ "$(readlink /service/dbus-emporia-vue)" = /data/dbus-emporia-vue/service/dbus-emporia-vue ]; then
    svc -u /service/dbus-emporia-vue/log 2>/dev/null || true
    svc -u /service/dbus-emporia-vue 2>/dev/null || true
fi
# === end dbus-emporia-vue ===
RCEOF
# An existing rc.local may end in "exit 0"; boot hooks appended after it never run.
awk -v block="$RC_BLOCK" '
    !inserted && /^exit[ \t]+0[ \t]*$/ {
        while ((getline line < block) > 0) print line
        close(block)
        inserted = 1
    }
    { print }
    END { if (!inserted) while ((getline line < block) > 0) print line }
' "$RC_LOCAL" > "$STAGING_DIR/rc.local"
cat "$STAGING_DIR/rc.local" > "$RC_LOCAL"
chmod +x "$RC_LOCAL"
sep "refreshed rc.local boot persistence block"

# Existing supervisors remain attached. Only a first installation needs
# svscan to notice the new link. PackageManager is not restarted by an update.
sleep 3
for service_path in "$SERVICE_LINK/log" "$SERVICE_LINK"; do
    svc -u "$service_path"
done

sep "installed version $(cat "$INSTALL_DIR/version" 2>/dev/null || echo unknown)"

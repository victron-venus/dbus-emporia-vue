#!/bin/bash
#
# Deploy dbus-emporia-vue to Venus OS
#
# Prerequisites:
#   - SSH config with host 'Cerbo' pointing to Venus OS device
#   - SSH key authentication configured
#
# Usage: ./deploy.sh [SSH_HOST]
#

set -e

SSH_HOST="${1:-Cerbo}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/data/dbus-emporia-vue"
SETUP_OPTIONS_DIR="/data/setupOptions/dbus-emporia-vue"
SERVICE_DIR="/service/dbus-emporia-vue"
LOG_DIR="/var/log/dbus-emporia-vue"
SEPARATOR="=============================================="

echo "$SEPARATOR"
echo "  Deploying dbus-emporia-vue to Venus OS"
echo "$SEPARATOR"
echo "SSH Host: $SSH_HOST"
echo ""

# Check local syntax before copying
echo ">>> Checking Python syntax..."
python3 -m py_compile "$SCRIPT_DIR/main.py"
echo "    Syntax OK"

# Create directories on remote
echo ">>> Creating directories..."
ssh "$SSH_HOST" "mkdir -p $INSTALL_DIR $SERVICE_DIR/log $LOG_DIR $SETUP_OPTIONS_DIR"

# Copy main Python file
echo ">>> Copying main.py..."
scp -q "$SCRIPT_DIR/main.py" "$SSH_HOST:$INSTALL_DIR/"
ssh "$SSH_HOST" "chmod +x $INSTALL_DIR/main.py"

# Copy vendored aiovelib library
echo ">>> Copying aiovelib..."
ssh "$SSH_HOST" "mkdir -p $INSTALL_DIR/aiovelib"
scp -q -r "$SCRIPT_DIR/aiovelib/." "$SSH_HOST:$INSTALL_DIR/aiovelib/"

# Copy setup and register-package scripts
echo ">>> Copying setup scripts..."
scp -q "$SCRIPT_DIR/setup" "$SSH_HOST:$INSTALL_DIR/"
ssh "$SSH_HOST" "chmod +x $INSTALL_DIR/setup"
scp -q "$SCRIPT_DIR/register-package.sh" "$SSH_HOST:$INSTALL_DIR/"
ssh "$SSH_HOST" "chmod +x $INSTALL_DIR/register-package.sh"

# Copy version file
if [[ -f "$SCRIPT_DIR/version" ]]; then
    echo ">>> Copying version..."
    scp -q "$SCRIPT_DIR/version" "$SSH_HOST:$INSTALL_DIR/"
fi

# Copy requirements.txt (optional, for reference)
if [[ -f "$SCRIPT_DIR/requirements.txt" ]]; then
    echo ">>> Copying requirements.txt..."
    scp -q "$SCRIPT_DIR/requirements.txt" "$SSH_HOST:$INSTALL_DIR/"
fi

# Copy gitHubInfo for PackageManager (create if missing)
if [[ -f "$SCRIPT_DIR/gitHubInfo" ]]; then
    echo ">>> Copying gitHubInfo..."
    scp -q "$SCRIPT_DIR/gitHubInfo" "$SSH_HOST:$INSTALL_DIR/"
else
    echo "victron-venus:latest" > "$SCRIPT_DIR/.gitHubInfo.tmp"
    scp -q "$SCRIPT_DIR/.gitHubInfo.tmp" "$SSH_HOST:$INSTALL_DIR/gitHubInfo"
    rm -f "$SCRIPT_DIR/.gitHubInfo.tmp"
fi

# Handle configuration: prefer local config.json (not in git) over example
if [[ -f "$SCRIPT_DIR/config.json" ]]; then
    echo ">>> Using existing local config.json..."
else
    echo ">>> No local config.json found."
    if [[ -n "$HA_URL" && -n "$HA_TOKEN" ]]; then
        echo ">>> Generating config.json from HA using ha_config_gen.py..."
        HA_URL="$HA_URL" HA_TOKEN="$HA_TOKEN" python3 "$SCRIPT_DIR/ha_config_gen.py"
        if [[ ! -f "$SCRIPT_DIR/config.json" ]]; then
            echo "!!! Failed to generate config.json. Please create it manually."
            exit 1
        fi
    else
        echo ">>> Please set HA_URL and HA_TOKEN environment variables to auto-generate config, or create config.json manually."
        echo "    Example:"
        echo "      export HA_URL=\"ws://192.168.1.50:8123/api/websocket\""
        echo "      export HA_TOKEN=\"your_long_lived_token\""
        echo "    Then re-run deploy.sh."
        exit 1
    fi
fi

# Copy config.json (local, may have been generated)
echo ">>> Copying config.json..."
scp -q "$SCRIPT_DIR/config.json" "$SSH_HOST:$INSTALL_DIR/"

# Also ensure config exists in setupOptions (for potential future use)
ssh "$SSH_HOST" "if [ ! -f $SETUP_OPTIONS_DIR/config.json ]; then
    cp $INSTALL_DIR/config.json $SETUP_OPTIONS_DIR/config.json
fi"

# Set up service: create run script and log run script
echo ">>> Setting up service..."
cat > /tmp/dbus-emporia-vue-run << 'EOF'
#!/bin/sh
exec 2>&1
cd /data/dbus-emporia-vue
exec python3 main.py
EOF
scp -q /tmp/dbus-emporia-vue-run "$SSH_HOST:$SERVICE_DIR/run"
ssh "$SSH_HOST" "chmod +x $SERVICE_DIR/run"

cat > /tmp/dbus-emporia-vue-log-run << 'EOF'
#!/bin/sh
exec 2>&1
exec multilog t s25000 n4 /var/log/dbus-emporia-vue
EOF
scp -q /tmp/dbus-emporia-vue-log-run "$SSH_HOST:$SERVICE_DIR/log/run"
ssh "$SSH_HOST" "chmod +x $SERVICE_DIR/log/run"

rm -f /tmp/dbus-emporia-vue-run /tmp/dbus-emporia-vue-log-run

# Restart PackageManager to discover package
echo ">>> Restarting PackageManager..."
ssh "$SSH_HOST" "svc -t /service/PackageManager 2>/dev/null || true"

# Stop service first to ensure clean restart, then start
echo ">>> Restarting service..."
ssh "$SSH_HOST" "svc -d $SERVICE_DIR 2>/dev/null || true"  # Disable (stop) service
ssh "$SSH_HOST" "svc -u $SERVICE_DIR 2>/dev/null || true"  # Enable (start) service

# Wait and check status
sleep 2
echo ">>> Service status:"
ssh "$SSH_HOST" "svstat $SERVICE_DIR"

echo ""
echo "$SEPARATOR"
echo "  Deployment Complete!"
echo "$SEPARATOR"
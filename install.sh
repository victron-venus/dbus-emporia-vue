#!/bin/bash
# Install script for dbus-emporia-vue service on Victron Venus OS (Cerbo GX)
# This script assumes you are running it on the Venus OS device or have copied the files to the device.

set -e

echo "=== dbus-emporia-vue Installation ==="

# Check if we are root
if [ "$(id -u)" -ne 0 ]; then
    echo "This script must be run as root"
    exit 1
fi

# Configuration
SERVICE_DIR="/service/dbus-emporia-vue"
REPO_DIR="$(
  cd "$(dirname "$0")" || exit
  pwd
)"

echo "Repository directory: $REPO_DIR"
echo "Service directory: $SERVICE_DIR"

# Create service directory
mkdir -p "$SERVICE_DIR"

# Copy files
echo "Copying files..."
cp "$REPO_DIR/main.py" "$SERVICE_DIR/"
cp "$REPO_DIR/config.json.example" "$SERVICE_DIR/config.json"
cp "$REPO_DIR/requirements.txt" "$SERVICE_DIR/"

# Make main.py executable
chmod +x "$SERVICE_DIR/main.py"

# Create run script for runit
echo "Creating runit run script..."
cat > "$SERVICE_DIR/run" << 'EOF'
#!/bin/bash
exec python3 /service/dbus-emporia-vue/main.py
EOF
chmod +x "$SERVICE_DIR/run"

# Install Python dependencies if pip is available
if command -v pip3 &> /dev/null; then
    echo "Installing Python dependencies..."
    pip3 install -r "$SERVICE_DIR/requirements.txt"
else
    echo "Warning: pip3 not found. Please install dependencies manually:"
    echo "  pip3 install -r $SERVICE_DIR/requirements.txt"
fi

echo "=== Installation complete ==="
echo "Next steps:"
echo "1. Edit $SERVICE_DIR/config.json with your Home Assistant details"
echo "2. Ensure the service is enabled (it should start automatically with runit)"
echo "3. Check logs with: sv log $SERVICE_DIR"
echo "4. To restart the service: sv restart $SERVICE_DIR"
# dbus-emporia-vue

A Python service for Victron Venus OS (Cerbo GX) that reads power measurements from Home Assistant via WebSocket API and registers individual AC loads on the Venus OS DBus system.

## Features

- Connects to Home Assistant via WebSocket API with long-lived access token authentication
- Subscribes only to the configured power sensors using HA `subscribe_trigger` (state-based triggers), keeping load on the GX device minimal
- Loads the current value of every channel via HA `get_states` on startup
- Registers each channel as a `com.victronenergy.acload.*` service on DBus using the standard `com.victronenergy.BusItem` interface (via a vendored copy of `aiovelib`)
- Assigns unique DeviceInstance numbers (configurable per channel) to avoid conflicts
- Tracks HA connection state: channels are marked `Connected=0` while the WebSocket link is down
- Provides example configuration and easy installation
- Can be installed via Venus OS PackageManager (using SetupHelper) – same pattern as `dbus-mqtt-battery`, `dbus-tasmota-pv`, `inverter-control`

## Current Integration and Future Plans

**Current:** The service obtains power data from Home Assistant via its WebSocket API. This is the simplest and most reliable method today, as the Emporia Vue integration already publishes individual channel power sensors to Home Assistant.

**Future:** We plan to add a direct connection to the Emporia Vue web portal/local API to eliminate the extra hop through Home Assistant. This will reduce latency and avoid maintaining two separate connections (HA + Vue) for the same data. For now, using Home Assistant is sufficient and keeps the architecture simple.

## Installation

### Manual Installation

1. Copy the `config.json.example` to `config.json` and edit it with your Home Assistant URL, long-lived access token, and channel mappings.
   * The resulting `config.json` contains your long-lived access token and should be kept private (it is already ignored by git).
   * Alternatively, you can generate a config automatically with the provided `ha_config_gen.py` script (see below).
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Make sure the `dbus-fast` and `websockets` packages are available in your Python environment.
4. Run the service:
   ```bash
   python main.py
   ```

### Venus OS PackageManager Installation (Recommended)

The service can be installed as a PackageManager package using the provided SetupHelper scripts.

1. Copy the entire `dbus-emporia-vue` directory to your Venus OS device (e.g., via SCP to `/root/`).
2. On the Venus OS device, run:
   ```bash
   cd /root/dbus-emporia-vue
   ./setup install
   ```
3. The package will be registered with PackageManager and can be managed via:
   - GUI v1: Settings → PackageManager
   - CLI: `/data/dbus-emporia-vue/setup install` (to reinstall) or `/data/dbus-emporia-vue/setup uninstall` to remove.

### First‑time Setup Wizard

You can also run the setup script interactively:
```bash
./setup
```
It will prompt you to choose install/uninstall.

## Configuration

Edit `config.json` with the following structure:

```json
{
  "ha_url": "ws://<YOUR_HOME_ASSISTANT_IP>:8123/api/websocket",
  "ha_token": "YOUR_LONG_LIVED_ACCESS_TOKEN",
  "channels": [
    {
      "ha_entity_id": "sensor.emporia_channel_1_power",
      "service_name": "com.victronenergy.acload.emporia_ch1",
      "instance": 71,
      "custom_name": "Heat Pump",
      "position": 0
    }
    // Add more channels as needed...
  ],
  "log_level": "INFO"
}
```

- `ha_url`: WebSocket URL of your Home Assistant instance
- `ha_token`: Long-lived access token from Home Assistant (create in Profile → Long-Lived Access Tokens)
- `channels`: Array of channel configurations:
  - `ha_entity_id`: Entity ID of the power sensor in Home Assistant (should report power in Watts)
  - `service_name`: DBus service name (must be unique, use the pattern `com.victronenergy.acload.emporia_chX`)
  - `instance`: DeviceInstance number (integer). **Choose numbers that do not conflict with existing devices on the VeBus.**  
    On a typical Venus OS system, numbers 41‑56 are partially occupied (e.g., 45 and 52 are used). A free block is 71‑86, so you may start at 71 and increment for each channel.
  - `custom_name`: Display name for the load (e.g., "Heat Pump", "Dryer")
  - `position`: AC position of the load:
    - `0` = AC output → shown under **Essential Loads** in the GUI
    - `1` = AC input → shown under **AC Loads** in the GUI
- `log_level`: `INFO` (default), `DEBUG` or `ERROR`

### How to verify free DeviceInstance numbers

On the Venus OS device, you can list all DeviceInstance values currently in use:

```bash
ssh root@cerbo "dbus -y com.victronenergy.vebus.ttyUSB2 / GetItems | grep -a DeviceInstance"
```

Look for gaps in the output; choose numbers that do not appear.

### Automatic configuration generation

If you prefer not to manually list each channel, you can use the helper script `ha_config_gen.py` to query Home Assistant for all power sensors (unit_of_measurement == 'W') and generate a `config.json` with sequential DeviceInstance numbers starting at 71.

Usage (run on a machine with network access to your HA instance):
```bash
HASS_SERVER=ws://<HA_IP>:8123/api/websocket HA_TOKEN=<your_long_lived_token> python ha_config_gen.py
```
The script will create (or overwrite) `config.json` in the current directory. Review the generated file and adjust `instance` numbers if needed to avoid collisions.

## Service Management on Venus OS

When installed via the setup script, the service is automatically created under `/service/dbus-emporia-vue` and supervised by runit. It will start on boot and restart after firmware updates.

To manually control the service:
```bash
# Start
svc -u /service/dbus-emporia-vue
# Stop
svc -d /service/dbus-emporia-vue
# Restart
svc -t /service/dbus-emporia-vue
# View logs
sv log /service/dbus-emporia-vue
```

### Verifying installation

After starting the service, you can confirm that the DBus services are registered:

```bash
# List all acload services on the system bus
ssh root@cerbo "dbus -y org.freedesktop.DBus /org/freedesktop/DBus ListNames | grep acload"

# Inspect one channel's exported paths
ssh root@cerbo "dbus -y com.victronenergy.acload.emporia_ch1 / GetItems"
```
You should see the standard Venus paths (`/Ac/Power`, `/Ac/L1/Power`, `/Connected`, `/CustomName`, `/DeviceInstance`, ...) with live values, and the system service should report:
```bash
ssh root@cerbo "dbus -y com.victronenergy.system /Ac/HasAcLoads GetValue"
# 1
```

## Notes

- This service does NOT register a Grid Meter. It is intended for individual submetering channels from an Emporia Vue device.
- Make sure the DeviceInstance numbers (instance) do not conflict with existing Victron devices. Use the verification method above to pick a free range.
- Because the subscription uses HA state *triggers*, idle channels (whose reading does not change) keep their last known value and are still reported as connected to HA.

## Dependencies

- Python 3.7+
- dbus-fast
- websockets
- requests (used by ha_config_gen.py)
- `aiovelib` (vendored under `aiovelib/`; `deploy.sh` copies it to the GX device, with a fallback to the copies shipped in `/opt/victronenergy/dbus-*/ext/aiovelib`)

## License

MIT
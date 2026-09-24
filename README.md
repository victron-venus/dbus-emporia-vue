# dbus-emporia-vue

Show Emporia Vue circuits as AC loads on a Victron GX device. Read power from
Home Assistant, or read power and energy directly from Emporia Cloud. You can
also send the direct readings to your own Home Assistant through GX MQTT.

The service runs on Venus OS. Each configured circuit becomes a Victron AC-load
service with its own name and device instance. Consumers such as Inverter Desktop
can display those loads.

## Python runtime

Native Venus OS packages target **Python 3.12.x**. The audited Cerbo on Venus OS
v3.75 reports Python **3.12.13**; the [official Venus OS v3.79 manifest](https://updates.victronenergy.com/feeds/venus/release/sdk/venus-scarthgap-x86_64-arm-cortexa8hf-neon-toolchain-v3.79.target.manifest)
also ships 3.12.13. Local development and CI use `.python-version` / Python
3.12.13. Regenerate both requirements locks with `--python-version 3.12.13`. The installer accepts 3.12 patch updates and rejects other minor versions
before stopping the running service. Use the firmware's system interpreter
and its matching D-Bus/GI libraries on the device; do not replace the OS Python.

## Choose your setup

### 1. Get readings from Home Assistant

**Choose this if the Emporia integration already works in HA and you want its
power readings on GX.**

```text
Emporia integration in HA -> this service on GX -> Victron AC loads
```

You need an HA URL, an HA access token and the power entity IDs. Keep the Emporia
integration enabled in HA. This setup forwards power; energy stays in HA.

[Setup instructions](docs/examples/1-from-home-assistant/README.md) ·
[GX config](docs/examples/1-from-home-assistant/config.json.example)

### 2. Get readings directly from Emporia Vue API

**Choose this if GX should collect Vue readings independently of HA.**

```text
Emporia Cloud -> this service on GX -> Victron AC loads
```

You need your Emporia account, internet access and the device/channel IDs. This
setup provides power, daily energy and monthly energy. HA and an MQTT bridge are
not required.

By default, power refreshes every 3 seconds, daily energy every 30 minutes and
monthly energy every 6 hours.

[Setup instructions](docs/examples/2-from-emporia-api/README.md) ·
[GX config](docs/examples/2-from-emporia-api/config.json.example) ·
[Credentials template](docs/examples/2-from-emporia-api/emporia-credentials.json.example)

### 3. Get readings from Emporia Vue API and use them in your own HA

**Choose this if GX should collect the readings and HA should consume them
through your existing MQTT broker.**

```text
Emporia Cloud -> this service on GX -> GX MQTT -> HA MQTT broker -> HA sensors
```

You need everything from setup 2, GX MQTT access, an HA MQTT integration and a
bridge between the two brokers. The example includes a GX config, bridge rules
and an HA package. The HA Emporia integration is not required for these sensors.

[Setup instructions and files](docs/examples/3-emporia-api-to-home-assistant/README.md) ·
[Full MQTT guide](docs/home-assistant-mqtt.md)

There are **two source modes**: `home_assistant` for setup 1 and `emporia` for
setups 2 and 3. Setup 3 adds MQTT consumers to setup 2. The driver connects only
to the selected source. To change it, edit `source` and restart the service.

## Before you start

- A GX device running Venus OS with Python 3.12.x and SSH access is required.
- Emporia API access is cloud-based and requires internet access on GX.
- Configuration is manual: choose the circuits and keep their device instances
  unique. Existing installations should retain their service names and instances.
- A 19-channel Raspberry Pi 3B installation on Venus OS 3.75 used about 44 MiB
  of service RAM. The service stores current readings and tokens; HA can store
  history when using setup 3.

## Installation

1. [Prepare the package and dependencies on GX](docs/installation.md#prepare-the-package).
2. Follow **one** setup above to create `/data/dbus-emporia-vue/config.json`
   and, for direct API access, the private credentials file.
3. [Start the service and verify readings](docs/installation.md#start-the-service).

The root `config.json.example` is a minimal copy of setup 2 for installer
compatibility. Start with the example for your chosen setup.

## Everyday commands

Run these on GX:

```sh
# Restart after editing config.json
svc -t /service/dbus-emporia-vue

# Check the service and the example circuit
svstat /service/dbus-emporia-vue
dbus -y com.victronenergy.acload.emporia_ch1 / GetItems
```

`/Connected=1` and a numeric `/Ac/Power` mean the circuit is available. Zero is a
valid reading. Unavailable source readings become unavailable on GX.

## Reference

- [Configuration and credentials](docs/configuration.md)
- [Find Emporia device and channel IDs](docs/configuration.md#find-your-emporia-device-and-channel-ids)
- [Installation, updates and troubleshooting](docs/installation.md)
- [D-Bus paths and MQTT values](docs/configuration.md#published-readings)
- [Home Assistant through GX MQTT](docs/home-assistant-mqtt.md)

<!-- ci-release-process:start -->
## Release process

See the [release strategy](RELEASING.md) for validation, nightly, beta, RC and stable promotion rules, and the [operator runbook](docs/release-workflow.md) for local commands.
<!-- ci-release-process:end -->

## License

MIT

## Tariff reference export

Use [the read-only tariff exporter](docs/tariff-export.md) to seed the dashboard
editor from the configured Emporia device. Utility-plan schedules still need
to be copied from the app; an ID alone is never treated as a flat price.

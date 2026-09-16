# Home Assistant through Cerbo GX MQTT

Use the MQTT broker already connected to Home Assistant to receive this driver's
measurements from Cerbo GX. A Mosquitto bridge forwards GX notifications into that
broker and sends read requests back to the GX device.

```text
Emporia API -------------------------+
                                    | one selected source
HA Emporia integration -- WebSocket -+
                                    v
                           dbus-emporia-vue on GX
                                    |
                                  D-Bus
                                    |
                            Venus OS MQTT broker
                                    |
                              MQTT bridge
                                    |
                            Home Assistant broker
                                    |
                             HA MQTT sensors
```

`source: "emporia"` connects only to Emporia. `source: "home_assistant"` connects
only to HA. There are no fallback requests or automatic source changes.

## 1. Prerequisites and example values

- Install and configure the driver using the [installation instructions](../README.md#installation).
- Enable local MQTT access on GX. Use its configured network security profile,
  authentication and TLS settings. Menu names vary by Venus OS version; see the
  [GX manual](https://www.victronenergy.com/media/pg/Cerbo_GX/en/index-en.html).
- Keep Home Assistant connected to its existing MQTT broker. Do not replace that
  connection with the GX broker.
- The examples use a local prefix of `victron/`, GX device instances `70` and `71`,
  and placeholder `PORTAL_ID`. Replace every occurrence before installing them.
- `PORTAL_ID` is the GX **VRM Portal ID**, not an Emporia device ID, MQTT client ID,
  or the numeric VRM installation ID. Find it in the GX VRM settings or an existing
  `N/<portal-id>/...` topic.
- `CERBO_IP` is the address reachable from the MQTT broker host/container.

The examples target Venus OS with dbus-flashmq. The driver does not publish HA
MQTT discovery messages; the YAML package below defines the HA entities.

## 2. Configure one driver source

### Emporia API

Start with [config.emporia.json](examples/config.emporia.json). It defines a main
meter at instance `70` and a heat-pump circuit at instance `71`. Replace device ID
`123456` and channel strings with your actual Emporia mappings. Keep existing
`id`, `service_name` and `instance` values when updating an installation; the
instance becomes part of the MQTT topic.

On GX, save the configuration as `/data/dbus-emporia-vue/config.json`. Create
`/data/dbus-emporia-vue/emporia-credentials.json` locally with this structure:

```json
{
  "username": "your-emporia-email@example.com",
  "password": "YOUR_EMPORIA_PASSWORD"
}
```

Create the file with private permissions before entering credentials, for example
with `umask 077` in the editing shell. Its required permissions are:

```sh
chmod 600 /data/dbus-emporia-vue/emporia-credentials.json
```

The driver creates and refreshes `emporia-tokens.json` with mode `0600`. Direct
mode needs internet access and the dependencies listed in the README. It does
not need an HA URL or token.

`emporia_import_channel` and `emporia_export_channel` are optional. Use them only
when the device provides those channels. They add energy values to the same
main-meter service; they do not create extra power meters. Additional circuit
entries need unique IDs, service names and instances.

### Home Assistant integration

Use [config.home-assistant.json](examples/config.home-assistant.json). Replace the
HA WebSocket URL, long-lived access token and power entity IDs. The source entities
must belong to the Emporia integration and must have supported power units.
Protect `config.json` with mode `0600` because it contains the HA token.

This mode forwards power. It does not create `/Emporia/Energy/*`, `/Emporia/DeviceId`,
`/Emporia/Channel` or `/Source/Type`. `/LastUpdate` exists only for a configured
submeter in this mode. Keep the power sensors from the HA package and remove its
direct-mode sensors. Energy already provided by the HA Emporia integration can
continue to be used directly in HA.

Never set `ha_entity_id` to an MQTT sensor produced by this driver. That creates
a loop: HA MQTT sensor → driver → GX MQTT → same HA sensor. Use separate names
for the original integration entities and the returned MQTT entities.

### Apply the selected source

For an installed service, restart after saving the configuration:

```sh
svc -t /service/dbus-emporia-vue
svstat /service/dbus-emporia-vue
tail -n 40 /var/log/dbus-emporia-vue/current
dbus -y com.victronenergy.acload.emporia_ch1 / GetItems
```

Check `/Connected` and `/Ac/Power`. In direct mode also check `/Source/Type`,
`/LastUpdate` and the energy paths. Switching modes requires changing `source`
and restarting; MQTT service identities can stay the same.

## 3. Reuse or configure the MQTT bridge

If the main broker already receives `victron/N/<portal-id>/...`, reuse its bridge.
These existing rules are sufficient:

```conf
topic N/# in 0 victron/
topic R/# out 0 victron/
```

Check that both directions exist. Receiving notifications alone does not let HA
send keepalive or read requests. No `W/` rule is needed for this guide. Preserve
any existing write routes used by other applications.

For a new bridge, use [mosquitto-cerbo.conf](examples/mosquitto-cerbo.conf). It
limits the N/R routes to one portal ID. Install it in an `include_dir` loaded by
the **main HA broker**, not on the GX device. Replace `CERBO_IP` and `PORTAL_ID`.
Port `1883` assumes that GX permits plain local MQTT on the trusted LAN; adapt
the transport to the GX listener you actually enabled.

If the GX listener requires credentials or TLS, set the bridge's `remote_username`,
`remote_password`, `bridge_cafile` and listener port as appropriate. Keep bridge
credentials in a private configuration file. These are credentials for GX, not
the credentials HA uses for its main broker. Consult the
[Mosquitto bridge options](https://mosquitto.org/man/mosquitto-conf-5.html).

For the [HA Mosquitto app/add-on](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md),
a common arrangement is a file under
`/share/mosquitto/` and this app configuration:

```yaml
customize:
  active: true
  folder: mosquitto
```

For standalone or containerized Mosquitto, mount the file into its configured
include directory. For example, the main configuration can contain:

```conf
include_dir /mosquitto/config/conf.d
```

Keep the broker's existing listeners, users and persistence configuration. Restart
the broker after adding a bridge and check its logs. An existing working bridge
does not need a restart for new driver channels. Run only one bridge for these
routes; parallel copies can duplicate traffic.

### Topic translation

The bridge adds `victron/` only on the HA broker side:

```text
GX notification: N/PORTAL_ID/acload/71/Ac/Power
HA state topic:  victron/N/PORTAL_ID/acload/71/Ac/Power

HA request:     victron/R/PORTAL_ID/keepalive
GX request:     R/PORTAL_ID/keepalive
```

If your bridge uses no local prefix, remove `victron/` from every HA example.
If it uses a different prefix, replace it consistently in both N and R topics.
Do not add the prefix twice.

## 4. Verify messages on the HA broker

In HA, open **Settings → Devices & services → MQTT → Configure** and use its
topic listener for `victron/N/PORTAL_ID/acload/#`. Publish this message through
the same MQTT integration, using **Developer tools → Actions**:

```yaml
action: mqtt.publish
data:
  topic: victron/R/PORTAL_ID/keepalive
  payload: '{}'
  qos: 0
  retain: false
```

Example notifications:

```text
victron/N/PORTAL_ID/acload/71/Ac/Power              {"value": 842.5}
victron/N/PORTAL_ID/acload/71/Connected             {"value": 1}
victron/N/PORTAL_ID/acload/71/Source/Type           {"value": "emporia"}
victron/N/PORTAL_ID/acload/71/Emporia/Energy/Day     {"value": 4.218}
victron/N/PORTAL_ID/acload/71/Emporia/Energy/Month   {"value": 87.631}
```

The JSON `value` is the measurement. Power is W; energy is kWh. `{"value": null}`
is unavailable data, not zero. Service removal can produce an empty payload.

To request one leaf explicitly, publish an empty payload to its R topic:

```yaml
action: mqtt.publish
data:
  topic: victron/R/PORTAL_ID/acload/71/Ac/Power
  payload: ''
  retain: false
```

Use exact leaf paths for individual requests. Subscribe with `#` when listening;
do not put MQTT wildcards in published request topics.

The driver exports power on both `Ac/Power` and `Ac/L1/Power`. They represent the
same channel total; adding them together would double-count it. MQTT instances
come from `instance`, not the Emporia channel number or D-Bus service suffix.

## 5. Add the Home Assistant package

Copy [home-assistant-emporia.yaml](examples/home-assistant-emporia.yaml) to
`/config/packages/emporia_mqtt.yaml` on the HA host. Replace all `PORTAL_ID`
placeholders and adapt instances and names. The example provides:

- Main-meter and circuit power sensors.
- Circuit daily and monthly energy.
- Main-meter daily and monthly import/export energy.
- Direct-source diagnostics.
- An MQTT keepalive automation.

Enable package loading in `configuration.yaml` if it is not already configured:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Merge `packages` into the existing `homeassistant` mapping; do not add a duplicate
top-level key. If package loading already exists, use its current layout. The file
contains top-level `mqtt` and `automation` sections. It can also be merged into
an existing manual setup: entries under `mqtt.sensor` go under the existing
sensor list, and the automation goes into the existing automation list.
See [HA configuration packages](https://www.home-assistant.io/docs/configuration/packages/).

Keep the existing MQTT YAML style consistent. This package uses a mapping with
`mqtt.sensor`. If your setup uses a per-item list under `mqtt:`, convert each
sensor to a `- sensor:` item in that list instead of merging this mapping into
it. HA does not support mixing those two forms. See
[manual MQTT configuration](https://www.home-assistant.io/integrations/mqtt/#manual-configured-mqtt-items).

Run HA's configuration check, then restart HA to load the package. Confirm the
new MQTT entities in **Settings → Devices & services → Entities**. A `unique_id`
allows later UI customization; it does not force a specific entity ID.

To add a circuit, copy the instance-71 sensor entries and change their topic
instance, `unique_id` and name. Keep unique IDs stable thereafter. In HA-source
mode keep only sensors whose paths are available in that mode, as described in
section 2.

### Keepalive and unchanged readings

The package publishes `{}` to `victron/R/PORTAL_ID/keepalive` every 30 seconds,
at HA startup and when HA announces `online` on `homeassistant/status`. Adapt
that trigger if you customized HA's MQTT birth topic or payload.

GX requires a keepalive within 60 seconds. This payload also refreshes the
current GX snapshot, including unchanged values. It reads cached D-Bus state;
it does not make additional Emporia or HA API requests. It republishes GX
telemetry beyond this driver's channels. See
[the Victron MQTT keepalive protocol](https://github.com/victronenergy/dbus-flashmq#keep-alive).

The sensors use `expire_after: 90` so a lost bridge/GX connection becomes
unavailable even when its last `/Connected` value was `1`. Keep the periodic
snapshot refresh when using these examples: a keepalive with
`suppress-republish` alone would let a healthy, unchanged zero-power reading
expire. Do not retain keepalive requests or republish telemetry as retained state.

If an existing automation already sends a full GX snapshot request at least
every 30 seconds, retain that automation and omit the example's duplicate.
The legacy `R/PORTAL_ID/system/0/Serial` request with an empty or `{}` payload is
also a full keepalive on dbus-flashmq; an existing automation using that form
already provides the refresh.

### Availability and energy freshness

Power uses `/Connected` plus MQTT expiration. Direct mode also invalidates stale
power inside the driver. HA-source mode follows the source entity and WebSocket
connection; ordinary channels do not gain the direct-mode timestamp checks.

Energy uses its own `Updated` path, independent of `/Connected`. With the default
poll intervals, the validity limits are 1,830 seconds for daily energy and 7,230
seconds for monthly energy. If you change an energy poll interval, change the
matching YAML age limit to `2 * interval + 30`. Keep GX and HA clocks synchronized.
An energy value can remain valid while current power is unavailable.

The templates preserve null or empty messages as unknown/unavailable instead of
turning them into zero. The expiration and availability options are described in
the [HA MQTT sensor documentation](https://www.home-assistant.io/integrations/sensor.mqtt/).

## 6. Energy dashboard and totals

`Emporia/Energy/Day` and `Month` are current-period readings. They reset on the
source's period boundaries and can be signed for net/bidirectional channels.
Their `Updated` paths are freshness timestamps, not reset markers. The driver
does not export a lifetime counter; `Ac/Energy/Forward` is unavailable.

The example intentionally leaves period-energy `state_class` unset. These values
are useful on cards and history charts, but are not automatically suitable for
the Energy dashboard. Never label signed net energy `total_increasing`, or add
daily and monthly readings together.

For a verified nonnegative import/export or consumption counter that increases
within each period, you can opt into `state_class: total_increasing`. A decrease
is then interpreted by HA as a counter reset. Cloud corrections can look like
resets, and missed readings around a boundary can lose consumption. Select one
period per flow and check its behavior before using it for long-term statistics.
See [HA sensor statistics semantics](https://developers.home-assistant.io/docs/core/entity/sensor/#long-term-statistics).

Alternatively, create an Integral helper from a nonnegative MQTT power sensor.
For the heat-pump circuit, set its entity ID in HA to
`sensor.emporia_heat_pump_power_mqtt`, then this optional package fragment creates
estimated energy in kWh:

```yaml
sensor:
  - platform: integration
    source: sensor.emporia_heat_pump_power_mqtt
    name: Emporia heat pump estimated energy
    unique_id: emporia_heat_pump_estimated_energy
    unit_prefix: k
    unit_time: h
    method: left
    round: 3
    max_sub_interval:
      minutes: 5
```

This works with either driver source and estimates energy from received power;
it cannot reconstruct missing power during outages. Keep it separate from the
cloud period readings. Use separate nonnegative import/export flows for grid
accounting, not a signed net-power sensor. See the
[HA Integral helper](https://www.home-assistant.io/integrations/integration/) and
[Energy dashboard requirements](https://www.home-assistant.io/docs/energy/faq/).

## 7. Troubleshooting

- **No `acload` topics:** check service registration and `/DeviceInstance` on GX,
  then the portal ID, bridge subscription and local topic prefix.
- **Messages only appear briefly:** check the R route and the keepalive automation.
  A TCP/MQTT connection alone does not keep GX telemetry active.
- **Stable zero becomes unavailable:** restore the full periodic snapshot. Zero
  is valid and must remain zero; suppressing republish can hide unchanged values.
- **Power is null or `/Connected` is `0`:** inspect driver logs and the selected
  source. MQTT cannot repair an unavailable upstream reading.
- **Power works but energy is missing:** confirm direct mode and device/channel
  mappings. Import/export fields require their optional channel mappings. HA
  source mode forwards power only.
- **Energy becomes unavailable:** check its `Updated` value, clock alignment and
  configured polling interval. A fresh MQTT snapshot does not make an old source
  timestamp fresh.
- **Entities remain absent:** verify package inclusion, YAML validation and unique
  IDs. This driver does not announce HA discovery configurations.
- **Energy is absent from the Energy dashboard:** use suitable statistics semantics
  or the Integral helper; do not assign counter semantics solely to make it appear.
- **Duplicate readings or loops:** check for multiple bridges, duplicate YAML
  entities and HA source entities that reference this driver's MQTT output.

Removing the HA package removes these manually configured entities after a
configuration reload/restart. Do not remove a shared MQTT bridge or keepalive
automation that other Victron consumers still use.

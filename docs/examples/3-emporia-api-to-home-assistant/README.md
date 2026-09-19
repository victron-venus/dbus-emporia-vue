# 3. Read Emporia API and send readings to your Home Assistant

Choose this setup to show Emporia loads on GX and use the same readings in your
own HA dashboards and automations. The driver reads the Emporia Cloud API;
Venus OS publishes the resulting D-Bus values through its MQTT broker. An MQTT
bridge carries those values to the broker already used by HA.

```text
Emporia Cloud → driver on GX → Venus MQTT → existing HA broker → HA sensors
```

This uses `source: "emporia"`, just like scenario 2. It adds no input source,
fallback or driver MQTT publisher. It needs no HA API token or HA Emporia
integration.

## What you need

- A supported GX device with internet access and local MQTT enabled.
- Emporia account credentials, a device ID and channel identifiers; see
  [Emporia prerequisites](../2-from-emporia-api/README.md#before-you-start).
- HA connected to an MQTT broker that can bridge to GX, such as Mosquitto.
- The GX VRM Portal ID, its reachable address and any GX MQTT credentials.

This example defines a main meter at GX instance `70` and a heat-pump circuit at
`71`. The HA package contains 12 sensors: power, period energy and diagnostics.
Energy sensors are display values by default; see the
[Energy dashboard guidance](../../home-assistant-mqtt.md#6-energy-dashboard-and-totals)
before adding them to energy statistics.

## Set it up

If the driver is already configured, keep your current `config.json` and its
channel identities. For an existing direct-API setup, continue at step 4 and
adapt the HA package to your instances. The copy commands below are for a new
installation.

1. [Prepare the package](../../installation.md#prepare-the-package) on GX, then
   copy this scenario's [config.json.example](config.json.example):

   ```sh
   cd /data/dbus-emporia-vue
   umask 077
   cp docs/examples/3-emporia-api-to-home-assistant/config.json.example config.json
   ```

   Edit `config.json`: replace device ID `123456` and channel strings with your
   account's mappings. Keep instances `70` and `71` for this example, or change
   them in the HA package too. On an existing installation, adapt your config
   while retaining its channel IDs, service names and instances.
2. Copy the shared [credentials template](../2-from-emporia-api/emporia-credentials.json.example)
   on GX, then enter your Emporia username and password in the new file:

   ```sh
   cd /data/dbus-emporia-vue
   umask 077
   cp docs/examples/2-from-emporia-api/emporia-credentials.json.example emporia-credentials.json
   chmod 600 emporia-credentials.json
   ```

   The driver creates and refreshes `emporia-tokens.json` in the same directory
   with mode `0600`. Keep both files private on GX.
3. For a first installation, finish [Start the service](../../installation.md#start-the-service).
   After later configuration edits, restart it with
   `svc -t /service/dbus-emporia-vue`. Verify the running service and readings:

   ```sh
   svstat /service/dbus-emporia-vue
   dbus -y com.victronenergy.acload.emporia_ch1 / GetItems
   ```

   Expect `/Connected` to be `1`, `/Ac/Power` to be numeric and `/Source/Type` to
   be `emporia`.
4. Reuse your existing GX bridge if it forwards both notifications and read
   requests. Otherwise, install [mosquitto-cerbo.conf](mosquitto-cerbo.conf) in
   the include directory of the **main HA broker**, replacing `CERBO_IP` and
   `PORTAL_ID`. Adjust GX authentication/TLS to match your listener. Follow the
   [bridge instructions](../../home-assistant-mqtt.md#3-reuse-or-configure-the-mqtt-bridge)
   for broker-specific paths and restart steps.
5. Verify that HA receives `victron/N/PORTAL_ID/acload/#` from its existing
   broker using the [MQTT message check](../../home-assistant-mqtt.md#4-verify-messages-on-the-ha-broker).
6. Copy [home-assistant-emporia.yaml](home-assistant-emporia.yaml) to
   `/config/packages/emporia_mqtt.yaml` on **HA**. Replace all `PORTAL_ID`
   occurrences and match your bridge prefix and GX instances. Enable package
   loading, check the configuration, then restart HA as described in the
   [package instructions](../../home-assistant-mqtt.md#5-add-the-home-assistant-package).
   If a full GX keepalive already runs at least every 30 seconds, omit the
   example's keepalive automation.

`emporia_import_channel` and `emporia_export_channel` are optional. If your
meter does not expose them, remove those keys from the driver config and remove
the four import/export sensors from the HA package. To add circuits, copy a
channel and its matching HA sensor entries with unique IDs and GX instances.

## Check the result

In HA, the new MQTT power sensors should be numeric, including zero when a
circuit is idle. The circuit's Power Source diagnostic should show `emporia`.
Daily energy refreshes every 30 minutes and monthly energy every 6 hours by
default. The MQTT keepalive refreshes cached GX readings; it does not request
more cloud readings.

The example creates new MQTT entities. It does not replace an existing HA
Emporia integration or preserve its entity IDs automatically. Update dashboard
and automation references before disabling an existing integration.

See the [complete MQTT reference](../../home-assistant-mqtt.md) for freshness,
energy statistics, topic translation and troubleshooting. To receive data from
HA instead, choose [scenario 1](../1-from-home-assistant/README.md).

# 2. Read directly from the Emporia Vue API

Use this when you want the GX device to read your Vue account directly.

`Emporia Vue API → this driver on GX → AC load services`

This example creates one AC load named **Heat Pump**, with instance **71**,
and exposes its power plus daily and monthly energy. HA is not required.
The driver connects only to Emporia. Internet access is required.

## Before you start

- Complete the package and dependency preparation in
  [Installation](../../../README.md#installation), including `pyemvue`.
- Have your Emporia account email and password, with a working Vue meter.
- [Find your device and channel IDs](../../configuration.md#find-your-emporia-device-and-channel-ids).
  The sample values `123456` and `"1"` must match your meter and circuit.

## Configure

For a new installation, run these commands on the GX device:

```sh
cd /data/dbus-emporia-vue
umask 077
cp docs/examples/2-from-emporia-api/config.json.example config.json
cp docs/examples/2-from-emporia-api/emporia-credentials.json.example emporia-credentials.json
chmod 600 config.json emporia-credentials.json
vi emporia-credentials.json
vi config.json
```

In `emporia-credentials.json`, replace `username` and `password` with your
Emporia account credentials. Keep the file private on the GX device.

In `config.json`, replace `emporia_device_gid`, `emporia_channel` and
`custom_name`. Keep the channel value a JSON string, including values such as
`"1,2,3"` for a main channel. Paths to credentials and tokens are relative to
`config.json`.

Use a free `instance` and `service_name` if **71** or `emporia_ch1` is already
in use. For an existing installation, edit its configuration and preserve the
channel's `id`, `instance` and `service_name`.

The driver creates and refreshes `emporia-tokens.json` automatically with
permissions `0600`. Do not create it manually. The credentials file must also
remain `0600`. Neither file belongs in Git.

## Start and verify

Finish [Installation](../../../README.md#installation) to install and start the
service. After later configuration edits, restart it:

```sh
svc -t /service/dbus-emporia-vue
```

Inspect the example channel:

```sh
dbus -y com.victronenergy.acload.emporia_ch1 / GetItems
```

Check `/Connected=1`, `/Source/Type=emporia`, current `/LastUpdate` and numeric
`/Ac/Power`. Energy appears under `/Emporia/Energy/Day` and
`/Emporia/Energy/Month`. A reading of zero is valid. If unavailable, check
the credentials, device/channel mapping, internet access and
`/var/log/dbus-emporia-vue/current`.

Power updates every 3 seconds by default; daily energy every 15 minutes and
monthly energy every hour. These energy readings are period totals, not
lifetime counters.

To add more channels, copy the channel object and give each one a distinct
`id`, `service_name` and `instance`, with its own Emporia mapping.
See the [configuration reference](../../configuration.md) for optional settings.
To also send the readings to your own HA installation, continue with
[example 3](../3-emporia-api-to-home-assistant/README.md).

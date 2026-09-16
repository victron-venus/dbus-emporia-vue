# 1. Read from Home Assistant

Use this when the Emporia integration already works in Home Assistant and you
want its power readings on your GX device.

`Emporia integration in HA → this driver on GX → AC load services`

This example creates one AC load named **Heat Pump**, with instance **71**.
It reads power from HA; it does not provide Emporia daily or monthly energy.
The driver connects only to HA. Keep the HA Emporia integration enabled.

## Before you start

- Complete the package and dependency preparation in
  [Installation](../../../README.md#installation).
- Have a working Emporia power sensor in HA, reporting watts (`W`).
  This example uses its numeric state as watts; it does not convert `kW`.
- Find its entity ID in HA and create a long-lived access token in your HA
  user profile. The GX device must be able to reach HA.

## Configure

For a new installation, run these commands on the GX device:

```sh
cd /data/dbus-emporia-vue
umask 077
cp docs/examples/1-from-home-assistant/config.json.example config.json
chmod 600 config.json
vi config.json
```

In `config.json`, replace:

- `ha_url` with your HA WebSocket URL, including `/api/websocket`. Use `wss://`
  for an HTTPS endpoint.
- `ha_token` with your long-lived access token.
- `ha_entity_id` with your existing Emporia power entity ID.
- `custom_name` with the name you want to display on GX.

Use a free `instance` and `service_name` if **71** or `emporia_ch1` is already
in use. For an existing installation, edit its configuration and preserve the
channel's `id`, `instance` and `service_name`.

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

Check that `/Connected` is `1` and `/Ac/Power` matches the HA sensor in watts.
A reading of zero is valid. If unavailable, check the HA entity, token, URL
and `/var/log/dbus-emporia-vue/current`.

To add more channels, copy the channel object and give each one a distinct
`id`, `ha_entity_id`, `service_name` and `instance`.
See the [configuration reference](../../configuration.md) for optional settings.
Do not use this driver's MQTT output as an HA source entity.

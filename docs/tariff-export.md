## Emporia import

The companion `dbus-emporia-vue/scripts/export_tariff.py` reads the existing
configured device's `locationProperties` endpoint and emits only tariff fields.
Run it on the machine that already holds the driver's configuration and tokens:

```sh
python3 scripts/export_tariff.py --config /path/to/config.json \
  --device-gid 12345 --currency USD --output /tmp/emporia-tariff.json
```

Use the actual configured device ID and the currency shown in the Emporia app.
Import the resulting JSON with **Import tariff**. The exporter refuses to
replace an existing file and never includes credentials or address fields.

A nonempty `utilityRateGid` identifies a selected utility plan; the available
PyEmVue device-properties contract does not provide the plan's time-of-use
schedule. Such an import retains the plan reference and leaves price cells
blank. Copy the actual schedule from the Emporia app, review it, and save.
It never treats `usageCentPerKwHour` as a complete TOU plan. For a legacy flat
plan without a utility plan ID, cents are converted to currency/kWh explicitly.

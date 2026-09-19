# Install and operate the service

Choose [one setup](../README.md#choose-your-setup) before configuring the service.
The steps below are shared by all three setups.

## Prepare the package

You need SSH access to a GX device running Venus OS and Python 3.11 or newer.
Run `python3 --version` on GX to check. The service uses `dbus-fast` and
`websockets`; direct Emporia access also uses `pyemvue` and its dependencies.

For a new installation, download the complete package archive from
[Releases](https://github.com/victron-venus/dbus-emporia-vue/releases). Select the
uploaded asset named `dbus-emporia-vue-<version>.tar.gz` and extract it on GX so
that `main.py`, `update.sh`, `requirements.lock` and `docs/` are under
`/data/dbus-emporia-vue`. The archive has a `dbus-emporia-vue/` top-level directory.
The examples below assume this complete package is present before installation.

Keep dependencies in `/data/dbus-emporia-vue/vendor`. The service and installer
load that directory, and updates preserve it. On GX, with a target-compatible
Python interpreter and pip available:

```sh
cd /data/dbus-emporia-vue
python3 -m pip install --require-hashes --target /data/dbus-emporia-vue/vendor -r requirements.lock
PYTHONPATH=/data/dbus-emporia-vue/vendor python3 -c "import dbus_fast, websockets, pyemvue"
```

The lock installs dependencies for all three setups. If GX has no pip or a
required binary wheel is unavailable, prepare `vendor/` on a matching Linux CPU
architecture and Python version, then copy it to GX. Mac or Windows binary
packages cannot be used on GX. Existing firmware dependencies can also satisfy
the imports. Keep installations under `/data`, outside the firmware filesystem.

Now configure **one** setup:

1. [Read power from HA](examples/1-from-home-assistant/README.md#configure).
2. [Read power and energy from Emporia API](examples/2-from-emporia-api/README.md#configure).
3. [Read Emporia API and send measurements to HA](examples/3-emporia-api-to-home-assistant/README.md#set-it-up).

Return here once `config.json` and any required credentials are ready.

## Start the service

With SetupHelper installed at `/data/SetupHelper`, run on GX:

```sh
cd /data/dbus-emporia-vue
./setup install
```

Without SetupHelper, run `sh update.sh` from the same directory. Both commands
use the same updater. The installer checks dependency imports before stopping
an existing service; it does not run pip.

Verify the process and the example circuit:

```sh
svstat /service/dbus-emporia-vue
dbus -y com.victronenergy.acload.emporia_ch1 / GetItems
```

Expect a running process, `/Connected=1` and numeric `/Ac/Power`. Direct mode
also exposes `/Source/Type=emporia` and `/LastUpdate`. A running process alone
does not establish that readings are available. Check your chosen setup's
verification steps, including HA MQTT sensors for setup 3.

## Change configuration or update

After editing the installed `config.json`, restart the service:

```sh
svc -t /service/dbus-emporia-vue
```

For an update, extract the new complete package into a separate staging
directory on GX and run its `sh update.sh`. It installs into
`/data/dbus-emporia-vue` and preserves the existing configuration, credentials,
tokens, `vendor/` directory and service supervisors. Existing service names and
instances should remain unchanged. Restore a previous package with its
`update.sh` and a configuration compatible with that version.

The updater copies runtime files; documentation and examples remain in the
extracted package. Firmware updates may replace system dependencies, so verify
the imports and readings again afterward.

### Deploy from a workstation checkout

With SSH key authentication configured, run `./deploy.sh root@cerbo` from the
checkout. It uploads the tracked release files and the local `config.json`, if
present. That local configuration replaces the device configuration. Without a
local config, the device keeps its current config, unless `HA_URL` and `HA_TOKEN`
are set and generate a new HA configuration. Emporia credentials and token files
stay on GX and are never uploaded by deployment.

Prepare the private credentials and dependencies on GX before deploying.
`deploy.sh` waits for a new heartbeat and a running process; also verify live
readings after deployment. Its temporary package, including examples, is removed
after installation, so copy/edit example configs in the workstation checkout
when using this path.

## Troubleshooting and service commands

```sh
# Start or stop
svc -u /service/dbus-emporia-vue
svc -d /service/dbus-emporia-vue

# Inspect status and recent logs
svstat /service/dbus-emporia-vue /service/dbus-emporia-vue/log
tail -n 40 /var/log/dbus-emporia-vue/current
```

If a channel is unavailable, check the chosen setup's account/HA connection,
channel mapping and internet access. Credential files must have owner-only
permissions; use `chmod 600` on those files. For HA MQTT availability or missing
messages, use the [MQTT troubleshooting guide](home-assistant-mqtt.md).

The persistent service directory is
`/data/dbus-emporia-vue/service/dbus-emporia-vue`. A boot hook recreates the
`/service/dbus-emporia-vue` symlink. Logs rotate four 25 KB files, and the service
writes its heartbeat atomically to `/tmp/dbus-emporia-vue.heartbeat`.

The updater stops only this application and retains its logger. It sends one
supervisor-scoped kill after 20 seconds if needed and aborts after 25 seconds if
the process has not stopped. Unexpected service paths are rejected before
stopping. With SetupHelper, `./setup uninstall` removes the service and boot hook.

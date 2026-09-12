#!/usr/bin/env python3
"""Expose Emporia Vue channels as Victron AC Loads on the Venus OS D-Bus.

Connects to Home Assistant over WebSocket, subscribes to state changes of
exactly the configured Emporia power sensors via ``subscribe_trigger`` and
publishes each channel as a ``com.victronenergy.acload.*`` service using the
standard ``com.victronenergy.BusItem`` interface (aiovelib).
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime

import websockets

try:
    from dbus_fast import BusType
    from dbus_fast.aio.message_bus import MessageBus
except ImportError:
    BusType = None  # type: ignore[assignment, misc]
    MessageBus = None  # type: ignore[assignment, misc]

import secrets
import tempfile
import time
from pathlib import Path

from parse_ha import parse_ha_state_change, parse_initial_state

_here = os.path.dirname(os.path.abspath(__file__))

for _p in (
    os.path.join(_here, "aiovelib"),
    "/opt/victronenergy/dbus-mqtt-integrations/aiovelib",
    "/opt/victronenergy/dbus-acsystem/ext/aiovelib",
    "/opt/victronenergy/dbus-shelly/ext/aiovelib",
):
    if os.path.isfile(os.path.join(_p, "aiovelib", "service.py")):
        sys.path.insert(0, _p)
        break

from aiovelib.service import DoubleItem, IntegerItem, Service, TextItem  # noqa: E402


def write_heartbeat(path: Path | None = None) -> None:
    """Atomically replace the heartbeat without following an existing symlink."""
    destination = path or Path(tempfile.gettempdir()) / "dbus-emporia-vue.heartbeat"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".dbus-emporia-vue-heartbeat-",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(str(int(time.time())))
            temporary.flush()
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


PRODUCT_ID = 0xFFFF

PATH_CONNECTED = "/Connected"
PATH_STATUS = "/Status"

DEFAULT_CONFIG = {
    # User-overridable Home Assistant LAN example, including its placeholder IP.
    "ha_url": "ws://192.168.1.50:8123/api/websocket",  # NOSONAR(S5332, S1313)
    "ha_token": "",
    "channels": [],
    "log_level": "INFO",
}

logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

for _name in ("websockets", "websockets.client", "websockets.protocol"):
    _mod = logging.getLogger(_name)
    _mod.setLevel(logging.CRITICAL)
    _mod.propagate = False


def _state_updated_at(state):
    """Read HA's timestamp only for ordering startup snapshot/event overlap."""
    try:
        value = datetime.fromisoformat(state.get("last_updated"))
        return value if value.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def read_version():
    try:
        with open(os.path.join(_here, "version")) as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


VERSION = read_version()


class AcLoadService:
    """A com.victronenergy.acload.* service backed by an aiovelib Service."""

    def __init__(self, bus, service_name, instance, custom_name, position):
        self._bus = bus
        self._service = Service(bus, service_name)
        self._service.add_item(TextItem("/Mgmt/ProcessName", os.path.basename(__file__)))
        self._service.add_item(TextItem("/Mgmt/ProcessVersion", VERSION))
        self._service.add_item(TextItem("/Mgmt/Connection", "Home Assistant"))
        self._service.add_item(IntegerItem("/DeviceInstance", instance))
        self._service.add_item(IntegerItem("/ProductId", PRODUCT_ID))
        self._service.add_item(TextItem("/ProductName", "Emporia Vue AC Load"))
        self._service.add_item(TextItem("/CustomName", custom_name))
        self._service.add_item(TextItem("/FirmwareVersion", VERSION))
        self._service.add_item(IntegerItem("/Position", position))
        self._service.add_item(IntegerItem(PATH_CONNECTED, 0))
        self._service.add_item(IntegerItem(PATH_STATUS, 1))
        self._service.add_item(IntegerItem("/IsGenericEnergyMeter", 1))
        self._service.add_item(DoubleItem("/Ac/Power", None))
        self._service.add_item(DoubleItem("/Ac/L1/Power", None))
        self._service.add_item(DoubleItem("/Ac/Energy/Forward", None))

    @property
    def name(self):
        return self._service.name

    async def register(self):
        await self._service.register()

    async def close(self):
        await self._service.close()
        # Each service owns its D-Bus connection (one com.victronenergy.*
        # name per connection, every service exports BusItem at "/").
        self._bus.disconnect()

    def update_power(self, power):
        with self._service as s:
            s["/Ac/Power"] = power
            s["/Ac/L1/Power"] = power
            s[PATH_CONNECTED] = 1 if power is not None else 0
            s[PATH_STATUS] = 0 if power is not None else 1

    def set_connected(self, connected):
        with self._service as s:
            s[PATH_CONNECTED] = 1 if connected else 0
            s[PATH_STATUS] = 0 if connected else 1


class HaWebSocketClient:
    """Handle the WebSocket connection to Home Assistant."""

    def __init__(self, url, token, channel_map):
        self.url = url
        self.token = token
        self.channel_map = channel_map
        self.websocket = None
        self._message_id = 1

    async def connect(self):
        logger.info("Connecting to Home Assistant at %s", self.url)
        self.websocket = await websockets.connect(self.url, max_size=10**7)

        initial = json.loads(await self.websocket.recv())
        if initial.get("type") != "auth_required":
            raise RuntimeError(f"Expected auth_required, got: {initial}")

        await self.websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
        auth_resp = json.loads(await self.websocket.recv())
        if auth_resp.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant authentication failed: {auth_resp}")

        logger.info("Authenticated with Home Assistant")
        await self.subscribe_triggers()
        await self.fetch_initial_states()
        logger.info("Connected, subscribed to %d entities", len(self.channel_map))

    async def subscribe_triggers(self):
        request = {
            "id": self._message_id,
            "type": "subscribe_trigger",
            "trigger": {
                "platform": "state",
                "entity_id": list(self.channel_map.keys()),
            },
        }
        self._message_id += 1
        await self.websocket.send(json.dumps(request))
        response = json.loads(await self.websocket.recv())
        if response.get("success") is not True:
            raise RuntimeError(f"Failed to subscribe to triggers: {response}")
        logger.info("Subscribed to state triggers for %d entities", len(self.channel_map))

    async def fetch_initial_states(self):
        request = {
            "id": self._message_id,
            "type": "get_states",
        }
        self._message_id += 1
        await self.websocket.send(json.dumps(request))
        # Skip trigger events that may arrive before the get_states reply.
        request_id = request["id"]
        response = None
        event_updates = {}
        for _ in range(50):
            message = json.loads(await self.websocket.recv())
            if message.get("type") == "event":
                await self.handle_message(json.dumps(message))
                trigger = message.get("event", {}).get("variables", {}).get("trigger", {})
                entity_id = trigger.get("entity_id")
                if entity_id in self.channel_map:
                    event_updates[entity_id] = _state_updated_at(trigger.get("to_state"))
            if message.get("id") == request_id and ("result" in message or "error" in message):
                response = message
                break
        if response is None or response.get("success") is not True:
            logger.warning("Could not fetch initial states: %s", (response or {}).get("error"))
            return
        count = 0
        for entity in response.get("result", []):
            entity_id, power = parse_initial_state(entity)
            if entity_id not in self.channel_map:
                continue
            if entity_id in event_updates:
                event_time = event_updates[entity_id]
                snapshot_time = _state_updated_at(entity)
                # Interleaved events have already been applied. Replace only
                # when HA explicitly identifies this snapshot as newer.
                if event_time is None or snapshot_time is None or event_time >= snapshot_time:
                    continue
            self.channel_map[entity_id].update_power(power)
            count += 1
        logger.info("Loaded initial state for %d entities", count)

    def set_connected(self, connected):
        for service in self.channel_map.values():
            service.set_connected(connected)

    async def listen(self):
        try:
            async for message in self.websocket:
                await self.handle_message(message)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Home Assistant WebSocket connection closed")
        finally:
            self.set_connected(False)

    async def handle_message(self, message):
        try:
            entity_id, power = parse_ha_state_change(message)
            if entity_id is None:
                return
            service = self.channel_map.get(entity_id)
            if service is None:
                return
            service.update_power(power)
            logger.debug("Updated %s to %s W", entity_id, power)
        except json.JSONDecodeError:
            logger.exception("Invalid JSON received: %s", message[:200])
        except Exception:  # keep the listener alive
            logger.exception("Error processing message")

    async def disconnect(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None


def load_config(path):
    with open(path) as f:
        return json.load(f)


async def run_websocket_client(ws_client):
    """Reconnect after network failures without restarting the D-Bus services."""
    delay = 1  # Start with 1 second
    max_delay = 60  # Maximum delay of 60 seconds
    while True:
        try:
            # Bound authentication/subscription too, not just the TCP open.
            await asyncio.wait_for(ws_client.connect(), timeout=30)
            await ws_client.listen()
            # If we get here, the connection was successful and we reset the delay
            delay = 1
        except (
            OSError,
            TimeoutError,
            RuntimeError,
            json.JSONDecodeError,
            websockets.exceptions.WebSocketException,
        ) as exc:
            logger.warning("Home Assistant unavailable: %s; retrying in %s s", exc, delay)
        finally:
            ws_client.set_connected(False)
            await ws_client.disconnect()
        # Wait for the delay period before retrying, with jitter to avoid thundering herd
        jitter = delay * 0.1 * (secrets.randbelow(1_000_000) / 1_000_000)  # 10% jitter
        await asyncio.sleep(delay + jitter)
        delay = min(delay * 2, max_delay)  # Exponential backoff


async def main():
    config_path = os.path.join(_here, "config.json")
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        logger.exception("Configuration file %s not found", config_path)
        return
    except json.JSONDecodeError:
        logger.exception("Invalid JSON in %s", config_path)
        return

    logger.setLevel(str(config.get("log_level", DEFAULT_CONFIG["log_level"])).upper())

    ha_url = config.get("ha_url", DEFAULT_CONFIG["ha_url"])
    ha_token = config.get("ha_token", DEFAULT_CONFIG["ha_token"])
    channels_config = config.get("channels", DEFAULT_CONFIG["channels"])

    if not ha_token or ha_token == "YOUR_LONG_LIVED_ACCESS_TOKEN":
        logger.error("Please set a valid long-lived access token in config.json")
        return

    if not channels_config:
        logger.error("No channels configured")
        return

    services = {}
    for chan in channels_config:
        entity_id = chan.get("ha_entity_id")
        service_name = chan.get("service_name")
        instance = chan.get("instance")
        custom_name = chan.get("custom_name")
        position = chan.get("position", 0)

        if not all([entity_id, service_name, instance is not None, custom_name]):
            logger.error("Invalid channel configuration: %s", chan)
            continue

        # One message bus per service: every com.victronenergy.* service
        # exports the BusItem interface at "/", so sharing a single bus
        # between services raises "already exported on this bus".
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        service = AcLoadService(bus, service_name, instance, custom_name, position)
        try:
            await service.register()
        except Exception:  # a broken channel must not kill startup
            logger.exception("Failed to register service %s", service_name)
            await service.close()
            continue
        services[entity_id] = service
        logger.info(
            "Registered %s for entity %s (instance %d)",
            service_name,
            entity_id,
            instance,
        )

    if not services:
        logger.error("No services could be registered")
        return

    ws_client = HaWebSocketClient(ha_url, ha_token, services)

    async def heartbeat_task():
        while True:
            try:
                await asyncio.to_thread(write_heartbeat)
            except OSError:
                logger.exception("Failed to write heartbeat file")
            await asyncio.sleep(5)  # Update every 5 seconds

    async def shutdown():
        logger.info("Shutting down...")
        await ws_client.disconnect()
        for service in services.values():
            await service.close()
        # Disconnect the shared bus
        bus.disconnect()
        sys.exit(0)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            pass

    await asyncio.gather(run_websocket_client(ws_client), heartbeat_task())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")

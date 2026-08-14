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

import websockets
from dbus_fast import BusType
from dbus_fast.aio.message_bus import MessageBus

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

from aiovelib.service import DoubleItem, IntegerItem, Service, TextItem

PRODUCT_ID = 0xFFFF

DEFAULT_CONFIG = {
    "ha_url": "ws://192.168.1.50:8123/api/websocket",
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
        self._service.add_item(IntegerItem("/Connected", 0))
        self._service.add_item(IntegerItem("/Status", 1))
        self._service.add_item(IntegerItem("/IsGenericEnergyMeter", 1))
        self._service.add_item(DoubleItem("/Ac/Power", 0.0))
        self._service.add_item(DoubleItem("/Ac/L1/Power", 0.0))
        self._service.add_item(DoubleItem("/Ac/Energy/Forward", 0.0))

    @property
    def name(self):
        return self._service.name

    async def register(self):
        await self._service.register()

    async def close(self):
        await self._service.close()
        self._bus.disconnect()

    def update_power(self, power):
        with self._service as s:
            s["/Ac/Power"] = power
            s["/Ac/L1/Power"] = power
            s["/Connected"] = 1
            s["/Status"] = 0

    def set_connected(self, connected):
        with self._service as s:
            s["/Connected"] = 1 if connected else 0
            s["/Status"] = 0 if connected else 1


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

        await self.websocket.send(
            json.dumps({"type": "auth", "access_token": self.token})
        )
        auth_resp = json.loads(await self.websocket.recv())
        if auth_resp.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant authentication failed: {auth_resp}")

        logger.info("Authenticated with Home Assistant")
        await self.subscribe_triggers()
        await self.fetch_initial_states()
        self.set_connected(True)
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
        response = json.loads(await self.websocket.recv())
        if response.get("success") is not True:
            logger.warning("Could not fetch initial states: %s", response.get("error"))
            return
        count = 0
        for entity in response.get("result", []):
            entity_id = entity.get("entity_id")
            if entity_id not in self.channel_map:
                continue
            state = entity.get("state")
            try:
                power = float(state) if state not in (None, "", "unavailable", "unknown") else 0.0
            except (TypeError, ValueError):
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
            data = json.loads(message)
            if data.get("type") != "event":
                return
            variables = data.get("event", {}).get("variables", {})
            trigger = variables.get("trigger", {})
            entity_id = trigger.get("entity_id")
            state = (trigger.get("to_state") or {}).get("state")

            service = self.channel_map.get(entity_id)
            if service is None:
                return

            try:
                power = float(state) if state not in (None, "", "unavailable", "unknown") else 0.0
            except (TypeError, ValueError):
                logger.warning("Could not convert state %r to float for %s", state, entity_id)
                return

            service.update_power(power)
            logger.debug("Updated %s to %.1f W", entity_id, power)
        except json.JSONDecodeError:
            logger.error("Invalid JSON received: %s", message[:200])
        except Exception as e:  # noqa: BLE001 - keep the listener alive
            logger.error("Error processing message: %s", e)

    async def disconnect(self):
        if self.websocket:
            await self.websocket.close()
            self.websocket = None


def load_config(path):
    with open(path) as f:
        return json.load(f)


async def main():
    config_path = os.path.join(_here, "config.json")
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        logger.error("Configuration file %s not found", config_path)
        return
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in %s: %s", config_path, e)
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

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        service = AcLoadService(bus, service_name, instance, custom_name, position)
        try:
            await service.register()
        except Exception as e:  # noqa: BLE001 - a broken channel must not kill startup
            logger.error("Failed to register service %s: %s", service_name, e)
            bus.disconnect()
            continue
        services[entity_id] = service
        logger.info("Registered %s for entity %s (instance %d)", service_name, entity_id, instance)

    if not services:
        logger.error("No services could be registered")
        return

    ws_client = HaWebSocketClient(ha_url, ha_token, services)

    async def websocket_task():
        while True:
            try:
                await ws_client.connect()
                await ws_client.listen()
            except (RuntimeError, websockets.exceptions.WebSocketException) as e:
                logger.error("WebSocket error: %s: %s", type(e).__name__, e)
            finally:
                ws_client.set_connected(False)
                await ws_client.disconnect()
            await asyncio.sleep(5)

    async def shutdown():
        logger.info("Shutting down...")
        await ws_client.disconnect()
        for service in services.values():
            await service.close()
        sys.exit(0)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            pass

    await asyncio.gather(websocket_task())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")

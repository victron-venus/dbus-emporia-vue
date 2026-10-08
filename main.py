#!/usr/bin/env python3
"""Expose Emporia power and energy from the configured source on D-Bus."""

import asyncio
import contextlib
import json
import logging
import math
import os
import signal
import sys
import threading
from concurrent.futures import Future
from urllib.parse import quote, urlsplit, urlunsplit

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

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

from parse_ha import parse_initial_state, parse_source_timestamp, parse_submeter_state
from sources import ENERGY_PATHS, EmporiaChannel, channel_id, emporia_config

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

from aiovelib.service import (  # noqa: E402
    DoubleItem,
    IntegerItem,
    Service,
    TextArrayItem,
    TextItem,
)

# Shared protocol identifiers keep publication and update paths consistent.
DBUS_POWER_PATH = "/Ac/Power"
DBUS_L1_POWER_PATH = "/Ac/L1/Power"
DBUS_LAST_UPDATE_PATH = "/LastUpdate"


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

DEFAULT_CONFIG: dict[str, object] = {
    # User-overridable Home Assistant LAN example, including its placeholder IP.
    "ha_url": "ws://192.168.1.50:8123/api/websocket",  # NOSONAR(S5332, S1313)
    "ha_token": "",
    "channels": [],
    "log_level": "INFO",
    "submeter": None,
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
    """Order startup overlap by source reports, including unchanged readings."""
    return parse_source_timestamp(state) if isinstance(state, dict) else None


def read_version():
    try:
        with open(os.path.join(_here, "version")) as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


VERSION = read_version()


class AcLoadService:
    """A com.victronenergy.acload.* service backed by an aiovelib Service."""

    def __init__(self, bus, service_name, instance, custom_name, position, submeter=None):
        self._bus = bus
        self.submeter = submeter
        self._source_time = None
        self._source_deadline = None
        self._fresh_until = 0.0
        self._ha_stale_after = submeter["stale_after_seconds"] if submeter else None
        self._has_last_update = bool(submeter)
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
        self._service.add_item(DoubleItem(DBUS_POWER_PATH, None))
        self._service.add_item(DoubleItem(DBUS_L1_POWER_PATH, None))
        self._service.add_item(DoubleItem("/Ac/Energy/Forward", None))
        if submeter:
            # Match Victron's AC energy-meter profile. Selection as the
            # controller's backup remains separate and explicit.
            self._service.add_item(TextItem("/Role", "acload"))
            self._service.add_item(TextArrayItem("/AllowedRoles", ["acload"]))
            self._service.add_item(TextItem("/Serial", f"emporia:{submeter['channel']}"))
            self._service.add_item(IntegerItem("/NrOfPhases", 1))
            self._service.add_item(IntegerItem("/RefreshTime", 5000))
            self._service.add_item(DoubleItem(DBUS_LAST_UPDATE_PATH, None))
            self._service.add_item(TextItem("/Source/EntityId", submeter["channel"]))

    @property
    def name(self):
        return self._service.name

    async def register(self):
        await self._service.register()

    async def close(self):
        try:
            await self._service.close()
        finally:
            # Each service owns its connection, including failed name release.
            self._bus.disconnect()
            # Retrieve transport failures even when the observer was cancelled
            # during shutdown. Do not cancel dbus-fast's shared disconnect future.
            with contextlib.suppress(EOFError, OSError, TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._bus.wait_for_disconnect()), timeout=1)

    def update_power(self, power):
        with self._service as s:
            s[DBUS_POWER_PATH] = power
            s[DBUS_L1_POWER_PATH] = power
            s[PATH_CONNECTED] = 1 if power is not None else 0
            s[PATH_STATUS] = 0 if power is not None else 1

    def configure_emporia(self, channel, poll_interval=3):
        self._direct_refresh_ms = int(poll_interval * 1000)
        self._service.add_item(TextItem("/Source/Type", "unavailable"))
        self._service.add_item(TextItem("/Emporia/DeviceId", str(channel["emporia_device_gid"])))
        self._service.add_item(TextItem("/Emporia/Channel", channel["emporia_channel"]))
        if not self.submeter:
            self._service.add_item(DoubleItem(DBUS_LAST_UPDATE_PATH, None))
        self._has_last_update = True
        self.energy_fields = ["energy_day", "energy_month"]
        for direction in ("import", "export"):
            if channel.get(f"emporia_{direction}_channel"):
                self.energy_fields.extend(
                    f"energy_{direction}_{period}" for period in ("day", "month")
                )
        for field in self.energy_fields:
            period = ENERGY_PATHS[field]
            self._service.add_item(DoubleItem(f"/Emporia/Energy/{period}", None))
            self._service.add_item(DoubleItem(f"/Emporia/Energy/{period}Updated", None))
            self._service.add_item(
                TextItem(f"/Emporia/Energy/{period}Sample", '{"value":null,"timestamp":null}')
            )

    def publish_measurement(self, sample, source):
        with self._service as s:
            s[DBUS_POWER_PATH] = sample.power if sample else None
            s[DBUS_L1_POWER_PATH] = sample.power if sample else None
            s[DBUS_LAST_UPDATE_PATH] = sample.timestamp if sample else None
            s["/Source/Type"] = source
            s["/Mgmt/Connection"] = {
                "emporia": "Emporia API",
                "unavailable": "Unavailable",
            }[source]
            if self.submeter:
                s["/RefreshTime"] = self._direct_refresh_ms
            s[PATH_CONNECTED] = 1 if sample else 0
            s[PATH_STATUS] = 0 if sample else 1

    def publish_energy(self, field, value, timestamp):
        period = ENERGY_PATHS[field]
        with self._service as s:
            s[f"/Emporia/Energy/{period}"] = value
            s[f"/Emporia/Energy/{period}Updated"] = timestamp
            # Keep energy and its source timestamp atomic for MQTT consumers.
            s[f"/Emporia/Energy/{period}Sample"] = json.dumps(
                {"value": value, "timestamp": timestamp}, separators=(",", ":")
            )

    def configure_ha(self, stale_after_seconds):
        """Apply freshness to HA channels without affecting direct-mode clocks."""
        if not self.submeter:
            self._ha_stale_after = stale_after_seconds
        if not self._has_last_update:
            self._service.add_item(DoubleItem(DBUS_LAST_UPDATE_PATH, None))
            self._has_last_update = True

    def needs_revalidation(self):
        """Changed source reports refresh themselves; poll quiet channels early."""
        return self._ha_stale_after is not None and (
            self._fresh_until - time.monotonic() <= self._ha_stale_after / 2
        )

    def set_connected(self, connected):
        if not connected:
            self.invalidate()
            return
        with self._service as s:
            s[PATH_CONNECTED] = 1 if connected else 0
            s[PATH_STATUS] = 0 if connected else 1

    def _entity_sample(self, entity):
        """Read power and its source time using the selected HA meter format."""
        if self.submeter:
            return parse_submeter_state(entity)
        _, power = parse_initial_state(entity)
        return power, parse_source_timestamp(entity)

    def _record_source_time(self, timestamp):
        """Reset the monotonic deadline only when the source timestamp changes."""
        if timestamp != self._source_time:
            self._source_deadline = None
        self._source_time = timestamp

    def update_entity(self, entity):
        """Publish source-fresh HA values and reject older REST/WS snapshots."""
        power, timestamp = self._entity_sample(entity)
        if (
            timestamp is not None
            and self._source_time is not None
            and timestamp < self._source_time
        ):
            return
        age = time.time() - timestamp if timestamp is not None else math.inf
        max_age = self._ha_stale_after
        fresh = max_age is None or -5 <= age <= max_age
        if timestamp is not None and -5 <= age and fresh:
            # Unavailable and invalid-unit events also supersede older polls.
            # Do not let a future-dated payload poison the ordering watermark.
            self._record_source_time(timestamp)
        if power is None or not math.isfinite(power) or not fresh:
            self.invalidate()
            return
        if max_age is not None:
            now = time.monotonic()
            deadline = now + max_age - max(0, age)
            if self._source_deadline is not None:
                deadline = min(deadline, self._source_deadline)
            self._fresh_until = self._source_deadline = deadline
            if deadline <= now:
                self.invalidate()
                return
        with self._service as s:
            s[DBUS_POWER_PATH] = power
            # Victron's AC-load meter profile needs a phase power. Home is an
            # aggregate source, so its signed total is represented on L1 too.
            s[DBUS_L1_POWER_PATH] = power
            if self._has_last_update:
                s[DBUS_LAST_UPDATE_PATH] = timestamp
            s[PATH_CONNECTED] = 1
            s[PATH_STATUS] = 0

    def invalidate(self):
        self._fresh_until = 0.0
        with self._service as s:
            s[DBUS_POWER_PATH] = None
            s[DBUS_L1_POWER_PATH] = None
            if self._has_last_update:
                s[DBUS_LAST_UPDATE_PATH] = None
            s[PATH_CONNECTED] = 0
            s[PATH_STATUS] = 1

    def expire(self):
        if self._ha_stale_after is not None and time.monotonic() >= self._fresh_until:
            self.invalidate()


class HaWebSocketClient:
    """Handle the WebSocket connection to Home Assistant."""

    def __init__(self, url, token, channel_map, stale_after_seconds=30, request_timeout_seconds=10):
        self.url = url
        self.token = token
        self.channel_map = channel_map
        self.websocket = None
        self._message_id = 1
        self.request_timeout = request_timeout_seconds
        self._event_revisions = dict.fromkeys(channel_map, 0)
        self._rest_after = dict.fromkeys(channel_map, 0.0)
        self._rest_lock = threading.Lock()
        self._rest_request_lock = asyncio.Lock()
        self._rest_session = None
        self._rest_future: Future | None = None
        self._rest_waiter = None
        self._rest_closed = False
        parts = urlsplit(url)
        if parts.scheme not in {"ws", "wss"}:
            raise ValueError("ha_url must use ws:// or wss://")
        path = parts.path.rstrip("/").removesuffix("/websocket") or "/api"
        self._rest_url = urlunsplit(
            ("https" if parts.scheme == "wss" else "http", parts.netloc, path, "", "")
        )
        for service in channel_map.values():
            service.configure_ha(stale_after_seconds)

    async def connect(self):
        with self._rest_lock:
            self._rest_closed = False
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
        async with asyncio.timeout(20):
            while True:
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
        count = self._apply_initial_states(response.get("result", []), event_updates)
        logger.info("Loaded initial state for %d entities", count)

    def _apply_initial_states(self, entities, event_updates):
        """Apply snapshots only when they supersede interleaved trigger events."""
        count = 0
        for entity in entities:
            entity_id = entity.get("entity_id")
            if entity_id not in self.channel_map:
                continue
            if entity_id in event_updates:
                event_time = event_updates[entity_id]
                snapshot_time = _state_updated_at(entity)
                # Interleaved events have already been applied. Replace only
                # when HA explicitly identifies this snapshot as newer.
                if event_time is None or snapshot_time is None or event_time >= snapshot_time:
                    continue
            self.channel_map[entity_id].update_entity(entity)
            count += 1
        return count

    def set_connected(self, connected):
        for service in self.channel_map.values():
            service.set_connected(connected)

    async def listen(self):
        refresh = asyncio.create_task(self.refresh_channels())
        try:
            async for message in self.websocket:
                await self.handle_message(message)
        except ConnectionClosed:
            logger.warning("Home Assistant WebSocket connection closed")
        finally:
            refresh.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresh
            self.set_connected(False)

    def _read_entity(self, entity_id, future):
        """One daemon request at a time, using a reusable HTTP connection pool."""
        import requests

        entity = None
        try:
            with self._rest_lock:
                if self._rest_closed:
                    return
                if self._rest_session is None:
                    self._rest_session = requests.Session()
                    self._rest_session.headers["Authorization"] = f"Bearer {self.token}"
                session = self._rest_session
            url = f"{self._rest_url}/states/{quote(entity_id, safe='')}"
            with session.get(
                url,
                timeout=(self.request_timeout, self.request_timeout),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise ValueError(f"HA state request returned HTTP {response.status_code}")
                chunks = []
                size = 0
                for chunk in response.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > 262144:
                        raise ValueError("HA entity state exceeded 256 KiB")
                    chunks.append(chunk)
                entity = json.loads(b"".join(chunks))
                if not isinstance(entity, dict) or entity.get("entity_id") != entity_id:
                    raise ValueError("HA returned an unexpected entity state")
        except (OSError, ValueError) as exc:
            logger.warning("Could not revalidate HA entity %s: %s", entity_id, exc)
            entity = None
        finally:
            with self._rest_lock:
                if self._rest_closed and self._rest_session is not None:
                    self._rest_session.close()
                    self._rest_session = None
                # Publish completion under the same lock as session cleanup so
                # disconnect cannot miss both an active and a completed request.
                # Completion never touches D-Bus; only a live consumer may do so.
                future.set_result(entity)

    async def fetch_entity(self, entity_id):
        """Cancellation retains the sole in-flight request across reconnects."""
        async with self._rest_request_lock:
            if self._rest_future is not None:
                # A cancelled prior connection may still have a blocking request.
                # Drain and discard it before allowing another thread/request.
                await asyncio.shield(self._rest_waiter)
            if self._rest_closed:
                return None
            self._rest_future = Future()
            self._rest_waiter = asyncio.wrap_future(self._rest_future)
            threading.Thread(
                target=self._read_entity,
                args=(entity_id, self._rest_future),
                name="ha-state-refresh",
                daemon=True,
            ).start()
            entity = await asyncio.shield(self._rest_waiter)
            self._rest_future = None
            self._rest_waiter = None
            return entity

    async def refresh_channels(self):
        """Revalidate quiet channels; changing source reports need no HTTP poll."""
        while True:
            await asyncio.sleep(5)
            selected = [(key, s) for key, s in self.channel_map.items() if s.submeter]
            ordinary = [(key, s) for key, s in self.channel_map.items() if not s.submeter]
            for entity_id, service in selected:
                await self.revalidate_channel(entity_id, service)
            for entity_id, service in ordinary:
                # A slow ordinary request must not defer the selected meter
                # behind every remaining channel in the sweep.
                for selected_id, selected_service in selected:
                    await self.revalidate_channel(selected_id, selected_service)
                await self.revalidate_channel(entity_id, service)

    async def revalidate_channel(self, entity_id, service):
        """Recheck source freshness after intervening events and bound retries."""
        if not service.needs_revalidation() or time.monotonic() < self._rest_after[entity_id]:
            return
        revision = self._event_revisions[entity_id]
        entity = await self.fetch_entity(entity_id)
        self._rest_after[entity_id] = time.monotonic() + 5
        if not self._rest_closed and revision == self._event_revisions[entity_id]:
            service.update_entity(entity or {})

    async def handle_message(self, message):
        try:
            data = json.loads(message)
            if data.get("type") != "event":
                return
            trigger = data.get("event", {}).get("variables", {}).get("trigger", {})
            entity_id = trigger.get("entity_id")
            service = self.channel_map.get(entity_id)
            if service is None:
                return
            self._event_revisions[entity_id] += 1
            entity = trigger.get("to_state")
            service.update_entity(entity or {})
            logger.debug("Updated %s", entity_id)
        except json.JSONDecodeError:
            logger.exception("Invalid JSON received: %s", message[:200])
        except Exception:  # keep the listener alive
            logger.exception("Error processing message")

    async def disconnect(self):
        with self._rest_lock:
            self._rest_closed = True
            if self._rest_session is not None and (
                self._rest_future is None or self._rest_future.done()
            ):
                self._rest_session.close()
                self._rest_session = None
        websocket, self.websocket = self.websocket, None
        if websocket:
            await asyncio.wait_for(websocket.close(), timeout=5)


def load_config(path):
    with open(path) as f:
        return json.load(f)


def ha_settings(config):
    """Validate HA freshness separately from direct Emporia configuration."""
    age = config.get("ha_stale_after_seconds", 30)
    timeout = config.get("ha_request_timeout_seconds", 10)
    for name, value, minimum, maximum in (
        ("ha_stale_after_seconds", age, 10, math.inf),
        ("ha_request_timeout_seconds", timeout, 1, 30),
    ):
        if name == "ha_stale_after_seconds" and value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ValueError(f"{name} must be a finite number between {minimum} and {maximum}")
    return {"stale_after_seconds": age, "request_timeout_seconds": timeout}


def selected_submeter(config):
    """Optional selection from configured channels; no site names in code."""
    selection = config.get("submeter")
    if selection is None:
        return None
    if not isinstance(selection, dict):
        raise ValueError("submeter must be null or an object with channel")
    channel = selection.get("channel")
    matches = [
        c for c in config.get("channels", []) if isinstance(c, dict) and channel_id(c) == channel
    ]
    if not isinstance(channel, str) or len(matches) != 1:
        raise ValueError("submeter.channel must identify exactly one configured channel")
    if not matches[0].get("service_name", "").startswith("com.victronenergy.acload."):
        raise ValueError("submeter channel must use a com.victronenergy.acload service")
    age = selection.get("stale_after_seconds", 30)
    if (
        isinstance(age, bool)
        or not isinstance(age, (int, float))
        or not math.isfinite(age)
        or age < 10
    ):
        raise ValueError("submeter.stale_after_seconds must be a finite number >= 10")
    return {"channel": channel, "stale_after_seconds": float(age)}


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
            RuntimeError,
            json.JSONDecodeError,
            WebSocketException,
        ) as exc:
            logger.warning("Home Assistant unavailable: %s; retrying in %s s", exc, delay)
        finally:
            ws_client.set_connected(False)
            try:
                await ws_client.disconnect()
            except (OSError, RuntimeError, WebSocketException):
                logger.exception("Failed to close Home Assistant connection")
        # Wait for the delay period before retrying, with jitter to avoid thundering herd
        jitter = delay * 0.1 * (secrets.randbelow(1_000_000) / 1_000_000)  # 10% jitter
        await asyncio.sleep(delay + jitter)
        delay = min(delay * 2, max_delay)  # Exponential backoff


async def monitor_service_bus(service):
    """Stop the worker when a published service loses its D-Bus connection."""
    try:
        # dbus-fast directly awaits a shared future; shielding keeps normal
        # task cancellation from cancelling the transport's completion signal.
        await asyncio.shield(service._bus.wait_for_disconnect())
    except Exception as exc:
        raise ConnectionError(f"D-Bus connection lost for {service.name}") from exc
    raise ConnectionError(f"D-Bus connection lost for {service.name}")


async def close_unowned_bus(bus):
    """Close a bus whose connection or service construction did not finish."""
    bus.disconnect()
    with contextlib.suppress(EOFError, OSError, TimeoutError):
        # No service or observer owns this future, so a timeout may cancel it.
        await asyncio.wait_for(bus.wait_for_disconnect(), timeout=1)


async def close_dbus_resources(services, buses):
    """Release completed and partially constructed services within one deadline."""
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(service.close() for service in services),
                *(close_unowned_bus(bus) for bus in buses),
                return_exceptions=True,
            ),
            timeout=5,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error("Failed to release D-Bus service: %s", result)
    except TimeoutError:
        logger.exception("Timed out releasing D-Bus services")


def refresh_channel_freshness(direct_channels, services):
    if direct_channels:
        for channel in direct_channels.values():
            channel.refresh()
    else:
        for service in services.values():
            service.expire()


async def heartbeat_task(direct_channels, services):
    while True:
        try:
            await asyncio.to_thread(write_heartbeat)
        except OSError:
            logger.exception("Failed to write heartbeat file")
        for _ in range(5):
            refresh_channel_freshness(direct_channels, services)
            await asyncio.sleep(1)


async def connect_service_bus(service_name, unowned_buses):
    """Retain a failed connection until cleanup finishes, without stopping later channels."""
    bus = MessageBus(bus_type=BusType.SYSTEM)
    unowned_buses.append(bus)
    try:
        connected = await bus.connect()
    except Exception:
        logger.exception("Failed to connect D-Bus service %s", service_name)
        try:
            await close_unowned_bus(bus)
        except Exception:
            # The outer owner must retry a failed cleanup during shutdown.
            logger.exception("Failed to close D-Bus connection for %s", service_name)
        else:
            unowned_buses.remove(bus)
        return None
    unowned_buses[-1] = connected
    return connected


def channel_registration_settings(chan, direct):
    """Read required channel fields only after checking the configured entry type."""
    if not isinstance(chan, dict):
        return None
    entity_id = channel_id(chan) if direct else chan.get("ha_entity_id")
    service_name = chan.get("service_name")
    instance = chan.get("instance")
    custom_name = chan.get("custom_name")
    position = chan.get("position", 0)
    if not all([entity_id, service_name, instance is not None, custom_name]):
        return None
    return entity_id, service_name, instance, custom_name, position


async def register_services(channels_config, direct, submeter, allocated_services, unowned_buses):
    """Register channels while the caller retains ownership of every allocated bus."""
    services = {}
    for chan in channels_config:
        settings = channel_registration_settings(chan, direct)
        if settings is None:
            logger.error("Invalid channel configuration: %s", chan)
            continue
        entity_id, service_name, instance, custom_name, position = settings

        # One message bus per service: every com.victronenergy.* service
        # exports the BusItem interface at "/", so sharing a single bus
        # between services raises "already exported on this bus".
        bus = await connect_service_bus(service_name, unowned_buses)
        if bus is None:
            continue
        selection = submeter if submeter and submeter["channel"] == channel_id(chan) else None
        service = AcLoadService(bus, service_name, instance, custom_name, position, selection)
        allocated_services.append(service)
        unowned_buses.pop()
        if direct:
            service.configure_emporia(chan, direct["poll_interval_seconds"])
        try:
            await service.register()
        except Exception:  # a broken channel must not kill startup
            logger.exception("Failed to register service %s", service_name)
            allocated_services.remove(service)
            await close_dbus_resources([service], [])
            continue
        services[entity_id] = service
        logger.info(
            "Registered %s for entity %s (instance %d)",
            service_name,
            entity_id,
            instance,
        )

    return services


def publish_channel_energy(direct_channels, measurements):
    """Deliver each available energy field in its existing source order."""
    for identity, reading in measurements.items():
        if identity in direct_channels:
            for field in ENERGY_PATHS:
                if field in reading:
                    direct_channels[identity].update_energy(
                        field,
                        reading[field],
                        reading.get("timestamp"),
                    )


def create_emporia_client(direct, channels_config, services, submeter, direct_channels):
    """Bind source callbacks to the same service and channel mappings."""
    from emporia import EmporiaClient

    for key in ("token_file", "credentials_file"):
        if key in direct:
            direct[key] = str(Path(_here) / direct[key])
    active_channels = [
        {**c, "id": channel_id(c)} for c in channels_config if channel_id(c) in services
    ]
    for channel in active_channels:
        identity = channel["id"]
        selected_age = (
            submeter["stale_after_seconds"]
            if submeter and submeter["channel"] == identity
            else None
        )
        direct_channels[identity] = EmporiaChannel(
            services[identity],
            direct,
            selected_age,
            services[identity].energy_fields,
        )

    def publish_power(measurements):
        for identity, sample in measurements.items():
            if identity in direct_channels:
                direct_channels[identity].update(sample)

    def cloud_unavailable():
        for channel in direct_channels.values():
            channel.unavailable()

    def publish_energy(measurements):
        publish_channel_energy(direct_channels, measurements)

    cloud_client = EmporiaClient(
        direct,
        active_channels,
        publish_power,
        cloud_unavailable,
        publish_energy=publish_energy,
    )

    return cloud_client


def install_shutdown_signals(loop, request_shutdown, installed_signals):
    """Record only successfully installed signal handlers for later removal."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
            installed_signals.append(sig)
        except NotImplementedError:
            pass


async def run_service_workers(direct_channels, services, ws_client, cloud_client):
    """Run and drain workers in the caller task before releasing D-Bus resources."""
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    stopping = False

    def request_shutdown():
        nonlocal stopping
        if not stopping:
            stopping = True
            logger.info("Shutting down...")
            if main_task is not None:
                main_task.cancel()

    installed_signals = []
    tasks = []
    try:
        install_shutdown_signals(loop, request_shutdown, installed_signals)

        tasks.append(asyncio.create_task(heartbeat_task(direct_channels, services)))
        tasks.extend(
            asyncio.create_task(monitor_service_bus(service)) for service in services.values()
        )
        if ws_client:
            tasks.insert(0, asyncio.create_task(run_websocket_client(ws_client)))
        if cloud_client:
            tasks.append(asyncio.create_task(cloud_client.run()))
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        if not stopping:
            raise
    finally:
        # Stop and retrieve workers before releasing their D-Bus resources.
        for task in tasks:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        except TimeoutError:
            logger.exception("Timed out stopping background tasks")
        finally:
            try:
                if ws_client:
                    await asyncio.wait_for(ws_client.disconnect(), timeout=5)
            except Exception:  # cleanup must continue even after an unexpected close failure
                logger.exception("Failed to close Home Assistant connection")
            finally:
                for sig in installed_signals:
                    loop.remove_signal_handler(sig)


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
    logging.getLogger("emporia").setLevel(logger.level)

    ha_url = config.get("ha_url", DEFAULT_CONFIG["ha_url"])
    ha_token = config.get("ha_token", DEFAULT_CONFIG["ha_token"])
    channels_config = config.get("channels", DEFAULT_CONFIG["channels"])
    try:
        submeter = selected_submeter(config)
        direct = emporia_config(config)
        ha_policy = ha_settings(config) if not direct else {}
    except ValueError as exc:
        logger.error("Invalid source configuration: %s", exc)
        return

    if not direct and (not ha_token or ha_token == "YOUR_LONG_LIVED_ACCESS_TOKEN"):
        logger.error("Please set a valid long-lived access token in config.json")
        return

    if not channels_config:
        logger.error("No channels configured")
        return

    allocated_services = []
    unowned_buses = []
    async with contextlib.AsyncExitStack() as resources:
        # Own every connection from allocation onward, including startup failures
        # before the worker tasks and their shutdown handlers exist.
        resources.push_async_callback(close_dbus_resources, allocated_services, unowned_buses)
        services = await register_services(
            channels_config, direct, submeter, allocated_services, unowned_buses
        )

        if not services:
            logger.error("No services could be registered")
            return

        direct_channels = {}
        ws_client = None
        cloud_client = None
        if direct:
            cloud_client = create_emporia_client(
                direct, channels_config, services, submeter, direct_channels
            )
        else:
            ws_client = HaWebSocketClient(ha_url, ha_token, services, **ha_policy)

        await run_service_workers(direct_channels, services, ws_client, cloud_client)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")

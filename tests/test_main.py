"""Tests for main.py orchestration — aiovelib + websockets + heartbeat are mocked."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import types
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level fixtures: stub aiovelib + dbus_fast before main.py imports
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_aiovelib():
    """Inject fake aiovelib + dbus_fast into sys.modules so main.py imports succeed."""
    # Fake dbus_fast
    dbus_fast = types.ModuleType("dbus_fast")
    dbus_fast.BusType = MagicMock(SYSTEM=1)
    msg_bus_mod = types.ModuleType("dbus_fast.aio")
    msg_bus_mod2 = types.ModuleType("dbus_fast.aio.message_bus")
    msg_bus_mod2.MessageBus = MagicMock()
    sys.modules["dbus_fast"] = dbus_fast
    sys.modules["dbus_fast.aio"] = msg_bus_mod
    sys.modules["dbus_fast.aio.message_bus"] = msg_bus_mod2

    # Fake aiovelib.service
    svc_mod = types.ModuleType("aiovelib.service")

    class _FakeItem:
        def __init__(self, *a, **kw):
            self.args = a
            self.kwargs = kw

    class FakeService:
        def __init__(self, bus, name):
            self.bus = bus
            self.name = name
            self.items = {}

        def add_item(self, item):
            self.items[item.args[0]] = item.args[1]

        async def register(self):
            pass

        async def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __setitem__(self, key, value):
            self.items[key] = value

        def __getitem__(self, key):
            return self.items[key]

    svc_mod.Service = FakeService
    svc_mod.DoubleItem = _FakeItem
    svc_mod.IntegerItem = _FakeItem
    svc_mod.TextItem = _FakeItem
    svc_mod.TextArrayItem = _FakeItem

    # Place under the project-local aiovelib/ dir
    proj_aiovelib = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aiovelib")
    aiovelib_pkg = types.ModuleType("aiovelib")
    aiovelib_pkg.__path__ = [proj_aiovelib]
    sys.modules["aiovelib"] = aiovelib_pkg
    sys.modules["aiovelib.service"] = svc_mod

    # Now safe to import main
    if "main" in sys.modules:
        del sys.modules["main"]


def _patch_websockets(monkeypatch):
    """Replace `main.websockets` with a fake module exposing the attributes main uses."""
    fake = types.ModuleType("fake_websockets")
    fake.connect = MagicMock()
    fake.exceptions = types.SimpleNamespace(
        WebSocketException=type("WebSocketException", (Exception,), {}),
        ConnectionClosed=type("ConnectionClosed", (Exception,), {}),
    )
    monkeypatch.setattr("main.websockets", fake)
    return fake


# ---------------------------------------------------------------------------
# AcLoadService
# ---------------------------------------------------------------------------


class TestAcLoadService:
    def _make(self, **kw):
        from main import AcLoadService

        bus = MagicMock()
        defaults = dict(
            bus=bus,
            service_name="com.victronenergy.acload.test",
            instance=71,
            custom_name="Test Load",
            position=0,
        )
        defaults.update(kw)
        return AcLoadService(**defaults)

    def test_name_property_returns_service_name(self):
        svc = self._make(service_name="com.victronenergy.acload.x")
        assert svc.name == "com.victronenergy.acload.x"

    def test_update_power_sets_values_and_connected(self):
        svc = self._make()
        svc.update_power(123.4)
        assert svc._service["/Ac/Power"] == 123.4
        assert svc._service["/Ac/L1/Power"] == 123.4
        assert svc._service["/Connected"] == 1
        assert svc._service["/Status"] == 0

    @pytest.mark.parametrize("directions", [(), ("import",), ("export",), ("import", "export")])
    def test_energy_samples_exist_only_for_configured_directions(self, directions):
        svc = self._make()
        channel = {"emporia_device_gid": 1, "emporia_channel": "1"}
        for direction in directions:
            channel[f"emporia_{direction}_channel"] = direction
        svc.configure_emporia(channel)
        expected = {"/Emporia/Energy/DaySample", "/Emporia/Energy/MonthSample"}
        for direction in directions:
            expected.update(
                f"/Emporia/Energy/{direction.title()}/{period}Sample" for period in ("Day", "Month")
            )
        samples = {path for path in svc._service.items if path.endswith("Sample")}
        assert samples == expected
        assert all(svc._service[path] == '{"value":null,"timestamp":null}' for path in samples)

    @pytest.mark.parametrize(
        ("field", "path"),
        [
            ("energy_day", "/Emporia/Energy/Day"),
            ("energy_month", "/Emporia/Energy/Month"),
            ("energy_import_day", "/Emporia/Energy/Import/Day"),
            ("energy_import_month", "/Emporia/Energy/Import/Month"),
            ("energy_export_day", "/Emporia/Energy/Export/Day"),
            ("energy_export_month", "/Emporia/Energy/Export/Month"),
        ],
    )
    def test_energy_sample_preserves_pair_through_reset_clear_and_expiry(
        self, monkeypatch, field, path
    ):
        from sources import EmporiaChannel

        svc = self._make()
        svc.configure_emporia(
            {
                "emporia_device_gid": 1,
                "emporia_channel": "1",
                "emporia_import_channel": "MainsFromGrid",
                "emporia_export_channel": "MainsToGrid",
            }
        )
        clock = {"wall": 1800000000, "monotonic": 100}
        monkeypatch.setattr("sources.time.time", lambda: clock["wall"])
        monkeypatch.setattr("sources.time.monotonic", lambda: clock["monotonic"])
        channel = EmporiaChannel(
            svc,
            {"stale_after_seconds": 30, "day_interval_seconds": 60, "month_interval_seconds": 600},
            energy_fields=svc.energy_fields,
        )

        def assert_pair(value, timestamp):
            sample = svc._service[f"{path}Sample"]
            assert json.loads(sample) == {"value": value, "timestamp": timestamp}
            assert " " not in sample
            assert svc._service[path] == value
            assert svc._service[f"{path}Updated"] == timestamp

        assert_pair(None, None)
        for value in (12.5, 0, None, 3.25):
            clock["wall"] += 1
            clock["monotonic"] += 1
            channel.update_energy(field, value, clock["wall"])
            assert_pair(value, clock["wall"] if value is not None else None)

        clock["monotonic"] += 2000
        channel.refresh()
        assert_pair(None, None)
        assert svc._service["/Ac/Energy/Forward"] is None

    def test_set_connected_true(self):
        svc = self._make()
        svc.set_connected(True)
        assert svc._service["/Connected"] == 1
        assert svc._service["/Status"] == 0

    def test_set_connected_false(self):
        svc = self._make()
        svc.set_connected(False)
        assert svc._service["/Connected"] == 0
        assert svc._service["/Status"] == 1

    def test_register_calls_service_register(self):
        svc = self._make()
        svc._service.register = AsyncMock()
        asyncio.run(svc.register())
        svc._service.register.assert_awaited_once()

    def test_close_disconnects_bus(self):
        from main import AcLoadService

        bus = MagicMock()
        svc = AcLoadService(bus, "com.victronenergy.acload.x", 71, "n", 0)
        svc._service.close = AsyncMock()
        asyncio.run(svc.close())
        bus.disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_reads_json(tmp_path):
    from main import load_config

    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"ha_url": "ws://x", "channels": []}))
    assert load_config(str(p)) == {"ha_url": "ws://x", "channels": []}


# ---------------------------------------------------------------------------
# read_version
# ---------------------------------------------------------------------------


def test_read_version_reads_file(tmp_path, monkeypatch):
    from main import read_version

    p = tmp_path / "version"
    p.write_text("1.2.3\n")
    monkeypatch.setattr("main._here", str(tmp_path))
    assert read_version() == "1.2.3"


def test_read_version_falls_back_when_missing(tmp_path, monkeypatch):
    from main import read_version

    monkeypatch.setattr("main._here", str(tmp_path))
    assert read_version() == "0.0.0"


# ---------------------------------------------------------------------------
# HaWebSocketClient
# ---------------------------------------------------------------------------


class TestHaWebSocketClient:
    def _make(self, **kw):
        from main import HaWebSocketClient

        defaults = dict(
            url="ws://h:8123/api/websocket",
            token="tok",
            channel_map={"sensor.x": MagicMock()},
        )
        defaults.update(kw)
        return HaWebSocketClient(**defaults)

    def test_construct_assigns_fields(self):
        c = self._make()
        assert c.url == "ws://h:8123/api/websocket"
        assert c.token == "tok"
        assert c._message_id == 1

    def test_handle_message_updates_matching_service(self):
        c = self._make(channel_map={"sensor.x": MagicMock()})
        msg = json.dumps(
            {
                "type": "event",
                "event": {
                    "variables": {
                        "trigger": {
                            "entity_id": "sensor.x",
                            "to_state": {"state": "500.0"},
                        }
                    }
                },
            }
        )
        asyncio.run(c.handle_message(msg))
        c.channel_map["sensor.x"].update_entity.assert_called_once_with({"state": "500.0"})

    def test_handle_message_unknown_entity_noop(self):
        svc = MagicMock()
        c = self._make(channel_map={"sensor.x": svc})
        msg = json.dumps(
            {
                "type": "event",
                "event": {
                    "variables": {
                        "trigger": {
                            "entity_id": "sensor.other",
                            "to_state": {"state": "1"},
                        }
                    }
                },
            }
        )
        asyncio.run(c.handle_message(msg))
        svc.update_entity.assert_not_called()

    def test_handle_message_invalid_json_logs_error(self):
        c = self._make()
        # Should not raise
        asyncio.run(c.handle_message("not json {{{"))

    def test_handle_message_non_event_returns(self):
        c = self._make(channel_map={"sensor.x": MagicMock()})
        msg = json.dumps({"type": "result", "result": []})
        asyncio.run(c.handle_message(msg))
        c.channel_map["sensor.x"].update_entity.assert_not_called()

    def test_set_connected_propagates_to_services(self):
        s1, s2 = MagicMock(), MagicMock()
        c = self._make(channel_map={"a": s1, "b": s2})
        c.set_connected(True)
        s1.set_connected.assert_called_once_with(True)
        s2.set_connected.assert_called_once_with(True)

    def test_listen_marks_disconnected_on_close(self):
        c = self._make()

        # An async iterator that raises ConnectionClosed on the first __anext__.
        class _BrokenWS:
            def __aiter__(self):
                return self

            async def __anext__(self):
                from websockets.exceptions import ConnectionClosed  # type: ignore[import-not-found]

                raise ConnectionClosed(None, None)

        c.websocket = _BrokenWS()
        c.set_connected = MagicMock()
        asyncio.run(c.listen())
        c.set_connected.assert_called_with(False)

    def test_disconnect_closes_websocket(self):
        c = self._make()
        ws = AsyncMock()
        c.websocket = ws
        asyncio.run(c.disconnect())
        ws.close.assert_awaited_once()
        assert c.websocket is None


class TestHaWebSocketClientConnect:
    def _ws(self, recv_values):
        """Build a fake websocket whose .recv() yields the given JSON in order."""
        ws = MagicMock()
        ws.close = AsyncMock()
        ws.send = AsyncMock()

        queue = list(recv_values)
        recv_mock = AsyncMock(side_effect=[json.dumps(v) for v in queue])
        ws.recv = recv_mock
        return ws

    def test_connect_auth_flow(self, monkeypatch):
        from main import HaWebSocketClient

        fake_ws = _patch_websockets(monkeypatch)
        svc = MagicMock()
        svc.update_power = MagicMock()
        ws = self._ws(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {"success": True},
                {
                    "id": 2,
                    "success": True,
                    "result": [
                        {"entity_id": "sensor.x", "state": "42.0"},
                    ],
                },
            ]
        )
        fake_ws.connect = AsyncMock(return_value=ws)
        c = HaWebSocketClient("ws://h:8123/api/websocket", "tok", {"sensor.x": svc})

        asyncio.run(c.connect())

        svc.update_entity.assert_called_once_with({"entity_id": "sensor.x", "state": "42.0"})
        # Connection alone must not mark missing or unavailable sensors live.
        svc.set_connected.assert_not_called()

    def test_connect_auth_failure_raises(self, monkeypatch):
        from main import HaWebSocketClient

        fake_ws = _patch_websockets(monkeypatch)
        ws = self._ws(
            [
                {"type": "auth_required"},
                {"type": "auth_invalid", "message": "bad"},
            ]
        )
        fake_ws.connect = AsyncMock(return_value=ws)
        c = HaWebSocketClient("ws://h:8123/api/websocket", "tok", {})
        coro = c.connect()
        with pytest.raises(RuntimeError, match="authentication failed"):
            asyncio.run(coro)

    def test_connect_bad_initial_raises(self, monkeypatch):
        from main import HaWebSocketClient

        fake_ws = _patch_websockets(monkeypatch)
        ws = self._ws([{"type": "other"}])
        fake_ws.connect = AsyncMock(return_value=ws)
        c = HaWebSocketClient("ws://h:8123/api/websocket", "tok", {})
        coro = c.connect()
        with pytest.raises(RuntimeError, match="auth_required"):
            asyncio.run(coro)


# ---------------------------------------------------------------------------
# main() — integration of config loading + service registration
# ---------------------------------------------------------------------------


CHANNELS_CFG = [
    {
        "ha_entity_id": "sensor.a",
        "service_name": "com.victronenergy.acload.a",
        "instance": 71,
        "custom_name": "A",
        "position": 0,
    },
    {
        "ha_entity_id": "sensor.b",
        "service_name": "com.victronenergy.acload.b",
        "instance": 72,
        "custom_name": "B",
        "position": 0,
    },
]


def _write_config(tmp_path, **overrides):
    cfg = {
        "ha_url": "ws://h:8123/api/websocket",
        "ha_token": "tok",
        "channels": CHANNELS_CFG,
        "log_level": "INFO",
    }
    cfg.update(overrides)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return p


def test_main_missing_config_returns(caplog, tmp_path, monkeypatch):
    from main import main

    p = tmp_path / "nope.json"
    with patch("main.os.path.join", return_value=str(p)):
        asyncio.run(main())
    assert "not found" in caplog.text


def test_main_invalid_json_returns(caplog, tmp_path, monkeypatch):
    from main import main

    p = tmp_path / "config.json"
    p.write_text("{ not json")
    with patch("main.os.path.join", return_value=str(p)):
        asyncio.run(main())
    assert "Invalid JSON" in caplog.text


def test_main_placeholder_token_returns(caplog, tmp_path, monkeypatch):
    from main import main

    p = _write_config(tmp_path, ha_token="YOUR_LONG_LIVED_ACCESS_TOKEN")
    with patch("main.os.path.join", return_value=str(p)):
        asyncio.run(main())
    assert "long-lived access token" in caplog.text


def test_main_no_channels_returns(caplog, tmp_path, monkeypatch):
    from main import main

    p = _write_config(tmp_path, channels=[])
    with patch("main.os.path.join", return_value=str(p)):
        asyncio.run(main())
    assert "No channels" in caplog.text


def test_main_invalid_channel_skipped_and_continues(caplog, tmp_path, monkeypatch):
    """A malformed channel must not abort the loop; the valid one registers."""
    import main as main_mod
    from main import main

    bad = {"ha_entity_id": "sensor.bad"}
    good = CHANNELS_CFG[0]
    p = _write_config(tmp_path, channels=[bad, good])

    # Short-circuit the long-lived gather so main() returns after registration.
    async def fake_gather(*coros, return_exceptions=False):
        for c in coros:
            t = asyncio.ensure_future(c)
            t.cancel()
        return []

    monkeypatch.setattr(main_mod.asyncio, "gather", fake_gather)

    with patch("main.os.path.join", return_value=str(p)):
        with patch("main.MessageBus") as mb:
            mb.return_value.connect = AsyncMock()
            with patch("main.AcLoadService") as ALS:
                ALS.return_value.register = AsyncMock()
                ALS.return_value.close = AsyncMock()
                asyncio.run(main())
    assert "Invalid channel" in caplog.text
    ALS.assert_called_once()


def test_main_register_failure_continues(caplog, tmp_path, monkeypatch):
    import main as main_mod
    from main import main

    bad = CHANNELS_CFG[0]
    good = CHANNELS_CFG[1]
    p = _write_config(tmp_path, channels=[bad, good])

    async def fake_gather(*coros, return_exceptions=False):
        for c in coros:
            t = asyncio.ensure_future(c)
            t.cancel()
        return []

    monkeypatch.setattr(main_mod.asyncio, "gather", fake_gather)

    with patch("main.os.path.join", return_value=str(p)):
        with patch("main.MessageBus") as mb:
            mb.return_value.connect = AsyncMock()
            with patch("main.AcLoadService") as ALS:
                ALS.return_value.register = AsyncMock(side_effect=RuntimeError("boom"))
                ALS.return_value.close = AsyncMock()
                ALS.return_value.name = "bad"
                asyncio.run(main())
    assert "Failed to register" in caplog.text
    assert ALS.call_count == 2


def test_main_all_services_fail_returns(caplog, tmp_path, monkeypatch):
    from main import main

    p = _write_config(tmp_path, channels=[CHANNELS_CFG[0]])

    with patch("main.os.path.join", return_value=str(p)):
        with patch("main.MessageBus") as mb:
            mb.return_value.connect = AsyncMock()
            with patch("main.AcLoadService") as ALS:
                ALS.return_value.register = AsyncMock(side_effect=RuntimeError("nope"))
                ALS.return_value.close = AsyncMock()
                asyncio.run(main())
    assert "No services could be registered" in caplog.text


# ---------------------------------------------------------------------------
# websocket_task / heartbeat_task / shutdown — direct exercise via main()
# ---------------------------------------------------------------------------


def test_main_heartbeat_writes_file(caplog, tmp_path, monkeypatch):
    """Drive main() far enough to exercise heartbeat_task once."""
    import main as main_mod
    from main import main

    p = _write_config(tmp_path, channels=[CHANNELS_CFG[0]])

    written = []

    async def fake_to_thread(fn, *args):
        result = fn(*args)
        written.append(getattr(fn, "__name__", str(fn)))
        return result

    async def fake_gather(*coros, return_exceptions=False):
        # Run heartbeat_task once, cancel the websocket task, let things unwind.
        tasks = [asyncio.ensure_future(c) for c in coros]
        # Give heartbeat a moment to run
        await asyncio.sleep(0.05)
        for t in tasks:
            t.cancel()
        # Drain via wait() (not the patched gather) to avoid recursion.
        await asyncio.wait(tasks, timeout=0.5)
        return []

    monkeypatch.setattr(main_mod.asyncio, "gather", fake_gather)
    monkeypatch.setattr(main_mod.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(main_mod, "write_heartbeat", MagicMock())
    monkeypatch.setattr(main_mod.os, "makedirs", MagicMock())  # no-op

    with patch("main.os.path.join", return_value=str(p)):
        with patch("main.MessageBus") as mb:
            mb.return_value.connect = AsyncMock()
            with patch("main.AcLoadService") as ALS:
                ALS.return_value.register = AsyncMock()
                ALS.return_value.close = AsyncMock()
                # Websocket connect will hang/fail fast; we cancel anyway.
                _patch_websockets(monkeypatch)
                monkeypatch.setattr(
                    "main.websockets.connect",
                    AsyncMock(side_effect=Exception("nope")),
                )
                asyncio.run(main())
    # to_thread at least invoked our wrapper
    assert written  # heartbeat ran at least one cycle


def test_shutdown_cleans_up(monkeypatch, tmp_path):
    """Drive main() to the point where signal handlers + shutdown wiring are set up."""
    import main as main_mod
    from main import main

    p = _write_config(tmp_path, channels=[CHANNELS_CFG[0]])

    async def fake_gather(*coros, return_exceptions=False):
        for c in coros:
            t = asyncio.ensure_future(c)
            t.cancel()
        return []

    monkeypatch.setattr(main_mod.asyncio, "gather", fake_gather)
    # No websocket connect needed — cancellation stops everything before that.
    _patch_websockets(monkeypatch)

    with patch("main.os.path.join", return_value=str(p)):
        with patch("main.MessageBus") as mb:
            mb.return_value.connect = AsyncMock()
            with patch("main.AcLoadService") as ALS:
                ALS.return_value.register = AsyncMock()
                ALS.return_value.close = AsyncMock()
                asyncio.run(main())
    # ALS constructed → main() reached the registration phase without crashing.
    ALS.assert_called_once()


def test_unavailable_channel_does_not_publish_zero():
    from main import AcLoadService, HaWebSocketClient

    service = AcLoadService(MagicMock(), "com.victronenergy.acload.x", 71, "X", 0)
    service.update_power(42.0)
    client = HaWebSocketClient("ws://ha", "token", {"sensor.x": service})
    message = json.dumps(
        {
            "type": "event",
            "event": {
                "variables": {
                    "trigger": {"entity_id": "sensor.x", "to_state": {"state": "unavailable"}}
                }
            },
        }
    )
    asyncio.run(client.handle_message(message))
    assert service._service["/Connected"] == 0
    assert service._service["/Ac/Power"] is None
    assert service._service["/Ac/L1/Power"] is None


@pytest.mark.parametrize("failure", [ConnectionRefusedError("offline"), TimeoutError("slow HA")])
def test_network_failure_retries_without_exiting(monkeypatch, failure):
    from main import run_websocket_client

    client = MagicMock()
    client.connect = AsyncMock(side_effect=failure)
    client.disconnect = AsyncMock()
    waits = []

    async def wait_once(delay):
        waits.append(delay)
        if len(waits) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("main.asyncio.sleep", wait_once)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_websocket_client(client))
    assert client.connect.await_count == 2
    assert client.disconnect.await_count == 2
    assert 1 <= waits[0] <= 1.1
    assert 2 <= waits[1] <= 2.2
    client.set_connected.assert_called_with(False)


def test_heartbeat_replaces_symlink_without_clobbering_target(tmp_path):
    """A preexisting heartbeat symlink cannot redirect the timestamp write."""
    from main import write_heartbeat

    target = tmp_path / "protected.txt"
    target.write_text("keep this content", encoding="utf-8")
    heartbeat = tmp_path / "heartbeat"
    heartbeat.symlink_to(target)
    write_heartbeat(heartbeat)
    assert target.read_text(encoding="utf-8") == "keep this content"
    assert not heartbeat.is_symlink()
    assert int(heartbeat.read_text(encoding="utf-8")) > 0
    assert list(tmp_path.glob(".dbus-emporia-vue-heartbeat-*")) == []


@pytest.mark.parametrize(
    "event_state,event_time,snapshot_time,expected",
    [
        ("100", "2026-09-12T10:00:02+00:00", "2026-09-12T10:00:01+00:00", 100.0),
        ("100", "2026-09-12T10:00:01+00:00", "2026-09-12T10:00:02+00:00", 50.0),
        ("unavailable", "2026-09-12T10:00:02+00:00", "2026-09-12T10:00:01+00:00", None),
        ("0", "2026-09-12T10:00:02+00:00", "2026-09-12T10:00:01+00:00", 0.0),
        ("100", None, None, 100.0),
    ],
)
def test_initial_snapshot_cannot_overwrite_a_newer_interleaved_event(
    event_state, event_time, snapshot_time, expected
):
    """HA timestamps resolve overlap without restoring stale or invalid values."""
    from main import AcLoadService, HaWebSocketClient  # pylint: disable=import-outside-toplevel

    service = AcLoadService(MagicMock(), "com.victronenergy.acload.x", 71, "X", 0)
    client = HaWebSocketClient("ws://ha.invalid", "test", {"sensor.x": service})
    event = {
        "type": "event",
        "event": {
            "variables": {
                "trigger": {
                    "entity_id": "sensor.x",
                    "to_state": {"state": event_state, "last_updated": event_time},
                }
            }
        },
    }
    result = {
        "id": 1,
        "type": "result",
        "success": True,
        "result": [
            {"entity_id": "sensor.x", "state": "50", "last_updated": snapshot_time},
        ],
    }
    client.websocket = AsyncMock()
    client.websocket.recv.side_effect = [json.dumps(event), json.dumps(result)]
    asyncio.run(client.fetch_initial_states())
    assert service._service["/Ac/Power"] == expected


def test_interleaved_event_is_retained_when_initial_snapshot_fails():
    """A failed initial query must not discard an already received zero value."""
    from main import AcLoadService, HaWebSocketClient  # pylint: disable=import-outside-toplevel

    service = AcLoadService(MagicMock(), "com.victronenergy.acload.x", 71, "X", 0)
    client = HaWebSocketClient("ws://ha.invalid", "test", {"sensor.x": service})
    client.websocket = AsyncMock()
    client.websocket.recv.side_effect = [
        json.dumps(
            {
                "type": "event",
                "event": {
                    "variables": {
                        "trigger": {
                            "entity_id": "sensor.x",
                            "to_state": {"state": "0"},
                        }
                    }
                },
            }
        ),
        json.dumps({"id": 1, "type": "result", "success": False, "error": {"code": "test"}}),
    ]
    asyncio.run(client.fetch_initial_states())
    assert service._service["/Ac/Power"] == 0.0
    assert service._service["/Connected"] == 1


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("disconnect_error", [False, True])
def test_real_signal_exits_without_unretrieved_tasks(stop_signal, disconnect_error, tmp_path):
    """Run the actual signal wiring in a child with all network/bus I/O stubbed."""
    config_path = _write_config(tmp_path)
    script = textwrap.dedent(
        """
        import asyncio, os, signal, sys
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch
        from tests.test_main import _stub_aiovelib
        _stub_aiovelib.__wrapped__()
        import main
        buses = [MagicMock(), MagicMock()]
        remaining = iter(buses)
        def make_bus(*args, **kwargs):
            return SimpleNamespace(connect=AsyncMock(return_value=next(remaining)))
        async def connect():
            loop = asyncio.get_running_loop()
            loop.call_later(0.02, os.kill, os.getpid(), int(sys.argv[2]))
            await asyncio.Event().wait()
        close_error = RuntimeError('unexpected close failure') if sys.argv[3] == 'True' else None
        client = SimpleNamespace(connect=connect, listen=AsyncMock(),
                                 disconnect=AsyncMock(side_effect=close_error),
                                 set_connected=MagicMock())
        async def run():
            errors = []
            asyncio.get_running_loop().set_exception_handler(
                lambda loop, context: errors.append(context))
            with patch.object(main, 'load_config', return_value=main.load_config(sys.argv[1])), \
                 patch.object(main, 'MessageBus', side_effect=make_bus), \
                 patch.object(main, 'HaWebSocketClient', return_value=client), \
                 patch.object(main, 'write_heartbeat', MagicMock()):
                await asyncio.wait_for(main.main(), timeout=3)
            await asyncio.sleep(0)
            assert not errors, errors
            assert all(bus.disconnect.call_count == 1 for bus in buses)
            assert client.disconnect.await_count >= 1
            assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            assert not asyncio.get_running_loop()._signal_handlers
        asyncio.run(run())
        print('CLEAN_SHUTDOWN')
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(config_path),
            str(int(stop_signal)),
            str(disconnect_error),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CLEAN_SHUTDOWN" in result.stdout, result.stderr
    assert "Task exception was never retrieved" not in result.stderr
    assert "SystemExit" not in result.stderr
    assert "AttributeError" not in result.stderr
    if disconnect_error:
        assert "Failed to close Home Assistant connection" in result.stderr
    else:
        assert "Traceback" not in result.stderr


def test_failed_service_release_still_disconnects_its_bus():
    from main import AcLoadService

    bus = MagicMock()
    service = AcLoadService(bus, "com.victronenergy.acload.test", 71, "Test", 0)
    service._service.close = AsyncMock(side_effect=RuntimeError("release failed"))
    with pytest.raises(RuntimeError, match="release failed"):
        asyncio.run(service.close())
    bus.disconnect.assert_called_once()


def test_timed_out_service_release_disconnects_bus_without_pending_tasks():
    """The shutdown deadline still disconnects a service blocked on name release."""
    from main import AcLoadService

    bus = MagicMock()
    service = AcLoadService(bus, "com.victronenergy.acload.test", 71, "Test", 0)

    async def never_releases():
        await asyncio.Event().wait()

    service._service.close = never_releases

    async def check():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(service.close(), timeout=0.01)
        bus.disconnect.assert_called_once()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(check())


def _submeter_state(power="-125", timestamp=1000, unit="W"):
    return {
        "entity_id": "sensor.a",
        "state": power,
        "attributes": {"unit_of_measurement": unit},
        "last_reported": datetime.fromtimestamp(timestamp, UTC).isoformat(),
    }


@pytest.fixture
def submeter(monkeypatch):
    from main import AcLoadService

    clock = types.SimpleNamespace(wall=1000.0, monotonic=50.0)
    monkeypatch.setattr("main.time.time", lambda: clock.wall)
    monkeypatch.setattr("main.time.monotonic", lambda: clock.monotonic)
    service = AcLoadService(
        MagicMock(),
        "com.victronenergy.acload.a",
        71,
        "Main supply",
        0,
        {"channel": "sensor.a", "stale_after_seconds": 30.0},
    )
    return service, clock


@pytest.mark.parametrize("selection", [None, {"channel": "sensor.b"}])
def test_submeter_selection_is_optional_and_uses_configured_channel(selection):
    from main import selected_submeter

    config = {"channels": CHANNELS_CFG, "submeter": selection}
    expected = {"channel": "sensor.b", "stale_after_seconds": 30.0} if selection else None
    assert selected_submeter(config) == expected
    assert selected_submeter({"channels": CHANNELS_CFG}) is None


@pytest.mark.parametrize(
    "selection,channels",
    [
        (True, CHANNELS_CFG),
        ({"channel": "sensor.missing"}, CHANNELS_CFG),
        ({"channel": 71}, CHANNELS_CFG),
        ({"channel": "sensor.a"}, [CHANNELS_CFG[0], CHANNELS_CFG[0]]),
        (
            {"channel": "sensor.a"},
            [dict(CHANNELS_CFG[0], service_name="com.victronenergy.grid.a")],
        ),
        *[
            ({"channel": "sensor.a", "stale_after_seconds": age}, CHANNELS_CFG)
            for age in (True, "30", 9, float("inf"), float("nan"))
        ],
    ],
)
def test_invalid_submeter_selection_rejected(selection, channels):
    from main import selected_submeter

    with pytest.raises(ValueError):
        selected_submeter({"channels": channels, "submeter": selection})


def test_selected_channel_exposes_standard_acload_profile(submeter):
    from main import AcLoadService

    service, _ = submeter
    items = service._service.items
    assert service.name == "com.victronenergy.acload.a"
    assert items["/Role"] == "acload"
    assert items["/AllowedRoles"] == ["acload"]
    assert items["/Position"] == 0
    assert items["/IsGenericEnergyMeter"] == 1
    assert items["/NrOfPhases"] == 1
    assert items["/Serial"] == "emporia:sensor.a"
    assert items["/Source/EntityId"] == "sensor.a"
    assert items["/RefreshTime"] == 5000
    assert items["/Ac/Power"] is None
    ordinary = AcLoadService(MagicMock(), "com.victronenergy.acload.b", 72, "B", 0)
    assert "/Source/EntityId" not in ordinary._service.items
    assert "/LastUpdate" not in ordinary._service.items


@pytest.mark.parametrize(
    "power,unit,expected", [("-125", "W", -125.0), ("0", "W", 0.0), ("1.2", "kW", 1200.0)]
)
def test_submeter_preserves_signed_watts_and_source_time(submeter, power, unit, expected):
    service, _ = submeter
    service.update_entity(_submeter_state(power, unit=unit))
    assert service._service["/Ac/Power"] == expected
    assert service._service["/Ac/L1/Power"] == expected
    assert service._service["/LastUpdate"] == 1000.0
    assert service._service["/Connected"] == 1


@pytest.mark.parametrize(
    "state",
    [
        {},
        _submeter_state("unavailable"),
        _submeter_state("NaN"),
        _submeter_state("inf"),
        _submeter_state("1e308", unit="kW"),
        _submeter_state(unit="kWh"),
        _submeter_state(timestamp=969),
        _submeter_state(timestamp=1006),
    ],
)
def test_submeter_invalid_or_stale_reading_clears_previous_power(submeter, state):
    service, clock = submeter
    clock.wall = 960
    service.update_entity(_submeter_state(timestamp=960))
    assert service._service["/Connected"] == 1
    clock.wall = 1000
    service.update_entity(state)
    assert service._service["/Ac/Power"] is None
    assert service._service["/Ac/L1/Power"] is None
    assert service._service["/LastUpdate"] is None
    assert service._service["/Connected"] == 0


def test_repeated_poll_does_not_make_an_old_source_sample_fresh(submeter):
    service, clock = submeter
    service.update_entity(_submeter_state())
    clock.wall += 29
    clock.monotonic += 29
    service.update_entity(_submeter_state())
    assert service._service["/Connected"] == 1
    clock.wall += 1
    clock.monotonic += 1
    service.expire()
    assert service._service["/Connected"] == 0
    assert service._service["/Ac/Power"] is None


def test_older_poll_cannot_undo_a_newer_unavailable_event(submeter):
    service, clock = submeter
    service.update_entity(_submeter_state(timestamp=995))
    service.update_entity(_submeter_state("unavailable", timestamp=1000))
    service.update_entity(_submeter_state(timestamp=998))
    assert service._service["/Connected"] == 0
    assert service._service["/Ac/Power"] is None
    clock.wall += 2
    service.update_entity(_submeter_state(timestamp=1002))
    assert service._service["/Connected"] == 1


def test_ha_disconnect_immediately_invalidates_selected_submeter(submeter):
    service, _ = submeter
    service.update_entity(_submeter_state())
    service.set_connected(False)
    assert service._service["/Connected"] == 0
    assert service._service["/Ac/Power"] is None
    assert service._service["/LastUpdate"] is None


@pytest.mark.parametrize("result", [{"success": False}, {"success": True, "result": []}])
def test_failed_or_missing_refresh_invalidates_only_selected_channel(submeter, result):
    from main import AcLoadService, HaWebSocketClient

    service, _ = submeter
    service.update_entity(_submeter_state())
    ordinary = AcLoadService(MagicMock(), "com.victronenergy.acload.b", 72, "B", 0)
    ordinary.update_power(200)
    client = HaWebSocketClient("ws://ha", "token", {"sensor.a": service, "sensor.b": ordinary})
    client._submeter_request = 2
    asyncio.run(client.handle_message(json.dumps(dict(result, id=2, type="result"))))
    assert service._service["/Connected"] == 0
    assert ordinary._service["/Connected"] == 1
    assert ordinary._service["/Ac/Power"] == 200
    assert client._submeter_request is None


def test_refresh_uses_ha_timestamp_even_when_power_is_unchanged(submeter):
    from main import HaWebSocketClient

    service, clock = submeter
    service.update_entity(_submeter_state())
    clock.wall += 5
    clock.monotonic += 5
    client = HaWebSocketClient("ws://ha", "token", {"sensor.a": service})
    client._submeter_request = 2
    asyncio.run(
        client.handle_message(
            json.dumps(
                {
                    "id": 2,
                    "type": "result",
                    "success": True,
                    "result": [_submeter_state(timestamp=1005)],
                }
            )
        )
    )
    assert service._service["/LastUpdate"] == 1005.0
    assert service._service["/Ac/Power"] == -125.0


@pytest.mark.parametrize("send_failure", [False, True])
def test_refresh_polls_every_five_seconds_and_invalidates_unanswered_queries(
    submeter, monkeypatch, send_failure
):
    from main import HaWebSocketClient

    service, _ = submeter
    service.update_entity(_submeter_state())
    client = HaWebSocketClient("ws://ha", "token", {"sensor.a": service})
    client.websocket = AsyncMock()
    if send_failure:
        client.websocket.send.side_effect = OSError("offline")
    waits = []

    async def tick(delay):
        waits.append(delay)
        if len(waits) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr("main.asyncio.sleep", tick)
    if send_failure:
        asyncio.run(client.refresh_submeter())
    else:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(client.refresh_submeter())
    assert waits == [5] * len(waits)
    assert json.loads(client.websocket.send.call_args.args[0])["type"] == "get_states"
    assert service._service["/Connected"] == 0


def test_refresh_disabled_without_selected_channel():
    from main import HaWebSocketClient

    client = HaWebSocketClient(
        "ws://ha", "token", {"sensor.a": types.SimpleNamespace(submeter=None)}
    )
    client.websocket = AsyncMock()
    asyncio.run(client.refresh_submeter())
    client.websocket.send.assert_not_called()


def test_direct_mode_never_constructs_ha_client(tmp_path, monkeypatch):
    import emporia
    import main as app
    from sources import Measurement

    cfg = [
        {
            **CHANNELS_CFG[0],
            "id": "circuit",
            "emporia_device_gid": 1,
            "emporia_channel": "1",
            "emporia_import_channel": "MainsFromGrid",
        }
    ]
    cfg[0].pop("ha_entity_id")
    _write_config(
        tmp_path,
        source="emporia",
        emporia={},
        channels=cfg,
        ha_token="",
        submeter={"channel": "circuit", "stale_after_seconds": 30},
    )
    monkeypatch.setattr(app, "_here", str(tmp_path))
    monkeypatch.setattr(app, "write_heartbeat", lambda: None)
    monkeypatch.setattr(
        app, "HaWebSocketClient", MagicMock(side_effect=AssertionError("HA started"))
    )
    monkeypatch.setattr(
        app,
        "MessageBus",
        MagicMock(return_value=MagicMock(connect=AsyncMock(return_value=MagicMock()))),
    )
    original_service, services = app.AcLoadService, []

    def service(*args):
        instance = original_service(*args)
        services.append(instance)
        return instance

    monkeypatch.setattr(app, "AcLoadService", service)

    async def exercise():
        ready = asyncio.Event()

        class Client:
            def __init__(self, config, channels, publish, unavailable, publish_energy):
                assert channels[0]["id"] == "circuit"
                assert config["token_file"] == str(tmp_path / "emporia-tokens.json")
                self.publish, self.unavailable, self.energy = publish, unavailable, publish_energy

            async def run(self):
                now = app.time.time()
                self.publish({"circuit": Measurement(-125, now)})
                self.energy(
                    {"circuit": {"energy_day": 3, "energy_import_day": 4, "timestamp": now}}
                )
                ready.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(emporia, "EmporiaClient", Client)
        task = asyncio.create_task(app.main())
        await asyncio.wait_for(ready.wait(), 2)
        try:
            items = services[0]._service.items
            assert items["/Ac/Power"] == -125
            assert items["/Connected"] == 1
            assert items["/Source/Type"] == "emporia"
            assert items["/Emporia/Energy/Day"] == 3
            assert items["/Emporia/Energy/Import/Day"] == 4
            assert items["/Ac/Energy/Forward"] is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(exercise())
    app.HaWebSocketClient.assert_not_called()
    services[0]._bus.disconnect.assert_called_once()


def test_ha_mode_never_constructs_emporia_client(tmp_path, monkeypatch):
    import emporia
    import main as app

    _write_config(tmp_path, source="home_assistant", emporia={"credentials_file": "unused"})
    monkeypatch.setattr(app, "_here", str(tmp_path))
    monkeypatch.setattr(app, "write_heartbeat", lambda: None)
    monkeypatch.setattr(
        app,
        "MessageBus",
        MagicMock(return_value=MagicMock(connect=AsyncMock(return_value=MagicMock()))),
    )
    cloud = MagicMock(side_effect=AssertionError("Emporia started"))
    monkeypatch.setattr(emporia, "EmporiaClient", cloud)

    async def exercise():
        ready = asyncio.Event()

        async def ha_client(client):
            assert set(client.channel_map) == {"sensor.a", "sensor.b"}
            ready.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(app, "run_websocket_client", ha_client)
        task = asyncio.create_task(app.main())
        await asyncio.wait_for(ready.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    cloud.assert_not_called()

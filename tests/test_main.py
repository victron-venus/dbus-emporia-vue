"""Tests for main.py orchestration — aiovelib + websockets + heartbeat are mocked."""

import asyncio
import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level fixtures: stub aiovelib + dbus_fast before main.py imports
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_aiovelib(monkeypatch):
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
            self.items[len(self.items)] = item

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

    # Place under the project-local aiovelib/ dir
    proj_aiovelib = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aiovelib")
    aiovelib_pkg = types.ModuleType("aiovelib")
    aiovelib_pkg.__path__ = [proj_aiovelib]
    sys.modules["aiovelib"] = aiovelib_pkg
    sys.modules["aiovelib.service"] = svc_mod

    # Now safe to import main
    if "main" in sys.modules:
        del sys.modules["main"]
    yield


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
        c.channel_map["sensor.x"].update_power.assert_called_once_with(500.0)

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
        svc.update_power.assert_not_called()

    def test_handle_message_invalid_json_logs_error(self):
        c = self._make()
        # Should not raise
        asyncio.run(c.handle_message("not json {{{"))

    def test_handle_message_non_event_returns(self):
        c = self._make(channel_map={"sensor.x": MagicMock()})
        msg = json.dumps({"type": "result", "result": []})
        asyncio.run(c.handle_message(msg))
        c.channel_map["sensor.x"].update_power.assert_not_called()

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

        svc.update_power.assert_called_once_with(42.0)
        assert svc.set_connected.call_args_list[-1].args == (True,)

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
        with pytest.raises(RuntimeError, match="authentication failed"):
            asyncio.run(c.connect())

    def test_connect_bad_initial_raises(self, monkeypatch):
        from main import HaWebSocketClient

        fake_ws = _patch_websockets(monkeypatch)
        ws = self._ws([{"type": "other"}])
        fake_ws.connect = AsyncMock(return_value=ws)
        c = HaWebSocketClient("ws://h:8123/api/websocket", "tok", {})
        with pytest.raises(RuntimeError, match="auth_required"):
            asyncio.run(c.connect())


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

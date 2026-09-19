"""Emporia request, conversion, authentication and worker contracts."""

import asyncio
import os
import stat
import sys
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from emporia import (
    EmporiaClient,
    _auth_error,
    _number,
    _read_private_json,
    _timestamp,
    _write_private_json,
)

STAMP = "2026-09-16T07:00:00Z"
EPOCH = datetime.fromisoformat(STAMP).timestamp()
TEMPLATE = "usage?gids={deviceGids}&instant={instant}&scale={scale}&unit={unit}"


def channel(number="1", gid=10, **extra):
    return {
        "id": f"sensor.{gid}_{number}",
        "emporia_device_gid": gid,
        "emporia_channel": number,
        **extra,
    }


def response(data):
    return SimpleNamespace(raise_for_status=Mock(), json=lambda: data)


def usage_payload(channels, gid=10, instant=STAMP):
    return {
        "deviceListUsages": {
            "instant": instant,
            "devices": [{"deviceGid": gid, "channelUsages": channels}],
        }
    }


def client(channels=None, config=None, payload=None):
    result = EmporiaClient(config or {}, channels or [channel()], Mock(), Mock(), Mock())
    result._auth = SimpleNamespace(request=Mock(return_value=response(payload or {})))
    result._api_template = TEMPLATE
    result._channel_info = {
        (str(item["emporia_device_gid"]), str(item["emporia_channel"])): {"type": "FiftyAmp"}
        for item in result.channels
    }
    result._device_status = {str(gid): True for gid in result.device_gids}
    result._status_timestamp = time.monotonic()
    result._next_status = time.monotonic() + 15
    return result


@pytest.mark.parametrize("value", [None, True, False, "unavailable", "nan", float("inf"), {}])
def test_invalid_numbers_remain_unavailable(value):
    assert _number(value) is None


@pytest.mark.parametrize("value, expected", [(0, 0), (-1.5, -1.5), ("2.5", 2.5)])
def test_finite_numbers(value, expected):
    assert _number(value) == expected


@pytest.mark.parametrize("value", [None, 1, "bad", "2026-09-16T07:00:00", datetime(2026, 1, 1)])
def test_missing_or_ambiguous_timestamps_remain_unavailable(value):
    assert _timestamp(value) is None


def test_timestamps_preserve_timezone_and_old_sample_time():
    assert _timestamp(STAMP) == EPOCH
    assert _timestamp("2026-09-16T00:00:00-07:00") == EPOCH
    assert _timestamp(datetime(2026, 9, 16, 7, tzinfo=UTC)) == EPOCH
    assert _timestamp("1970-01-01T00:00:00Z") is None


def test_power_is_batched_and_preserves_response_timestamp():
    payload = usage_payload([{"channelNum": "1", "usage": 0.0001}])
    monitor = client([channel(), channel("2", gid=11)], payload=payload)
    readings = monitor.poll_power()
    assert readings["sensor.10_1"].power == pytest.approx(360)
    assert readings["sensor.10_1"].timestamp == EPOCH
    assert readings["sensor.10_1"].device_gid == 10
    assert readings["sensor.10_1"].channel_num == "1"
    assert readings["sensor.11_2"].power is None
    monitor._auth.request.assert_called_once()
    method, url = monitor._auth.request.call_args.args
    assert method == "get"
    assert "gids=10+11" in url
    assert "scale=1S" in url
    assert "unit=KilowattHours" in url


@pytest.mark.parametrize("value", [None, True, "NaN", "Infinity", "unknown"])
def test_bad_usage_does_not_become_zero(value):
    monitor = client(payload=usage_payload([{"channelNum": "1", "usage": value}]))
    assert monitor.poll_power()["sensor.10_1"].power is None


def test_missing_usage_does_not_become_zero_and_zero_is_valid():
    monitor = client(
        [channel(), channel("2")],
        payload=usage_payload([{"channelNum": "1"}, {"channelNum": "2", "usage": 0}]),
    )
    readings = monitor.poll_power()
    assert readings["sensor.10_1"].power is None
    assert readings["sensor.10_2"].power == 0


def test_missing_timestamp_invalidates_power_and_energy():
    monitor = client(payload=usage_payload([{"channelNum": "1", "usage": 1}], instant=None))
    assert monitor.poll_power()["sensor.10_1"].power is None
    assert monitor.poll_energy("day")["sensor.10_1"]["energy_day"] is None


def test_nonfinite_converted_power_is_unavailable():
    monitor = client(payload=usage_payload([{"channelNum": "1", "usage": 1e308}]))
    assert monitor.poll_power()["sensor.10_1"].power is None


@pytest.mark.parametrize("period, scale", [("day", "1D"), ("month", "1MON")])
def test_energy_uses_authoritative_kwh_and_its_own_timestamp(period, scale):
    monitor = client(payload=usage_payload([{"channelNum": "1", "usage": 1.25}]))
    result = monitor.poll_energy(period)["sensor.10_1"]
    assert result == {f"energy_{period}": 1.25, "timestamp": EPOCH}
    assert f"scale={scale}" in monitor._auth.request.call_args.args[1]


@pytest.mark.parametrize("period", ["day", "month"])
def test_directional_energy_shares_main_service_and_batched_request(period):
    monitor = client(
        [
            channel(
                "1,2,3",
                emporia_import_channel="MainsFromGrid",
                emporia_export_channel="MainsToGrid",
            )
        ],
        payload=usage_payload(
            [
                {"channelNum": "1,2,3", "usage": -1},
                {"channelNum": "MainsFromGrid", "usage": 2},
                {"channelNum": "MainsToGrid", "usage": -3},
            ]
        ),
    )
    result = monitor.poll_energy(period)
    assert result == {
        "sensor.10_1,2,3": {
            f"energy_{period}": -1,
            f"energy_import_{period}": 2,
            f"energy_export_{period}": 3,
            "timestamp": EPOCH,
        }
    }
    monitor._auth.request.assert_called_once()


@pytest.mark.parametrize("period", ["day", "month"])
def test_missing_directional_energy_is_unavailable_without_clearing_main(period):
    monitor = client(
        [
            channel(
                "1,2,3",
                emporia_import_channel="MainsFromGrid",
                emporia_export_channel="MainsToGrid",
            )
        ],
        payload=usage_payload(
            [
                {"channelNum": "1,2,3", "usage": 0},
                {"channelNum": "MainsFromGrid", "usage": None},
            ]
        ),
    )
    assert monitor.poll_energy(period)["sensor.10_1,2,3"] == {
        f"energy_{period}": 0,
        f"energy_import_{period}": None,
        f"energy_export_{period}": None,
        "timestamp": EPOCH,
    }


def test_only_configured_directional_energy_fields_are_published():
    monitor = client(
        [channel("1,2,3", emporia_import_channel="MainsFromGrid", power_multiplier=2)],
        payload=usage_payload(
            [
                {"channelNum": "1,2,3", "usage": 1},
                {"channelNum": "MainsFromGrid", "usage": 2},
                {"channelNum": "MainsToGrid", "usage": 3},
            ]
        ),
    )
    assert monitor.poll_energy("day")["sensor.10_1,2,3"] == {
        "energy_day": 2,
        "energy_import_day": 4,
        "timestamp": EPOCH,
    }


@pytest.mark.parametrize(
    "number, metadata, inverted, expected",
    [
        ("9", {"channelTypeGid": 13, "type": "FiftyAmp"}, True, -2),
        ("9", {"channelTypeGid": 13, "type": "FiftyAmp"}, False, 2),
        ("1", {"type": "FiftyAmp"}, True, 2),
        ("1", {"type": "FiftyAmpBidirectional"}, True, -2),
        ("1,2,3", {"type": "Main"}, True, -2),
        ("Balance", {"type": "Main"}, True, -2),
    ],
)
def test_channel_signs(number, metadata, inverted, expected):
    monitor = client([channel(number)], config={"solar_invert": inverted})
    monitor._channel_info[("10", number)] = metadata
    usage = 2 if metadata.get("channelTypeGid") == 13 else -2
    assert monitor._signed_usage(10, number, usage) == expected


def test_explicit_multiplier_scales_readings_without_reapplying_device_multiplier():
    monitor = client(
        [channel(power_multiplier=-1)],
        payload=usage_payload([{"channelNum": "1", "usage": 0.0001}]),
    )
    monitor._channel_info[("10", "1")]["channelMultiplier"] = 2
    assert monitor.poll_power()["sensor.10_1"].power == pytest.approx(-360)
    assert monitor.poll_energy("day")["sensor.10_1"]["energy_day"] == -0.0001


def test_unknown_metadata_is_unavailable():
    monitor = client(payload=usage_payload([{"channelNum": "1", "usage": 1}]))
    monitor._channel_info.clear()
    assert monitor.poll_power()["sensor.10_1"].power is None


@pytest.mark.parametrize(
    "number, expected",
    [("Balance", -2), ("TotalUsage", 2), ("MainsFromGrid", 2), ("MainsToGrid", 2)],
)
def test_aggregate_channels_inherit_main_classification(number, expected):
    monitor = client([channel(number)])
    monitor._channel_info = {("10", "1,2,3"): {"type": "Main", "channelTypeGid": 1}}
    assert monitor._signed_usage(10, number, -2) == expected


def test_aggregate_without_main_metadata_retains_default_classification():
    monitor = client([channel("Balance")])
    monitor._channel_info.clear()
    assert monitor._signed_usage(10, "Balance", -1) == -1


def test_signed_solar_energy_is_preserved_when_inversion_is_disabled():
    monitor = client(
        config={"solar_invert": False},
        payload=usage_payload([{"channelNum": "1", "usage": -1}]),
    )
    monitor._channel_info[("10", "1")] = {"channelTypeGid": 13}
    assert monitor.poll_energy("day")["sensor.10_1"]["energy_day"] == -1


def test_nested_device_readings_and_metadata():
    monitor = client(
        [channel(gid=11)],
        payload=usage_payload(
            [
                None,
                {
                    "channelNum": "1",
                    "nestedDevices": [
                        None,
                        {"deviceGid": 11, "channelUsages": [{"channelNum": "1", "usage": 0}]},
                        {"deviceGid": 12},
                    ],
                },
            ]
        ),
    )
    monitor._load_channels(
        {
            "devices": [
                None,
                {
                    "deviceGid": 10,
                    "devices": [
                        {
                            "deviceGid": 11,
                            "channels": [None, {"channelNum": "1", "type": "FiftyAmp"}],
                        }
                    ],
                },
            ]
        }
    )
    assert monitor.poll_power()["sensor.11_1"].power == 0


@pytest.mark.parametrize("payload", [{}, {"deviceListUsages": {}}, {"deviceListUsages": None}])
def test_invalid_api_responses_fail(payload):
    monitor = client(payload=payload)
    with pytest.raises(ValueError, match="usage response"):
        monitor.poll_power()


def test_http_errors_propagate():
    monitor = client()
    monitor._auth.request.return_value.raise_for_status.side_effect = TimeoutError("secret")
    with pytest.raises(TimeoutError):
        monitor.poll_power()


def test_status_request_is_batched_and_follows_its_own_cadence():
    monitor = client([channel(), channel(gid=11)])
    monitor._next_status = 0
    monitor._auth.request.side_effect = [
        response(
            {
                "devicesConnected": [
                    {"deviceGid": 10, "connected": True},
                    {"deviceGid": 11, "connected": True},
                ]
            }
        ),
        response(usage_payload([{"channelNum": "1", "usage": 0}])),
        response(usage_payload([{"channelNum": "1", "usage": 0}])),
    ]
    assert monitor.poll_power()["sensor.10_1"].power == 0
    assert monitor.poll_power()["sensor.10_1"].power == 0
    requests = monitor._auth.request.call_args_list
    assert len(requests) == 3
    assert requests[0].args == ("get", "customers/devices/status")
    assert all("gids=10+11" in call.args[1] for call in requests[1:])


def test_offline_status_invalidates_zero_power_without_losing_energy():
    monitor = client()
    monitor._next_status = 0
    monitor._auth.request.side_effect = [
        response({"devicesConnected": [{"deviceGid": 10, "connected": False}]}),
        response(usage_payload([{"channelNum": "1", "usage": 2.5}])),
    ]
    assert monitor.poll_power()["sensor.10_1"].power is None
    monitor._auth.request.assert_called_once()
    assert monitor.poll_energy("day")["sensor.10_1"]["energy_day"] == 2.5


@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        {"devicesConnected": []},
        {"devicesConnected": [None, {}, {"deviceGid": 10, "connected": 1}]},
    ],
)
def test_unknown_or_missing_status_makes_power_unavailable(payload):
    monitor = client()
    monitor._next_status = 0
    monitor._auth.request.return_value = response(payload)
    assert monitor.poll_power()["sensor.10_1"].power is None
    monitor._auth.request.assert_called_once()


def test_expired_status_cannot_publish_power(monkeypatch):
    monitor = client()
    monitor._status_timestamp = 100
    monitor._next_status = 200
    monkeypatch.setattr("emporia.time.monotonic", lambda: 131)
    assert monitor.poll_power()["sensor.10_1"].power is None
    monitor._auth.request.assert_not_called()


def test_status_expiring_during_usage_request_invalidates_power(monkeypatch):
    monitor = client()
    now = [100]
    monitor._status_timestamp = 100
    monitor._next_status = 200
    monkeypatch.setattr("emporia.time.monotonic", lambda: now[0])

    def slow_request(*args):
        now[0] = 131
        return response(usage_payload([{"channelNum": "1", "usage": 0}]))

    monitor._auth.request.side_effect = slow_request
    assert monitor.poll_power()["sensor.10_1"].power is None


def test_offline_and_unknown_devices_do_not_invalidate_online_device():
    monitor = client([channel(), channel(gid=11), channel(gid=12)])
    monitor._next_status = 0
    payload = usage_payload([{"channelNum": "1", "usage": 0}])
    payload["deviceListUsages"]["devices"].extend(
        [{"deviceGid": gid, "channelUsages": [{"channelNum": "1", "usage": 0}]} for gid in (11, 12)]
    )
    monitor._auth.request.side_effect = [
        response(
            {
                "devicesConnected": [
                    {"deviceGid": 10, "connected": True},
                    {"deviceGid": 11, "connected": False},
                ]
            }
        ),
        response(payload),
    ]
    readings = monitor.poll_power()
    assert readings["sensor.10_1"].power == 0
    assert readings["sensor.11_1"].power is None
    assert readings["sensor.12_1"].power is None


@pytest.mark.parametrize("auth_error", [False, True])
def test_status_errors_clear_validity_and_only_reset_unauthorized_sessions(auth_error, caplog):
    monitor = client()
    monitor._next_status = 0
    auth = monitor._auth
    error = RuntimeError("secret-token")
    if auth_error:
        error.response = SimpleNamespace(status_code=401)
    auth.request.side_effect = error
    assert monitor.poll_power()["sensor.10_1"].power is None
    assert monitor._device_status == {}
    assert monitor._status_timestamp is None
    assert monitor._auth is (None if auth_error else auth)
    assert "secret-token" not in caplog.text


def test_status_recovery_requires_a_new_online_status():
    monitor = client()
    monitor._next_status = 0
    monitor._auth.request.side_effect = [
        response({"devicesConnected": [{"deviceGid": 10, "connected": False}]}),
        response({"devicesConnected": [{"deviceGid": 10, "connected": True}]}),
        response(usage_payload([{"channelNum": "1", "usage": 0}])),
    ]
    assert monitor.poll_power()["sensor.10_1"].power is None
    assert monitor.poll_power()["sensor.10_1"].power is None
    monitor._next_status = 0
    assert monitor.poll_power()["sensor.10_1"].power == 0


def test_status_failures_back_off_without_accumulating_requests(monkeypatch):
    monitor = client()
    now = [100]
    monkeypatch.setattr("emporia.time.monotonic", lambda: now[0])
    monitor._next_status = 0
    monitor._auth.request.side_effect = TimeoutError("secret")
    waits = []
    for _ in range(7):
        monitor._refresh_status()
        waits.append(monitor._next_status - now[0])
        now[0] = monitor._next_status
    assert waits == [15, 30, 60, 120, 240, 300, 300]


def test_status_connects_once_and_does_not_retry_login_for_energy(monkeypatch):
    monitor = client()
    monitor._next_status = 0
    monitor._auth = None
    monitor._connect = Mock(side_effect=TimeoutError("secret"))
    monitor._stop.wait = lambda delay: monitor._stop.set()
    monitor._work(lambda callback, *args: callback(*args))
    monitor._connect.assert_called_once()
    monitor.publish.assert_called_once()


def test_private_files_are_atomic_and_never_store_password(tmp_path):
    path = tmp_path / "tokens.json"
    monitor = client(config={"token_file": str(path)})
    monitor._username = "user@example.test"
    monitor._store_tokens({"id_token": "id", "refresh_token": "refresh", "password": "secret"})
    assert _read_private_json(str(path)) == {
        "username": "user@example.test",
        "id_token": "id",
        "refresh_token": "refresh",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]
    monitor._store_tokens({"id_token": "new"})
    assert _read_private_json(str(path))["id_token"] == "new"


def test_atomic_write_failure_preserves_existing_token_file(tmp_path, monkeypatch):
    path = tmp_path / "tokens.json"
    _write_private_json(str(path), {"id_token": "old"})
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("full")))
    with pytest.raises(OSError):
        _write_private_json(str(path), {"id_token": "new"})
    assert _read_private_json(str(path)) == {"id_token": "old"}
    assert list(tmp_path.iterdir()) == [path]


def test_insecure_or_symlinked_credential_file_is_rejected(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        _read_private_json(str(path))
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        _read_private_json(str(link))


def test_private_file_requires_an_object(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text("[]")
    path.chmod(0o600)
    with pytest.raises(ValueError):
        _read_private_json(str(path))


@pytest.fixture
def dependencies(monkeypatch):
    auth = Mock()
    auth.return_value.request.return_value = response({"devices": []})
    cognito = Mock()
    config = Mock()
    modules = {
        "botocore": SimpleNamespace(UNSIGNED="unsigned"),
        "botocore.config": SimpleNamespace(Config=config),
        "pycognito": SimpleNamespace(Cognito=cognito),
        "pyemvue.auth": SimpleNamespace(Auth=auth, CLIENT_ID="client", USER_POOL="pool"),
        "pyemvue.pyemvue": SimpleNamespace(
            API_ROOT="https://api.example.test",
            API_CUSTOMER_DEVICES="devices",
            API_DEVICES_USAGE=TEMPLATE,
            API_GET_STATUS="customers/devices/status",
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delenv("EMPORIA_USERNAME", raising=False)
    monkeypatch.delenv("EMPORIA_PASSWORD", raising=False)
    return SimpleNamespace(auth=auth, cognito=cognito, config=config)


def test_token_authentication_has_bounded_requests_and_persist_callback(tmp_path, dependencies):
    path = tmp_path / "tokens.json"
    _write_private_json(
        str(path), {"id_token": "id", "access_token": "access", "refresh_token": "refresh"}
    )
    monitor = client(config={"token_file": str(path), "timeout_seconds": 4})
    monitor._connect()
    config = dependencies.config.call_args.kwargs
    assert config["connect_timeout"] == config["read_timeout"] == 4
    assert config["retries"] == {"total_max_attempts": 1}
    assert config["signature_version"] == "unsigned"
    assert dependencies.auth.call_args.kwargs["max_retry_attempts"] == 1
    assert dependencies.auth.call_args.kwargs["token_updater"] == monitor._store_tokens
    assert dependencies.cognito.call_args.kwargs["refresh_token"] == "refresh"
    dependencies.cognito.return_value.authenticate.assert_not_called()
    dependencies.auth.return_value.refresh_tokens.assert_called_once()


def test_credential_authentication_and_lazy_connection(tmp_path, dependencies):
    path = tmp_path / "credentials.json"
    _write_private_json(str(path), {"username": "User@example.test", "password": "secret"})
    monitor = client(
        config={"token_file": str(tmp_path / "tokens.json"), "credentials_file": str(path)}
    )
    monitor._auth = None
    dependencies.auth.return_value.request.side_effect = [
        response({"devices": [{"deviceGid": 10, "channels": [{"channelNum": "1"}]}]}),
        response(usage_payload([{"channelNum": "1", "usage": 0}])),
    ]
    assert monitor.poll_power()["sensor.10_1"].power == 0
    assert dependencies.cognito.call_args.kwargs["username"] == "user@example.test"
    dependencies.cognito.return_value.authenticate.assert_called_once_with(password="secret")


def test_missing_credentials_fail_before_authentication(tmp_path, dependencies):
    monitor = client(config={"token_file": str(tmp_path / "missing")})
    with pytest.raises(ValueError, match="required"):
        monitor._connect()
    dependencies.auth.assert_not_called()


def test_revoked_tokens_retry_credentials(tmp_path, dependencies, monkeypatch):
    path = tmp_path / "tokens.json"
    _write_private_json(
        str(path), {"id_token": "id", "access_token": "access", "refresh_token": "refresh"}
    )
    monkeypatch.setenv("EMPORIA_USERNAME", "user@example.test")
    monkeypatch.setenv("EMPORIA_PASSWORD", "secret")
    error = RuntimeError("secret-token")
    error.response = {"Error": {"Code": "NotAuthorizedException"}}
    dependencies.auth.return_value.refresh_tokens.side_effect = [error, None]
    monitor = client(config={"token_file": str(path)})
    monitor._connect()
    assert dependencies.auth.call_count == 2
    dependencies.cognito.return_value.authenticate.assert_called_once_with(password="secret")


def test_metadata_failure_does_not_leave_a_partial_connection(tmp_path, dependencies, monkeypatch):
    monkeypatch.setenv("EMPORIA_USERNAME", "user@example.test")
    monkeypatch.setenv("EMPORIA_PASSWORD", "secret")
    dependencies.auth.return_value.request.return_value = response({})
    monitor = client(config={"token_file": str(tmp_path / "tokens.json")})
    with pytest.raises(ValueError, match="device response"):
        monitor._connect()
    assert monitor._auth is None


def test_pinned_auth_adapter_without_network(tmp_path, monkeypatch):
    pytest.importorskip("pyemvue")
    from pycognito import Cognito
    from pyemvue.auth import Auth

    def no_network(*args, **kwargs):
        raise AssertionError("Unexpected network request")

    monkeypatch.setattr("socket.socket.connect", no_network)
    monkeypatch.setattr("requests.sessions.Session.send", no_network)

    def refresh(cognito):
        cognito.access_token = "new-access"
        cognito.id_token = "new-id"
        cognito.refresh_token = "new-refresh"
        cognito.token_type = "Bearer"

    monkeypatch.setattr(Cognito, "renew_access_token", refresh)
    monkeypatch.setattr(Auth, "request", lambda *args: response({"devices": []}))
    path = tmp_path / "tokens.json"
    _write_private_json(
        str(path), {"id_token": "id", "access_token": "access", "refresh_token": "refresh"}
    )
    monitor = client(config={"token_file": str(path), "timeout_seconds": 4})
    monitor._connect()
    config = monitor._auth.cognito.client.meta.config
    assert config.connect_timeout == config.read_timeout == 4
    assert config.retries["total_max_attempts"] == 1
    assert monitor._auth.tokens["id_token"] == "new-id"
    assert _read_private_json(str(path))["refresh_token"] == "new-refresh"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_authentication_error_is_identified_without_exception_text():
    error = RuntimeError("secret")
    assert not _auth_error(error)
    error.response = SimpleNamespace(status_code=401)
    assert _auth_error(error)


def test_worker_serializes_requests_and_delivers_callbacks_on_event_loop():
    async def scenario():
        loop_thread = threading.get_ident()
        received = asyncio.Event()
        thread_ids = []
        callbacks = []
        monitor = client()
        monitor.poll_interval = 0.01

        def power():
            thread_ids.append(threading.get_ident())
            return {}

        def energy(period):
            thread_ids.append(threading.get_ident())
            return {period: 0}

        def publish(values):
            callbacks.append((threading.get_ident(), values))
            if len(callbacks) >= 3:
                received.set()

        monitor.poll_power = power
        monitor.poll_energy = energy
        monitor.publish = monitor.publish_energy = publish
        task = asyncio.create_task(monitor.run())
        await asyncio.wait_for(received.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(ident == loop_thread for ident, _ in callbacks)
        assert len(set(thread_ids)) == 1
        assert thread_ids[0] != loop_thread
        assert monitor._worker.daemon

    asyncio.run(scenario())


def test_cancellation_does_not_wait_for_or_publish_a_stalled_request():
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        monitor = client()

        def power():
            entered.set()
            release.wait(2)
            return {}

        monitor.poll_power = power
        task = asyncio.create_task(monitor.run())
        try:
            for _ in range(100):
                if entered.is_set():
                    break
                await asyncio.sleep(0.005)
            assert entered.is_set()
            with pytest.raises(RuntimeError, match="already running"):
                await monitor.run()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 0.2)
            release.set()
            await asyncio.sleep(0.03)
            monitor.publish.assert_not_called()
            monitor.publish_energy.assert_not_called()
        finally:
            release.set()
            task.cancel()

    asyncio.run(scenario())


def test_outage_backoff_is_bounded_and_logs_do_not_include_secrets(caplog):
    monitor = client()
    error = RuntimeError("password-and-token")
    error.response = SimpleNamespace(status_code=401)
    monitor.poll_power = Mock(side_effect=error)
    waits = []

    def wait(delay):
        waits.append(delay)
        if len(waits) == 9:
            monitor._stop.set()

    monitor._stop.wait = wait
    monitor._work(lambda callback, *args: callback(*args))
    assert waits[:3] == [5, 10, 20]
    assert max(waits) == 300
    assert monitor.unavailable.call_count == 9
    assert monitor._auth is None
    assert "password-and-token" not in caplog.text


def test_energy_failure_does_not_mark_power_unavailable(caplog):
    monitor = client()
    monitor.poll_power = Mock(return_value={})
    monitor.poll_energy = Mock(side_effect=RuntimeError("secret"))
    monitor._stop.wait = lambda delay: monitor._stop.set()
    monitor._work(lambda callback, *args: callback(*args))
    monitor.publish.assert_called_once_with({})
    monitor.unavailable.assert_not_called()
    assert "secret" not in caplog.text

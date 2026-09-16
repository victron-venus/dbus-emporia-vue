"""Direct measurement validity and exclusive source configuration."""

from unittest.mock import MagicMock

import pytest

from sources import EmporiaChannel, Measurement, channel_id, emporia_config, source_mode


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("sources.time.time", lambda: now[0])
    monkeypatch.setattr("sources.time.monotonic", lambda: now[0])
    return now


def settings(**overrides):
    return emporia_config({"source": "emporia", "emporia": overrides, "channels": []})


def channel(**overrides):
    return EmporiaChannel(MagicMock(), settings(**overrides))


def published(state):
    return state.service.publish_measurement.call_args.args


def test_direct_reading_expires_without_substituting_zero(clock):
    state = channel()
    state.update(Measurement(0, 1000))
    assert published(state) == (Measurement(0, 1000), "emporia")
    clock[0] += 30
    state.refresh()
    assert published(state) == (None, "unavailable")
    state.update(Measurement(-20, 1030))
    assert published(state)[0].power == -20
    state.unavailable()
    assert published(state) == (None, "unavailable")


@pytest.mark.parametrize(
    "power,timestamp",
    [(None, 1000), (float("nan"), 1000), (True, 1000), (2, None), (2, 1100), (2, 900)],
)
def test_invalid_samples_are_unavailable(clock, power, timestamp):
    state = channel()
    state.update(Measurement(power, timestamp))
    assert published(state) == (None, "unavailable")


def test_unavailable_report_prevents_regressive_recovery(clock):
    state = channel()
    state.update(Measurement(5, 990))
    state.update(Measurement(None, 1000))
    state.update(Measurement(9, 995))
    assert published(state) == (None, "unavailable")
    clock[0] += 1
    state.update(Measurement(10, 1001))
    assert published(state)[0].power == 10


def test_wall_clock_rollback_does_not_extend_cached_reading(clock, monkeypatch):
    state = channel()
    state.update(Measurement(5, 1000))
    clock[0] += 20
    monkeypatch.setattr("sources.time.time", lambda: 1000)
    state.update(Measurement(5, 1000))
    clock[0] += 11
    state.refresh()
    assert published(state) == (None, "unavailable")


def test_energy_refresh_does_not_extend_power_and_accepts_reset(clock):
    state = channel()
    state.update(Measurement(10, 1000))
    state.update_energy("energy_day", 12, 1000)
    clock[0] += 31
    state.update_energy("energy_day", 0, 1031)
    assert published(state) == (None, "unavailable")
    assert state.service.publish_energy.call_args_list[-2].args == ("energy_day", 0, 1031)
    state.update_energy("energy_day", None, 1031)
    state.update_energy("energy_day", 10, 1000)
    assert state.service.publish_energy.call_args_list[-2].args == ("energy_day", None, None)
    state.update_energy("energy_day", 1, 1031)
    clock[0] += 1900
    state.refresh()
    assert state.service.publish_energy.call_args_list[-2].args == ("energy_day", None, None)


def test_energy_fields_are_explicit(clock):
    state = EmporiaChannel(MagicMock(), settings(), energy_fields=["energy_import_day"])
    state.update_energy("energy_import_day", 5, 1000)
    assert state.service.publish_energy.call_args.args == ("energy_import_day", 5, 1000)
    with pytest.raises(ValueError):
        state.update_energy("energy_export_day", 2, 1000)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        True,
        {"timeout_seconds": 0},
        {"stale_after_seconds": 3},
        {"status_interval_seconds": 30},
        {"solar_invert": 0},
        {"token_file": ""},
    ],
)
def test_invalid_direct_settings(raw):
    with pytest.raises(ValueError):
        emporia_config({"source": "emporia", "emporia": raw})


def test_modes_are_exclusive_and_legacy_defaults_to_ha():
    assert source_mode({}) == "home_assistant"
    assert emporia_config({}) is None
    assert emporia_config({"source": "home_assistant", "emporia": "ignored"}) is None
    assert settings()["poll_interval_seconds"] == 3
    with pytest.raises(ValueError):
        emporia_config({"source": "auto"})


def valid_channel():
    return {
        "emporia_device_gid": 1,
        "emporia_channel": "1",
        "id": "one",
        "service_name": "com.victronenergy.acload.one",
        "instance": 71,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"id": ""},
        {"emporia_device_gid": True},
        {"emporia_channel": ""},
        {"service_name": "com.example.one"},
        {"instance": True},
        {"power_multiplier": 0},
        {"emporia_import_channel": 5},
    ],
)
def test_invalid_channel_mapping(changes):
    with pytest.raises(ValueError):
        emporia_config({"source": "emporia", "channels": [{**valid_channel(), **changes}]})


def test_duplicate_ids_and_devices_rejected():
    original = valid_channel()
    for changed in (
        dict(original),
        {**original, "id": "two", "instance": 72, "service_name": "com.victronenergy.acload.two"},
    ):
        with pytest.raises(ValueError):
            emporia_config({"source": "emporia", "channels": [original, changed]})
    assert channel_id({"ha_entity_id": "sensor.one"}) == "sensor.one"
    assert channel_id({"id": "one", "ha_entity_id": "sensor.one"}) == "one"
    with pytest.raises(ValueError):
        emporia_config({"source": "emporia", "channels": {}})

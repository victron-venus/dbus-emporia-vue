"""Hardware-free tests for parse_ha.py — HA WebSocket payload → D-Bus power mapping."""

import pytest

from parse_ha import parse_ha_state_change, parse_initial_state, parse_power, parse_submeter_state

# ---------------------------------------------------------------------------
# parse_power
# ---------------------------------------------------------------------------


class TestParsePower:
    def test_valid_float_string(self):
        assert parse_power("123.5") == 123.5

    def test_valid_int_string(self):
        assert parse_power("0") == 0.0

    def test_negative_value(self):
        assert parse_power("-50.3") == -50.3

    def test_unavailable_returns_none(self):
        assert parse_power("unavailable") is None

    def test_unknown_returns_none(self):
        assert parse_power("unknown") is None

    def test_empty_string_returns_none(self):
        assert parse_power("") is None

    def test_none_returns_none(self):
        assert parse_power(None) is None

    def test_junk_string_returns_none(self):
        assert parse_power("not_a_number") is None


# ---------------------------------------------------------------------------
# parse_ha_state_change — HA WebSocket event payload fixtures
# ---------------------------------------------------------------------------

HA_EVENT_POWER_CHANGE = """{
    "id": 42,
    "type": "event",
    "event": {
        "platform": "state",
        "variables": {
            "trigger": {
                "entity_id": "sensor.emporia_channel_1_power",
                "to_state": {
                    "state": "847.2"
                }
            }
        }
    }
}"""

HA_EVENT_DISCONNECT = """{
    "type": "event",
    "event": {
        "platform": "state",
        "variables": {
            "trigger": {
                "entity_id": "sensor.emporia_channel_2_power",
                "to_state": {
                    "state": "unavailable"
                }
            }
        }
    }
}"""

HA_EVENT_UNKNOWN_STATE = """{
    "type": "event",
    "event": {
        "variables": {
            "trigger": {
                "entity_id": "sensor.emporia_channel_3_power",
                "to_state": null
            }
        }
    }
}"""

HA_NON_EVENT_MESSAGE = '{"type": "pong"}'


class TestParseHaStateChange:
    def test_power_change_extracts_entity_and_power(self):
        entity_id, power = parse_ha_state_change(HA_EVENT_POWER_CHANGE)
        assert entity_id == "sensor.emporia_channel_1_power"
        assert power == 847.2

    def test_unavailable_state_returns_none_power(self):
        entity_id, power = parse_ha_state_change(HA_EVENT_DISCONNECT)
        assert entity_id == "sensor.emporia_channel_2_power"
        assert power is None

    def test_null_to_state_returns_none_power(self):
        entity_id, power = parse_ha_state_change(HA_EVENT_UNKNOWN_STATE)
        assert entity_id == "sensor.emporia_channel_3_power"
        assert power is None

    def test_non_event_message_returns_none(self):
        entity_id, power = parse_ha_state_change(HA_NON_EVENT_MESSAGE)
        assert entity_id is None
        assert power is None

    def test_negative_power_preserved(self):
        msg = """{
            "type": "event",
            "event": {
                "variables": {
                    "trigger": {
                        "entity_id": "sensor.export_power",
                        "to_state": {"state": "-120.5"}
                    }
                }
            }
        }"""
        entity_id, power = parse_ha_state_change(msg)
        assert entity_id == "sensor.export_power"
        assert power == -120.5


# ---------------------------------------------------------------------------
# parse_initial_state — HA get_states response entity fixture
# ---------------------------------------------------------------------------

HA_STATE_ENTITY_VALID = {
    "entity_id": "sensor.emporia_channel_1_power",
    "state": "312.0",
}

HA_STATE_ENTITY_UNAVAILABLE = {
    "entity_id": "sensor.emporia_channel_2_power",
    "state": "unavailable",
}

HA_STATE_ENTITY_MISSING = {
    "state": "500.0",
}


class TestParseInitialState:
    def test_valid_state_extracts_power(self):
        entity_id, power = parse_initial_state(HA_STATE_ENTITY_VALID)
        assert entity_id == "sensor.emporia_channel_1_power"
        assert power == 312.0

    def test_unavailable_returns_none(self):
        entity_id, power = parse_initial_state(HA_STATE_ENTITY_UNAVAILABLE)
        assert entity_id == "sensor.emporia_channel_2_power"
        assert power is None

    def test_missing_entity_id_returns_none(self):
        entity_id, power = parse_initial_state(HA_STATE_ENTITY_MISSING)
        assert entity_id is None
        assert power == 500.0


def test_nonfinite_power_is_unavailable():
    for value in ("nan", "inf", "-inf"):
        assert parse_power(value) is None


@pytest.mark.parametrize("value", [True, False, "nan", "inf", "-inf", "unknown"])
def test_invalid_numeric_states_are_unavailable(value):
    assert parse_power(value) is None


@pytest.mark.parametrize("unit,power", [("W", -1.5), ("kW", -1500.0), ("kWh", None), (None, None)])
def test_submeter_requires_power_units_and_preserves_export_sign(unit, power):
    assert parse_submeter_state(
        {
            "state": "-1.5",
            "attributes": {"unit_of_measurement": unit},
            "last_updated": "1970-01-01T00:16:40Z",
        }
    ) == (power, 1000.0)


def test_submeter_prefers_last_reported_for_unchanged_values():
    assert parse_submeter_state(
        {
            "state": "0",
            "attributes": {"unit_of_measurement": "W"},
            "last_reported": "1970-01-01T00:16:45+00:00",
            "last_updated": "1970-01-01T00:16:40+00:00",
        }
    ) == (0.0, 1005.0)


@pytest.mark.parametrize(
    "timestamp", [None, "bad", "2026-09-14T01:00:00", 1000, "99999999999-01-01"]
)
def test_submeter_requires_a_timezone_aware_ha_timestamp(timestamp):
    assert parse_submeter_state(
        {
            "state": "1",
            "attributes": {"unit_of_measurement": "W"},
            "last_reported": timestamp,
        }
    ) == (1.0, None)

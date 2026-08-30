"""Hardware-free tests for parse_ha.py — HA WebSocket payload → D-Bus power mapping."""

from parse_ha import parse_ha_state_change, parse_initial_state, parse_power

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

    def test_unavailable_returns_zero(self):
        assert parse_power("unavailable") == 0.0

    def test_unknown_returns_zero(self):
        assert parse_power("unknown") == 0.0

    def test_empty_string_returns_zero(self):
        assert parse_power("") == 0.0

    def test_none_returns_zero(self):
        assert parse_power(None) == 0.0

    def test_junk_string_returns_zero(self):
        assert parse_power("not_a_number") == 0.0


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

    def test_unavailable_state_returns_zero_power(self):
        entity_id, power = parse_ha_state_change(HA_EVENT_DISCONNECT)
        assert entity_id == "sensor.emporia_channel_2_power"
        assert power == 0.0

    def test_null_to_state_returns_zero_power(self):
        entity_id, power = parse_ha_state_change(HA_EVENT_UNKNOWN_STATE)
        assert entity_id == "sensor.emporia_channel_3_power"
        assert power == 0.0

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

    def test_unavailable_returns_zero(self):
        entity_id, power = parse_initial_state(HA_STATE_ENTITY_UNAVAILABLE)
        assert entity_id == "sensor.emporia_channel_2_power"
        assert power == 0.0

    def test_missing_entity_id_returns_none(self):
        entity_id, power = parse_initial_state(HA_STATE_ENTITY_MISSING)
        assert entity_id is None
        assert power == 500.0

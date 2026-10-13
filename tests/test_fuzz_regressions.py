"""Fixed input regressions discovered while preparing the RC fuzz corpus."""

import json

import pytest

from parse_ha import parse_ha_state_change, parse_power, parse_submeter_state


@pytest.mark.parametrize(
    "value",
    [[], None, {"type": "event", "event": []}, {"type": "event", "event": {"variables": None}}],
)
def test_wrong_event_shape_is_not_a_measurement(value):
    assert parse_ha_state_change(json.dumps(value)) == (None, None)


def test_numeric_overflow_is_not_published_as_power():
    assert parse_power(10**400) is None
    assert (
        parse_submeter_state({"state": "1e308", "attributes": {"unit_of_measurement": "kW"}})[0]
        is None
    )


def test_wrong_attributes_shape_is_not_a_measurement():
    assert parse_submeter_state({"state": "5", "attributes": ["W"]})[0] is None


def test_non_text_entity_id_is_rejected():
    value = {
        "type": "event",
        "event": {"variables": {"trigger": {"entity_id": 123, "to_state": {"state": "12"}}}},
    }
    assert parse_ha_state_change(json.dumps(value)) == (None, None)

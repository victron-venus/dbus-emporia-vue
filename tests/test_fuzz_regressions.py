"""Fixed input regressions discovered while preparing the RC fuzz corpus."""

import json

import pytest

from parse_ha import parse_ha_state_change, parse_power, parse_submeter_state


def test_deeply_nested_json_is_rejected_as_invalid_input():
    # Some Python builds allow more C decoder nesting than the Python recursion limit.
    depth = 10_000
    message = "[" * depth + "0" + "]" * depth
    with pytest.raises(ValueError, match="JSON nesting is too deep") as error:
        parse_ha_state_change(message)
    assert isinstance(error.value.__cause__, RecursionError)


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

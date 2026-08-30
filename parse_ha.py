"""Pure functions for HA WebSocket payload → D-Bus power mapping. Hardware-free."""

import json


def parse_power(state: str | None) -> float:
    """Convert HA entity state to power in watts.

    Returns 0.0 for unavailable/unknown/empty states.
    """
    if state in (None, "", "unavailable", "unknown"):
        return 0.0
    try:
        return float(state)
    except (TypeError, ValueError):
        return 0.0


def parse_ha_state_change(message: str) -> tuple[str | None, float | None]:
    """Parse HA WebSocket event message, extract entity_id and power.

    Args:
        message: JSON string from HA WebSocket event type="event".

    Returns:
        (entity_id, power_watts) or (None, None) if not a state change.
    """
    data = json.loads(message)
    if data.get("type") != "event":
        return None, None
    variables = data.get("event", {}).get("variables", {})
    trigger = variables.get("trigger", {})
    entity_id = trigger.get("entity_id")
    state = (trigger.get("to_state") or {}).get("state")
    return entity_id, parse_power(state)


def parse_initial_state(entity: dict) -> tuple[str | None, float]:
    """Parse a single entity from HA get_states response.

    Returns:
        (entity_id, power_watts).
    """
    entity_id = entity.get("entity_id")
    state = entity.get("state")
    return entity_id, parse_power(state)

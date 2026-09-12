"""Pure functions for HA WebSocket payload → D-Bus power mapping. Hardware-free."""

import json
import math


def parse_power(state: str | None) -> float | None:
    """Convert HA entity state to power in watts.

    Returns None for unavailable, malformed or non-finite states.
    """
    if state in (None, "", "unavailable", "unknown"):
        return None
    try:
        value = float(state)  # type: ignore[arg-type]
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


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


def parse_initial_state(entity: dict) -> tuple[str | None, float | None]:
    """Parse a single entity from HA get_states response.

    Returns:
        (entity_id, power_watts).
    """
    entity_id = entity.get("entity_id")
    state = entity.get("state")
    return entity_id, parse_power(state)

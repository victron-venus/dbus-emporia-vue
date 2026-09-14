"""Pure functions for HA WebSocket payload → D-Bus power mapping. Hardware-free."""

import json
import math
from datetime import datetime


def parse_power(state: str | None) -> float | None:
    """Convert HA entity state to power in watts.

    Returns None for unavailable, malformed or non-finite states.
    """
    if isinstance(state, bool) or state in (None, "", "unavailable", "unknown"):
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


def parse_submeter_state(entity: dict) -> tuple[float | None, float | None]:
    """Read signed watts and the HA source timestamp, never the fetch time."""
    power = parse_power(entity.get("state"))
    unit = (entity.get("attributes") or {}).get("unit_of_measurement")
    if unit == "kW" and power is not None:
        power *= 1000
    elif unit != "W":
        power = None
    raw_time = entity.get("last_reported") or entity.get("last_updated")
    try:
        dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        timestamp = dt.timestamp() if dt.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        timestamp = None
    return power, timestamp

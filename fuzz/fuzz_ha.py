"""Fuzz project-owned Home Assistant event and power normalization."""

import json
import math
import sys
from pathlib import Path

import atheris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with atheris.instrument_imports():
    from parse_ha import parse_ha_state_change, parse_power, parse_submeter_state


def test_one_input(data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    power = parse_power(text)
    assert power is None or math.isfinite(power)  # nosec B101 - intentional test oracle
    try:
        entity, power = parse_ha_state_change(text)
    except ValueError:
        return
    assert entity is None or isinstance(entity, str)  # nosec B101 - intentional test oracle
    assert power is None or math.isfinite(power)  # nosec B101 - intentional test oracle
    value = json.loads(text)
    if isinstance(value, dict):
        power, timestamp = parse_submeter_state(value)
        assert power is None or math.isfinite(power)  # nosec B101 - intentional test oracle
        assert timestamp is None or math.isfinite(timestamp)  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()

"""Validate source settings and expire direct measurements."""

import math
import time
from dataclasses import dataclass

ENERGY_PATHS = {
    "energy_day": "Day",
    "energy_month": "Month",
    "energy_import_day": "Import/Day",
    "energy_import_month": "Import/Month",
    "energy_export_day": "Export/Day",
    "energy_export_month": "Export/Month",
}


@dataclass(frozen=True)
class Measurement:
    power: float | None
    timestamp: float | None
    device_gid: int | None = None
    channel_num: str | None = None


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def source_mode(config):
    mode = config.get("source", "home_assistant")
    if mode not in ("emporia", "home_assistant"):
        raise ValueError("source must be emporia or home_assistant")
    return mode


def channel_id(channel):
    return channel.get("id") or channel.get("ha_entity_id")


def emporia_config(config):
    if source_mode(config) != "emporia":
        return None
    raw = config.get("emporia", {})
    if not isinstance(raw, dict):
        raise ValueError("emporia must be an object")
    result = {
        "token_file": "emporia-tokens.json",
        "poll_interval_seconds": 3,
        "day_interval_seconds": 1800,
        "month_interval_seconds": 21600,
        "timeout_seconds": 10,
        "stale_after_seconds": 30,
        "status_interval_seconds": 15,
        "status_stale_after_seconds": 30,
        "solar_invert": True,
        **raw,
    }
    for key in (
        "poll_interval_seconds",
        "day_interval_seconds",
        "month_interval_seconds",
        "timeout_seconds",
        "stale_after_seconds",
        "status_interval_seconds",
        "status_stale_after_seconds",
    ):
        if not finite(result[key]) or result[key] < 1:
            raise ValueError(f"emporia.{key} must be a finite number >= 1")
    for ttl, interval in (
        ("stale_after_seconds", "poll_interval_seconds"),
        ("status_stale_after_seconds", "status_interval_seconds"),
    ):
        if result[ttl] <= result[interval]:
            raise ValueError(f"emporia.{ttl} must exceed {interval}")
    if not isinstance(result["solar_invert"], bool):
        raise ValueError("emporia.solar_invert must be a boolean")
    for key in ("token_file", "credentials_file"):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()):
            raise ValueError(f"emporia.{key} must be a nonempty path")
    channels = config.get("channels", [])
    if not isinstance(channels, list) or not all(isinstance(c, dict) for c in channels):
        raise ValueError("channels must be a list of objects")
    identities, services, instances, devices = set(), set(), set(), set()
    for channel in channels:
        identity = channel_id(channel)
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("Each channel needs a unique id or ha_entity_id")
        identities.add(identity)
        service = channel.get("service_name")
        if (
            not isinstance(service, str)
            or not service.startswith("com.victronenergy.acload.")
            or service in services
        ):
            raise ValueError("Each channel needs a unique com.victronenergy.acload service_name")
        services.add(service)
        instance = channel.get("instance")
        if (
            isinstance(instance, bool)
            or not isinstance(instance, int)
            or instance < 0
            or instance in instances
        ):
            raise ValueError("Each channel needs a unique nonnegative instance")
        instances.add(instance)
        gid, number = channel.get("emporia_device_gid"), channel.get("emporia_channel")
        if isinstance(gid, bool) or not isinstance(gid, int) or gid <= 0:
            raise ValueError("Each channel needs a positive emporia_device_gid")
        if not isinstance(number, str) or not number.strip():
            raise ValueError("Each channel needs a nonempty emporia_channel")
        if (gid, number) in devices:
            raise ValueError("Duplicate Emporia channel")
        devices.add((gid, number))
        multiplier = channel.get("power_multiplier", 1)
        if not finite(multiplier) or multiplier == 0:
            raise ValueError("power_multiplier must be a finite nonzero number")
        for key in ("emporia_import_channel", "emporia_export_channel"):
            if key in channel and (not isinstance(channel[key], str) or not channel[key]):
                raise ValueError(f"{key} must be a nonempty channel number")
    return result


class EmporiaChannel:
    """Publish direct readings with independent power and energy freshness."""

    def __init__(self, service, config, stale_after=None, energy_fields=None):
        self.service = service
        self.max_age = stale_after or config["stale_after_seconds"]
        self._sample = None
        self._deadline = 0.0
        self._watermark = None
        self._energy = {}
        self._energy_watermarks = {}
        self._energy_ttl = {
            field: config[f"{field.rsplit('_', 1)[1]}_interval_seconds"] * 2 + 30
            for field in (energy_fields or ("energy_day", "energy_month"))
        }

    def _fresh_until(self, timestamp, max_age):
        if not finite(timestamp):
            return None
        age = time.time() - timestamp
        if not -5 <= age < max_age:
            return None
        return time.monotonic() + max_age - max(0, age)

    def update(self, sample):
        if (
            finite(sample.timestamp)
            and self._watermark is not None
            and sample.timestamp < self._watermark
        ):
            return
        deadline = self._fresh_until(sample.timestamp, self.max_age)
        if deadline is not None:
            self._watermark = sample.timestamp
        if deadline is None or not finite(sample.power):
            self.unavailable()
            return
        if self._sample and sample.timestamp == self._sample.timestamp:
            deadline = min(deadline, self._deadline)
        self._sample, self._deadline = sample, deadline
        self.refresh()

    def unavailable(self):
        self._sample, self._deadline = None, 0.0
        self.refresh()

    def refresh(self):
        sample = self._sample if time.monotonic() < self._deadline else None
        self.service.publish_measurement(sample, "emporia" if sample else "unavailable")
        for field in self._energy_ttl:
            value = self._energy.get(field)
            if value and value[2] <= time.monotonic():
                value = None
            self.service.publish_energy(
                field, value[0] if value else None, value[1] if value else None
            )

    def update_energy(self, field, value, timestamp):
        if field not in self._energy_ttl:
            raise ValueError("Unknown energy field")
        previous = self._energy.get(field)
        watermark = self._energy_watermarks.get(field)
        if finite(timestamp) and watermark is not None and timestamp < watermark:
            return
        deadline = self._fresh_until(timestamp, self._energy_ttl[field])
        if deadline is not None:
            self._energy_watermarks[field] = timestamp
        if deadline is None or not finite(value):
            self._energy.pop(field, None)
        else:
            if previous and timestamp == previous[1]:
                deadline = min(deadline, previous[2])
            self._energy[field] = (value, timestamp, deadline)
        self.refresh()

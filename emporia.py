"""Read Emporia measurements with a single background worker."""

import asyncio
import json
import logging
import math
import os
import stat
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sources import Measurement

LOG = logging.getLogger(__name__)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _timestamp(value: Any) -> float | None:
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            return None
        result = value.timestamp()
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, OverflowError, OSError):
        return None


def _read_private_json(path: str) -> dict:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "r") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise PermissionError("Emporia credential files must have mode 0600")
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Invalid Emporia credential file")
    return data


def _write_private_json(path: str, data: dict) -> None:
    target = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _auth_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return response.get("Error", {}).get("Code") == "NotAuthorizedException"
    return getattr(response, "status_code", None) in (401, 403)


class EmporiaClient:
    def __init__(
        self,
        config: dict,
        channels: list[dict],
        publish: Callable,
        unavailable: Callable,
        publish_energy: Callable | None = None,
    ):
        self.config = config
        self.channels = [
            channel
            for channel in channels
            if channel.get("emporia_device_gid") is not None
            and channel.get("emporia_channel") is not None
        ]
        self.device_gids = sorted({channel["emporia_device_gid"] for channel in self.channels})
        self.publish = publish
        self.unavailable = unavailable
        self.publish_energy = publish_energy
        self.poll_interval = config.get("poll_interval_seconds", 3.0)
        self.day_interval = config.get("day_interval_seconds", 1800.0)
        self.month_interval = config.get("month_interval_seconds", 21600.0)
        self.status_interval = config.get("status_interval_seconds", 15.0)
        self.status_max_age = config.get("status_stale_after_seconds", 30.0)
        self.timeout = config.get("timeout_seconds", 10.0)
        self._auth: Any = None
        self._api_template = ""
        self._api_status_path = "customers/devices/status"
        self._channel_info: dict[tuple[str, str], dict] = {}
        self._device_status: dict[str, bool] = {}
        self._status_timestamp: float | None = None
        self._next_status = 0.0
        self._status_failures = 0
        self._username: str | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    def _store_tokens(self, tokens: dict) -> None:
        data = {
            key: tokens[key]
            for key in ("id_token", "access_token", "refresh_token", "token_type")
            if key in tokens
        }
        if self._username:
            data["username"] = self._username
        _write_private_json(self.config["token_file"], data)

    def _connect(self) -> None:
        from botocore import UNSIGNED
        from botocore.config import Config
        from pycognito import Cognito
        from pyemvue.auth import CLIENT_ID, USER_POOL, Auth
        from pyemvue.pyemvue import (
            API_CUSTOMER_DEVICES,
            API_DEVICES_USAGE,
            API_GET_STATUS,
            API_ROOT,
        )

        self._api_template = API_DEVICES_USAGE
        self._api_status_path = API_GET_STATUS
        try:
            tokens = _read_private_json(self.config["token_file"])
        except FileNotFoundError:
            tokens = {}
        credentials = {}
        if self.config.get("credentials_file"):
            credentials = _read_private_json(self.config["credentials_file"])
        username = credentials.get("username") or os.environ.get("EMPORIA_USERNAME")
        password = credentials.get("password") or os.environ.get("EMPORIA_PASSWORD")
        self._username = tokens.get("username") or username
        have_tokens = all(
            isinstance(tokens.get(key), str) and tokens[key]
            for key in ("id_token", "access_token", "refresh_token")
        )
        have_credentials = (
            isinstance(username, str)
            and bool(username)
            and isinstance(password, str)
            and bool(password)
        )
        if not have_tokens and not have_credentials:
            raise ValueError("Emporia tokens or credentials are required")

        def authenticate(use_tokens: bool):
            auth = Auth(
                host=API_ROOT,
                connect_timeout=self.timeout,
                read_timeout=self.timeout,
                token_updater=self._store_tokens,
                max_retry_attempts=1,
                max_retry_delay=0,
            )
            auth.cognito = Cognito(
                USER_POOL,
                CLIENT_ID,
                user_pool_region="us-east-2",
                username=username.lower() if username else None,
                id_token=tokens.get("id_token") if use_tokens else None,
                access_token=tokens.get("access_token") if use_tokens else None,
                refresh_token=tokens.get("refresh_token") if use_tokens else None,
                botocore_config=Config(
                    signature_version=UNSIGNED,
                    connect_timeout=self.timeout,
                    read_timeout=self.timeout,
                    retries={"total_max_attempts": 1},
                ),
            )
            if not use_tokens:
                auth.cognito.authenticate(password=password)
            auth.refresh_tokens()
            return auth

        try:
            self._auth = authenticate(have_tokens)
        except Exception as error:
            if not have_tokens or not have_credentials or not _auth_error(error):
                raise
            self._auth = authenticate(False)
        try:
            response = self._auth.request("get", API_CUSTOMER_DEVICES)
            response.raise_for_status()
            self._load_channels(response.json())
        except Exception:
            self._auth = None
            raise

    def _load_channels(self, payload: dict) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
            raise ValueError("Invalid Emporia device response")
        info = {}
        devices = list(payload["devices"])
        while devices:
            device = devices.pop()
            if not isinstance(device, dict):
                continue
            if isinstance(device.get("devices"), list):
                devices.extend(device["devices"])
            for channel in device.get("channels", []) or []:
                if isinstance(channel, dict) and channel.get("channelNum") is not None:
                    info[(str(device.get("deviceGid")), str(channel["channelNum"]))] = channel
        self._channel_info = info

    def _signed_usage(self, gid: int, channel: str, usage: float | None) -> float | None:
        if usage is None:
            return None
        metadata = self._channel_info.get((str(gid), channel))
        if metadata is None and channel in (
            "Balance",
            "TotalUsage",
            "MainsFromGrid",
            "MainsToGrid",
        ):
            main = self._channel_info.get((str(gid), "1,2,3"), {})
            metadata = {"channelTypeGid": main.get("channelTypeGid", 1)}
        if metadata is None:
            return None
        if metadata.get("channelTypeGid") == 13:
            return -usage if self.config.get("solar_invert", True) else usage
        if (
            channel in ("1,2,3", "Balance")
            or "bidirectional" in str(metadata.get("type", "")).lower()
        ):
            return usage
        return abs(usage)

    def _usage(self, scale: str) -> tuple[float | None, dict]:
        if self._auth is None:
            self._connect()
        instant = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        path = self._api_template.format(
            deviceGids="+".join(map(str, self.device_gids)),
            instant=instant,
            scale=scale,
            unit="KilowattHours",
        )
        response = self._auth.request("get", path)
        response.raise_for_status()
        payload = response.json().get("deviceListUsages")
        if not isinstance(payload, dict) or not isinstance(payload.get("devices"), list):
            raise ValueError("Invalid Emporia usage response")
        timestamp = _timestamp(payload.get("instant"))
        readings = {}
        devices = list(payload["devices"])
        while devices:
            device = devices.pop()
            if not isinstance(device, dict):
                continue
            gid = device.get("deviceGid")
            channels = device.get("channelUsages")
            if not isinstance(channels, list):
                continue
            for channel in channels:
                if not isinstance(channel, dict):
                    continue
                if isinstance(channel.get("nestedDevices"), list):
                    devices.extend(channel["nestedDevices"])
                readings[(str(gid), str(channel.get("channelNum")))] = _number(channel.get("usage"))
        return timestamp, readings

    def _refresh_status(self) -> None:
        now = time.monotonic()
        if now < self._next_status:
            return
        self._next_status = now + self.status_interval
        try:
            if self._auth is None:
                self._connect()
            response = self._auth.request("get", self._api_status_path)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("devicesConnected"), list
            ):
                raise ValueError("Invalid Emporia status response")
            statuses = {}
            for device in payload["devicesConnected"]:
                if (
                    isinstance(device, dict)
                    and device.get("deviceGid") is not None
                    and isinstance(device.get("connected"), bool)
                ):
                    statuses[str(device["deviceGid"])] = device["connected"]
            self._device_status = statuses
            self._status_timestamp = time.monotonic()
            self._status_failures = 0
        except Exception as error:  # noqa: BLE001 - Unknown device status must fail closed.
            self._device_status = {}
            self._status_timestamp = None
            self._status_failures += 1
            self._next_status = time.monotonic() + min(
                300.0, self.status_interval * 2 ** min(self._status_failures - 1, 6)
            )
            if _auth_error(error):
                self._auth = None
            LOG.warning("Emporia status request failed (%s)", type(error).__name__)

    def _online(self, gid: int) -> bool:
        return (
            self._status_timestamp is not None
            and 0 <= time.monotonic() - self._status_timestamp <= self.status_max_age
            and self._device_status.get(str(gid)) is True
        )

    def poll_power(self) -> dict[str, Measurement]:
        self._refresh_status()
        timestamp, readings = (
            self._usage("1S") if any(self._online(gid) for gid in self.device_gids) else (None, {})
        )
        result = {}
        for channel in self.channels:
            gid = channel["emporia_device_gid"]
            number = str(channel["emporia_channel"])
            usage = self._signed_usage(gid, number, readings.get((str(gid), number)))
            power = (
                _number(usage * 3_600_000 * channel.get("power_multiplier", 1.0))
                if usage is not None and timestamp is not None and self._online(gid)
                else None
            )
            result[channel["id"]] = Measurement(
                power=power, timestamp=timestamp, device_gid=gid, channel_num=number
            )
        return result

    def poll_energy(self, period: str) -> dict[str, dict]:
        scale = {"day": "1D", "month": "1MON"}[period]
        timestamp, readings = self._usage(scale)
        result = {}
        for channel in self.channels:
            gid, number = channel["emporia_device_gid"], str(channel["emporia_channel"])
            values = {"timestamp": timestamp}
            energy_channels = {f"energy_{period}": number}
            for direction in ("import", "export"):
                directional_channel = channel.get(f"emporia_{direction}_channel")
                if directional_channel is not None:
                    energy_channels[f"energy_{direction}_{period}"] = str(directional_channel)
            for field, energy_channel in energy_channels.items():
                usage = self._signed_usage(
                    gid, energy_channel, readings.get((str(gid), energy_channel))
                )
                values[field] = (
                    _number(usage * channel.get("power_multiplier", 1.0))
                    if usage is not None and timestamp is not None
                    else None
                )
            result[channel["id"]] = values
        return result

    def _work(self, emit: Callable) -> None:
        next_energy = {"day": 0.0, "month": 0.0}
        energy_intervals = {"day": self.day_interval, "month": self.month_interval}
        failures = 0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                emit(self.publish, self.poll_power())
            except Exception as error:  # noqa: BLE001 - Keep the worker running.
                if _auth_error(error):
                    self._auth = None
                failures += 1
                LOG.warning("Emporia power request failed (%s)", type(error).__name__)
                emit(self.unavailable)
                self._stop.wait(
                    min(300.0, max(5.0, self.poll_interval) * 2 ** min(failures - 1, 6))
                )
                continue
            failures = 0
            for period in ("day", "month"):
                if self._stop.is_set():
                    break
                if self._auth is None and self._status_failures:
                    continue
                if self.publish_energy and time.monotonic() >= next_energy[period]:
                    try:
                        emit(self.publish_energy, self.poll_energy(period))
                    except Exception as error:  # noqa: BLE001 - Energy does not gate power.
                        LOG.warning("Emporia %s request failed (%s)", period, type(error).__name__)
                    next_energy[period] = time.monotonic() + energy_intervals[period]
            self._stop.wait(max(0.0, self.poll_interval - (time.monotonic() - started)))

    async def run(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            raise RuntimeError("Emporia worker is already running")
        self._stop = threading.Event()
        stop = self._stop
        loop = asyncio.get_running_loop()

        def deliver(callback, args):
            if not stop.is_set():
                callback(*args)

        def emit(callback, *args):
            if not stop.is_set():
                try:
                    loop.call_soon_threadsafe(deliver, callback, args)
                except RuntimeError:
                    stop.set()

        self._worker = threading.Thread(
            target=self._work, args=(emit,), name="emporia-poll", daemon=True
        )
        self._worker.start()
        try:
            await asyncio.Future()
        finally:
            stop.set()

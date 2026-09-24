"""Read-only, minimal tariff reference for the dashboard spreadsheet editor."""

import math
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def tariff_reference(properties: dict, currency: str) -> dict:
    """Do not turn a utility plan's placeholder flat price into a TOU schedule."""
    if not isinstance(properties, dict):
        raise ValueError("Invalid Emporia location properties")
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise ValueError("Currency must be a three-letter code")
    timezone = properties.get("timeZone")
    try:
        if not isinstance(timezone, str) or not timezone:
            raise ValueError("Emporia did not provide a time zone")
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("Emporia returned an unknown time zone") from error
    utility = properties.get("utilityRateGid")
    if utility is not None and (isinstance(utility, bool) or not isinstance(utility, (int, str))):
        raise ValueError("Invalid Emporia utility rate identifier")
    utility = str(utility) if utility not in (None, "", 0, "0") else ""
    cents = properties.get("usageCentPerKwHour")
    flat_rate = None
    if not utility and cents is not None:
        if (
            isinstance(cents, bool)
            or not isinstance(cents, (int, float))
            or not math.isfinite(cents)
        ):
            raise ValueError("Invalid Emporia flat energy rate")
        flat_rate = cents / 100
    name = properties.get("deviceName") or properties.get("displayName") or "Emporia tariff"
    if not isinstance(name, str):
        raise ValueError("Invalid Emporia device name")
    # Whitelist only tariff fields. No account IDs, location, or credentials.
    return {
        "type": "emporia-tariff-reference",
        "version": 1,
        "name": name[:120],
        "currency": currency.upper(),
        "timeZone": timezone,
        "utilityRateGid": utility,
        "flatRate": flat_rate,
        "exportedAt": datetime.now(UTC).isoformat(),
    }


def read_tariff_reference(client, device_gid: int, currency: str) -> dict:
    """Use the configured client's authenticated session, with no API writes."""
    # Reuse the driver's token refresh and session instead of a second login flow.
    # pylint: disable=protected-access
    if (
        isinstance(device_gid, bool)
        or not isinstance(device_gid, int)
        or device_gid not in client.device_gids
    ):
        raise ValueError("Select a device configured in dbus-emporia-vue")
    if client._auth is None:
        client._connect()
    response = client._auth.request("get", f"devices/{device_gid}/locationProperties")
    response.raise_for_status()
    return tariff_reference(response.json(), currency)

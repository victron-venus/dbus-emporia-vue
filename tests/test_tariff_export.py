from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tariff_export import read_tariff_reference, tariff_reference


def properties(**patch):
    return {
        "timeZone": "America/Los_Angeles",
        "deviceName": "Test home",
        "usageCentPerKwHour": 31,
        **patch,
    }


def test_flat_rate_uses_currency_units_and_excludes_private_fields():
    result = tariff_reference(properties(username="private", latitude=1, id_token="secret"), "usd")
    assert result["flatRate"] == 0.31
    assert result["currency"] == "USD"
    assert set(result) == {
        "type",
        "version",
        "name",
        "currency",
        "timeZone",
        "utilityRateGid",
        "flatRate",
        "exportedAt",
    }


def test_utility_plan_never_imports_placeholder_flat_rate():
    result = tariff_reference(properties(utilityRateGid=1234), "USD")
    assert result["utilityRateGid"] == "1234"
    assert result["flatRate"] is None


@pytest.mark.parametrize("rate", [True, "31", float("nan"), float("inf")])
def test_invalid_flat_rates_fail_closed(rate):
    with pytest.raises(ValueError):
        tariff_reference(properties(usageCentPerKwHour=rate), "USD")


def test_missing_rate_is_not_free_and_zero_is_preserved():
    assert tariff_reference(properties(usageCentPerKwHour=None), "USD")["flatRate"] is None
    assert tariff_reference(properties(usageCentPerKwHour=0), "USD")["flatRate"] == 0


def test_export_only_reads_selected_configured_device():
    auth = Mock()
    auth.request.return_value.json.return_value = properties()
    client = SimpleNamespace(device_gids=[42], _auth=auth)
    assert read_tariff_reference(client, 42, "USD")["flatRate"] == 0.31
    auth.request.assert_called_once_with("get", "devices/42/locationProperties")
    with pytest.raises(ValueError):
        read_tariff_reference(client, 43, "USD")

import json
import stat
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import export_tariff
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
    source = properties(usageCentPerKwHour=rate)
    with pytest.raises(ValueError):
        tariff_reference(source, "USD")


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


@pytest.mark.parametrize(
    "filename",
    ["../export.json", "/tmp/export.json", "nested/export.json", "tokens", "..\\export.json"],
)
def test_export_filename_cannot_escape_working_directory(filename):
    with pytest.raises(ValueError):
        export_tariff.export_path(filename)


def test_cli_writes_private_export_and_preserves_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"channels": []}))
    monkeypatch.setattr(export_tariff, "emporia_config", lambda _: {})
    monkeypatch.setattr(export_tariff, "EmporiaClient", Mock())
    monkeypatch.setattr(
        export_tariff, "read_tariff_reference", lambda *_: tariff_reference(properties(), "USD")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_tariff.py",
            "--config",
            str(config),
            "--device-gid",
            "42",
            "--currency",
            "USD",
            "--output",
            "export.json",
        ],
    )
    assert export_tariff.main() == 0
    output = tmp_path / "export.json"
    original = output.read_bytes()
    assert json.loads(original)["flatRate"] == 0.31
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert export_tariff.main() == 1
    assert output.read_bytes() == original

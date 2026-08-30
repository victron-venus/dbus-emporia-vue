"""Tests for ha_config_gen.py — URL conversion + state filtering + config emit."""

import json
from unittest.mock import MagicMock, patch

import pytest

import ha_config_gen

# ---------------------------------------------------------------------------
# ha_url_to_rest
# ---------------------------------------------------------------------------


class TestHaUrlToRest:
    def test_ws_to_http(self):
        assert ha_config_gen.ha_url_to_rest("ws://h:8123/api/websocket") == "http://h:8123/api"

    def test_wss_to_https(self):
        assert ha_config_gen.ha_url_to_rest("wss://h:8123/api/websocket") == "https://h:8123/api"

    def test_already_http_unchanged(self):
        assert ha_config_gen.ha_url_to_rest("http://h:8123/api") == "http://h:8123/api"

    def test_https_unchanged(self):
        assert ha_config_gen.ha_url_to_rest("https://h:8123/api") == "https://h:8123/api"

    def test_no_api_suffix_appends(self):
        assert ha_config_gen.ha_url_to_rest("ws://h:8123") == "http://h:8123/api"

    def test_trailing_slash_normalized(self):
        assert ha_config_gen.ha_url_to_rest("ws://h:8123/") == "http://h:8123/api"

    def test_websocket_suffix_stripped(self):
        assert ha_config_gen.ha_url_to_rest("ws://h:8123/api/websocket") == "http://h:8123/api"


# ---------------------------------------------------------------------------
# fetch_json
# ---------------------------------------------------------------------------


class TestFetchJson:
    def test_returns_parsed_json(self):
        body = json.dumps({"foo": "bar"}).encode()
        fake_resp = MagicMock()
        fake_resp.read = MagicMock(return_value=body)
        fake_resp.__enter__ = MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = MagicMock(return_value=False)
        with patch("ha_config_gen.urlopen", return_value=fake_resp):
            result = ha_config_gen.fetch_json("ws://h:8123/api/websocket", "tok", "/states")
            assert result == {"foo": "bar"}

    def test_http_error_returns_none(self, capsys):
        from urllib.error import HTTPError

        err = HTTPError("http://h:8123/api/states", 401, "Unauthorized", {}, None)
        with patch("ha_config_gen.urlopen", side_effect=err):
            assert ha_config_gen.fetch_json("ws://h:8123/api/websocket", "tok", "/states") is None
        assert "HTTP error: 401" in capsys.readouterr().err

    def test_url_error_returns_none(self, capsys):
        from urllib.error import URLError

        with patch("ha_config_gen.urlopen", side_effect=URLError("dns")):
            assert ha_config_gen.fetch_json("ws://h:8123/api/websocket", "tok", "/states") is None
        assert "URL error" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def _state(entity_id, state, unit=None, friendly=None):
    s = {"entity_id": entity_id, "state": state, "attributes": {}}
    if unit is not None:
        s["attributes"]["unit_of_measurement"] = unit
    if friendly is not None:
        s["attributes"]["friendly_name"] = friendly
    return s


def test_main_missing_env_exits(capsys, monkeypatch):
    monkeypatch.delenv("HA_URL", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    with pytest.raises(SystemExit) as exc:
        ha_config_gen.main()
    assert exc.value.code == 1
    assert "HA_URL" in capsys.readouterr().err


def test_main_no_power_sensors_exits(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HA_URL", "ws://h:8123/api/websocket")
    monkeypatch.setenv("HA_TOKEN", "tok")
    monkeypatch.chdir(tmp_path)
    with patch("ha_config_gen.fetch_json", return_value=[]):
        with pytest.raises(SystemExit) as exc:
            ha_config_gen.main()
    assert exc.value.code == 1
    assert "No power sensors" in capsys.readouterr().err


def test_main_fetch_returns_none_exits(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HA_URL", "ws://h:8123/api/websocket")
    monkeypatch.setenv("HA_TOKEN", "tok")
    monkeypatch.chdir(tmp_path)
    with patch("ha_config_gen.fetch_json", return_value=None):
        with pytest.raises(SystemExit) as exc:
            ha_config_gen.main()
    assert exc.value.code == 1


def test_main_filters_and_writes_config(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HA_URL", "ws://h:8123/api/websocket")
    monkeypatch.setenv("HA_TOKEN", "tok")
    monkeypatch.chdir(tmp_path)

    states = [
        # Included: W + _1s
        _state("sensor.ch1_1s", "10", unit="W", friendly="Channel 1"),
        _state("sensor.ch2_1s", "20", unit="W", friendly="Channel 2"),
        # Excluded: not W
        _state("sensor.volts_1s", "120", unit="V"),
        # Excluded: W but no _1s suffix
        _state("sensor.ch3", "30", unit="W"),
        # Excluded: not a sensor
        _state("binary_sensor.something", "off"),
    ]
    with patch("ha_config_gen.fetch_json", return_value=states):
        ha_config_gen.main()

    out = json.loads((tmp_path / "config.json").read_text())
    assert out["ha_url"] == "ws://h:8123/api/websocket"
    assert out["ha_token"] == "tok"
    assert out["stale_timeout"] == 15
    assert out["update_interval"] == 1
    assert len(out["channels"]) == 2
    # Sorted alphabetically by entity_id
    assert out["channels"][0]["ha_entity_id"] == "sensor.ch1_1s"
    assert out["channels"][1]["ha_entity_id"] == "sensor.ch2_1s"
    # Instance assignment starts at 71 and increments
    assert out["channels"][0]["instance"] == 71
    assert out["channels"][1]["instance"] == 72
    # Friendly name used as custom_name
    assert out["channels"][0]["custom_name"] == "Channel 1"
    # Service names
    assert out["channels"][0]["service_name"] == "com.victronenergy.acload.emporia_ch1"
    assert out["channels"][1]["service_name"] == "com.victronenergy.acload.emporia_ch2"
    # Default position 0
    assert all(c["position"] == 0 for c in out["channels"])


def test_main_no_instantaneous_exits(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HA_URL", "ws://h:8123/api/websocket")
    monkeypatch.setenv("HA_TOKEN", "tok")
    monkeypatch.chdir(tmp_path)
    # Has W sensors but none with _1s suffix
    states = [_state("sensor.ch1", "10", unit="W")]
    with patch("ha_config_gen.fetch_json", return_value=states):
        with pytest.raises(SystemExit) as exc:
            ha_config_gen.main()
    assert exc.value.code == 1
    assert "No power sensors found for the specified device" in capsys.readouterr().err

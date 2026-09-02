"""Tests for openblockperf.config

Covers:
- Network enum values
- NetworkConfig per network
- AppSettings defaults and SRV/API override fields
"""

import pytest

from pydantic import ValidationError

from openblockperf.config import DEFAULT_API_SRV, AppSettings, Network


class TestNetworkEnum:
    def test_three_networks_defined(self):
        assert len(Network) == 3

    def test_mainnet_value(self):
        assert Network.MAINNET.value == "mainnet"

    def test_preprod_value(self):
        assert Network.PREPROD.value == "preprod"

    def test_preview_value(self):
        assert Network.PREVIEW.value == "preview"


class TestNetworkConfig:
    """Each network has a distinct magic number."""

    def test_mainnet_magic(self, default_settings):
        assert default_settings.network_config.magic == 764824073

    def test_preprod_magic(self, preprod_settings):
        assert preprod_settings.network_config.magic == 1

    def test_preview_magic(self):
        s = AppSettings(network=Network.PREVIEW)
        assert s.network_config.magic == 2

    def test_mainnet_starttime(self, default_settings):
        # Shelley genesis: Sun Jun 07 2020 21:44:51 UTC
        assert default_settings.network_config.starttime == 1591566291


class TestSettingsDefaults:
    def test_default_network_is_mainnet(self, default_settings):
        assert default_settings.network == Network.MAINNET

    def test_default_local_port(self, default_settings):
        assert default_settings.local_port == 3001

    def test_default_check_interval(self, default_settings):
        assert default_settings.block_sample_check_interval == 2

    def test_default_api_srv(self, default_settings):
        assert default_settings.api_srv == DEFAULT_API_SRV
        assert default_settings.api_srv == "_obpf._tcp.network.cardano.org"

    def test_api_url_default_is_none(self, default_settings):
        assert default_settings.api_url is None

    def test_default_api_request_timeout_is_1000ms(self, default_settings):
        assert default_settings.api_request_timeout_ms == 1000

    def test_default_api_request_retries_is_two(self, default_settings):
        assert default_settings.api_request_retries == 2

    def test_default_peer_count_stats_interval_is_300(self, default_settings):
        assert default_settings.peer_count_stats_interval == 300


class TestSettingsOverrides:
    def test_network_override_enum(self):
        s = AppSettings(network=Network.PREPROD)
        assert s.network == Network.PREPROD

    def test_network_override_string(self):
        s = AppSettings(network="preview")
        assert s.network == Network.PREVIEW

    def test_invalid_network_raises(self):
        with pytest.raises(ValidationError):
            AppSettings(network="notanetwork")

    def test_api_url_override_is_stored_as_given(self):
        custom_url = "http://localhost:8000/mainnet/api/v0"
        s = AppSettings(api_url=custom_url)
        assert s.api_url == custom_url

    def test_api_srv_can_be_overridden(self):
        s = AppSettings(api_srv="_obpf._tcp.example.test")
        assert s.api_srv == "_obpf._tcp.example.test"

    def test_api_request_timeout_and_retries_can_be_overridden(self):
        s = AppSettings(api_request_timeout_ms=2500, api_request_retries=4)
        assert s.api_request_timeout_ms == 2500
        assert s.api_request_retries == 4

    def test_api_request_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            AppSettings(api_request_timeout_ms=0)

    def test_peer_count_stats_interval_zero_disables_logging(self):
        s = AppSettings(peer_count_stats_interval=0)
        assert s.peer_count_stats_interval == 0

    def test_peer_count_stats_interval_must_not_be_negative(self):
        with pytest.raises(ValidationError):
            AppSettings(peer_count_stats_interval=-1)

    def test_api_request_settings_load_from_json_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"api_request_timeout_ms": 1500, "api_request_retries": 1}',
            encoding="utf-8",
        )
        s = AppSettings(_config_file=config_file)
        assert s.api_request_timeout_ms == 1500
        assert s.api_request_retries == 1

    def test_peer_count_stats_interval_loads_from_json_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"peer_count_stats_interval": 0}', encoding="utf-8")
        s = AppSettings(_config_file=config_file)
        assert s.peer_count_stats_interval == 0

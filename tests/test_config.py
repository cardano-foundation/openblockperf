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

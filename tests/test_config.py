"""Tests for openblockperf.config

Covers:
- Network enum values
- NetworkConfig per network
- settings() factory: defaults, CLI overrides, error cases
- AppSettings.full_api_url construction
"""

import pytest

from openblockperf.config import AppSettings, Network, settings


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
    """Each network has a distinct magic number and API URL."""

    def test_mainnet_magic(self, default_settings):
        assert default_settings.network_config.magic == 764824073

    def test_preprod_magic(self, preprod_settings):
        assert preprod_settings.network_config.magic == 1

    def test_preview_magic(self):
        s = settings(network=Network.PREVIEW)
        assert s.network_config.magic == 2

    def test_mainnet_starttime(self, default_settings):
        # Shelley genesis: Sun Jun 07 2020 21:44:51 UTC
        assert default_settings.network_config.starttime == 1591566291

    # TODO: add tests for preprod / preview starttimes


class TestSettingsDefaults:
    def test_default_network_is_mainnet(self, default_settings):
        assert default_settings.network == Network.MAINNET

    def test_default_api_port(self, default_settings):
        assert default_settings.api_port == 443

    def test_default_local_port(self, default_settings):
        assert default_settings.local_port == 3001

    def test_default_check_interval(self, default_settings):
        assert default_settings.check_interval == 2

    # TODO: test that min_age default is 10


class TestSettingsFactory:
    def test_network_override_enum(self):
        s = settings(network=Network.PREPROD)
        assert s.network == Network.PREPROD

    def test_network_override_string(self):
        s = settings(network="preview")
        assert s.network == Network.PREVIEW

    def test_invalid_network_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid network"):
            settings(network="notanetwork")

    def test_api_url_override_bypasses_network_url(self):
        custom_url = "http://localhost:9000/api/"
        s = settings(api_url_override=custom_url)
        assert s.full_api_url == custom_url

    def test_api_url_override_takes_precedence_over_network(self):
        custom_url = "http://localhost:9000"
        s = settings(network=Network.PREPROD, api_url_override=custom_url)
        assert s.full_api_url == custom_url

    # TODO: test env var OPENBLOCKPERF_NETWORK overrides default
    # TODO: test env var OPENBLOCKPERF_API_KEY is picked up


class TestFullApiUrl:
    def test_mainnet_url_contains_expected_domain(self, default_settings):
        assert "openblockperf.cardano.org" in default_settings.full_api_url

    def test_preprod_url_contains_preprod(self, preprod_settings):
        assert "preprod" in preprod_settings.full_api_url

    def test_url_includes_port(self, default_settings):
        assert str(default_settings.api_port) in default_settings.full_api_url

    def test_url_includes_api_path(self, default_settings):
        assert default_settings.api_path in default_settings.full_api_url

    # TODO: test that a non-default api_port is reflected in full_api_url

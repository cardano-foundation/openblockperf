"""Tests for openblockperf.models.peer

Covers:
- PeerConnectionString: IPv4 and IPv6 parsing, error cases
- PeerConnectionSimple: nested dict parsing
- PeerState / PeerDirection enums
"""

import pytest
from pydantic import ValidationError

from openblockperf.models.peer import (
    PeerConnectionSimple,
    PeerConnectionString,
    PeerDirection,
    PeerState,
)


class TestPeerConnectionStringIPv4:
    def test_parses_local_addr(self):
        conn = PeerConnectionString.model_validate("192.168.1.1:3001 10.0.0.1:443")
        assert conn.local_addr == "192.168.1.1"

    def test_parses_local_port(self):
        conn = PeerConnectionString.model_validate("192.168.1.1:3001 10.0.0.1:443")
        assert conn.local_port == 3001

    def test_parses_remote_addr(self):
        conn = PeerConnectionString.model_validate("192.168.1.1:3001 10.0.0.1:443")
        assert conn.remote_addr == "10.0.0.1"

    def test_parses_remote_port(self):
        conn = PeerConnectionString.model_validate("192.168.1.1:3001 10.0.0.1:443")
        assert conn.remote_port == 443

    def test_real_world_example(self):
        conn = PeerConnectionString.model_validate("172.0.118.125:30002 167.235.223.34:5355")
        assert conn.remote_addr == "167.235.223.34"
        assert conn.remote_port == 5355


class TestPeerConnectionStringIPv6:
    def test_parses_ipv6_remote_addr(self):
        conn = PeerConnectionString.model_validate("[2001:db8::1]:3001 [::1]:443")
        assert conn.remote_addr == "::1"

    def test_parses_ipv6_local_addr(self):
        conn = PeerConnectionString.model_validate("[2001:db8::1]:3001 [::1]:443")
        assert conn.local_addr == "2001:db8::1"

    def test_parses_ipv6_ports(self):
        conn = PeerConnectionString.model_validate("[2001:db8::1]:3001 [::1]:443")
        assert conn.local_port == 3001
        assert conn.remote_port == 443

    # TODO: mixed IPv4/IPv6 in a single connection string


class TestPeerConnectionStringErrors:
    def test_non_string_raises(self):
        with pytest.raises(Exception):
            PeerConnectionString.model_validate({"local": "10.0.0.1"})

    # TODO: malformed string (no space separator)
    # TODO: invalid port number (non-numeric)
    # TODO: IPv6 missing closing bracket


class TestPeerConnectionSimple:
    def test_parses_from_nested_dict(self):
        data = {"connectionId": "172.0.118.125:30002 167.235.223.34:5355"}
        conn = PeerConnectionSimple.model_validate(data)
        assert conn.connectionId.remote_addr == "167.235.223.34"
        assert conn.connectionId.remote_port == 5355

    def test_local_addr_accessible(self):
        data = {"connectionId": "172.0.118.125:30002 167.235.223.34:5355"}
        conn = PeerConnectionSimple.model_validate(data)
        assert conn.connectionId.local_addr == "172.0.118.125"
        assert conn.connectionId.local_port == 30002

    # TODO: missing connectionId key should raise ValidationError


class TestPeerStateEnum:
    def test_all_expected_states_present(self):
        expected = {"Unknown", "Unconnected", "Cold", "Warm", "Hot", "Cooling"}
        actual = {s.value for s in PeerState}
        assert actual == expected

    # TODO: test state transition ordering if a helper is added


class TestPeerDirectionEnum:
    def test_inbound_value(self):
        assert PeerDirection.INBOUND.value == "inbound"

    def test_outbound_value(self):
        assert PeerDirection.OUTBOUND.value == "outbound"

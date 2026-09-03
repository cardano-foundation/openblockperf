"""Tests for hardcoded and configured IP obfuscation."""

from openblockperf.ip_obfuscate import OBFUSCATED_IP, obfuscate_ip, should_obfuscate_ip


def test_private_ipv4_ranges_are_obfuscated():
    for addr in ("10.0.0.5", "172.16.3.1", "192.168.1.10", "127.0.0.1", "169.254.1.1"):
        assert should_obfuscate_ip(addr) is True
        assert obfuscate_ip(addr) == OBFUSCATED_IP


def test_public_ipv4_is_kept():
    assert should_obfuscate_ip("8.8.8.8") is False
    assert obfuscate_ip("8.8.8.8") == "8.8.8.8"


def test_private_ipv6_ranges_are_obfuscated():
    for addr in ("::1", "fc00::1", "fd12:3456:789a::1", "fe80::1"):
        assert should_obfuscate_ip(addr) is True
        assert obfuscate_ip(addr) == OBFUSCATED_IP


def test_public_ipv6_is_kept():
    assert obfuscate_ip("2001:4860:4860::8888") == "2001:4860:4860::8888"


def test_extra_obfuscate_ips_match_exact_and_normalized():
    extra = ["203.0.113.10", " 2001:db8::1 "]
    assert obfuscate_ip("203.0.113.10", extra) == OBFUSCATED_IP
    assert obfuscate_ip("2001:db8::1", extra) == OBFUSCATED_IP
    assert obfuscate_ip("1.1.1.1", extra) == "1.1.1.1"


def test_already_obfuscated_stays_zero():
    assert obfuscate_ip("0.0.0.0") == OBFUSCATED_IP

"""Tests for clawrium.core.names module."""

import re

import pytest

from clawrium.core.names import generate_random_name, is_ip_address


class TestGenerateRandomName:
    """Tests for generate_random_name function."""

    def test_returns_adjective_scientist_format(self):
        """generate_random_name returns 'adjective-scientist' format."""
        name = generate_random_name()
        # Should be two parts separated by hyphen
        parts = name.split("-")
        assert len(parts) == 2, f"Expected 'adjective-scientist' format, got '{name}'"
        # Should be lowercase
        assert name == name.lower(), f"Expected lowercase, got '{name}'"

    def test_returns_string(self):
        """generate_random_name returns a string."""
        name = generate_random_name()
        assert isinstance(name, str)

    def test_generates_different_names(self):
        """generate_random_name can produce different results (randomness check)."""
        # Generate 50 names, expect at least 2 different ones
        names = [generate_random_name() for _ in range(50)]
        unique_names = set(names)
        assert len(unique_names) > 1, "Expected randomness in name generation"


class TestIsIpAddress:
    """Tests for is_ip_address function."""

    def test_returns_true_for_valid_ipv4(self):
        """is_ip_address returns True for valid IPv4 addresses."""
        assert is_ip_address("192.168.1.1") is True
        assert is_ip_address("10.0.0.1") is True
        assert is_ip_address("255.255.255.255") is True
        assert is_ip_address("0.0.0.0") is True
        assert is_ip_address("172.16.0.1") is True

    def test_returns_false_for_hostnames(self):
        """is_ip_address returns False for hostnames."""
        assert is_ip_address("hostname") is False
        assert is_ip_address("kevin") is False
        assert is_ip_address("my-server") is False
        assert is_ip_address("localhost") is False

    def test_returns_false_for_incomplete_ips(self):
        """is_ip_address returns False for incomplete IP addresses."""
        assert is_ip_address("192.168.1") is False
        assert is_ip_address("10.0") is False
        assert is_ip_address("1.2.3") is False

    def test_returns_false_for_invalid_formats(self):
        """is_ip_address returns False for invalid formats."""
        assert is_ip_address("") is False
        assert is_ip_address("192.168.1.1.1") is False  # Too many octets
        assert is_ip_address("abc.def.ghi.jkl") is False  # Not digits
        assert (
            is_ip_address("256.1.1.1") is False
        )  # Out of range (though simple regex might allow)

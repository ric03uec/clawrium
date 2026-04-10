"""Tests for clawrium.core.names module."""

from clawrium.core.names import (
    generate_random_name,
    is_ip_address,
    validate_agent_name,
    is_name_available_on_host,
    SCIENTISTS,
)


class TestGenerateRandomName:
    """Tests for generate_random_name function."""

    def test_returns_adjective_scientist_format(self):
        """generate_random_name returns 'adjective-scientist' format."""
        name = generate_random_name()
        parts = name.split("-")
        assert len(parts) == 2, f"Expected 'adjective-scientist' format, got '{name}'"
        assert name == name.lower(), f"Expected lowercase, got '{name}'"

    def test_returns_string(self):
        """generate_random_name returns a string."""
        name = generate_random_name()
        assert isinstance(name, str)

    def test_generates_different_names(self):
        """generate_random_name can produce different results (randomness check)."""
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
        assert is_ip_address("192.168.1.1.1") is False
        assert is_ip_address("abc.def.ghi.jkl") is False
        assert is_ip_address("256.1.1.1") is False


class TestScientistList:
    """Tests for SCIENTISTS list."""

    def test_has_exactly_100_names(self):
        """SCIENTISTS list has exactly 100 names."""
        assert len(SCIENTISTS) == 100, f"Expected 100 scientists, got {len(SCIENTISTS)}"

    def test_all_names_are_lowercase(self):
        """All scientist names are lowercase."""
        for name in SCIENTISTS:
            assert name == name.lower(), f"Scientist name '{name}' is not lowercase"

    def test_all_names_are_unique(self):
        """All scientist names are unique."""
        assert len(SCIENTISTS) == len(set(SCIENTISTS)), (
            "Duplicate scientist names found"
        )


class TestValidateClawName:
    """Tests for validate_agent_name function."""

    def test_valid_simple_names(self):
        """validate_agent_name accepts simple valid names."""
        assert validate_agent_name("work-assistant")[0] is True
        assert validate_agent_name("clever_einstein")[0] is True
        assert validate_agent_name("name123")[0] is True
        assert validate_agent_name("abc-123_xyz")[0] is True

    def test_valid_edge_cases(self):
        """validate_agent_name accepts edge case valid names."""
        assert validate_agent_name("a")[0] is True
        assert validate_agent_name("a" * 32)[0] is True
        assert validate_agent_name("clever-einstein-123")[0] is True

    def test_rejects_empty_name(self):
        """validate_agent_name rejects empty names."""
        valid, msg = validate_agent_name("")
        assert valid is False
        assert "empty" in msg.lower()

    def test_rejects_too_long_name(self):
        """validate_agent_name rejects names longer than 32 characters."""
        valid, msg = validate_agent_name("a" * 33)
        assert valid is False
        assert "32" in msg

    def test_rejects_invalid_characters(self):
        """validate_agent_name rejects names with invalid characters."""
        valid, msg = validate_agent_name("work assistant")
        assert valid is False
        assert "lowercase" in msg.lower()

        valid, msg = validate_agent_name("work.assistant")
        assert valid is False
        assert "lowercase" in msg.lower()

        valid, msg = validate_agent_name("work@assistant")
        assert valid is False
        assert "lowercase" in msg.lower()

    def test_rejects_uppercase_letters(self):
        """validate_agent_name rejects names with uppercase letters."""
        valid, msg = validate_agent_name("Name")
        assert valid is False
        assert "lowercase" in msg.lower()

        valid, msg = validate_agent_name("UPPER")
        assert valid is False
        assert "lowercase" in msg.lower()

        valid, msg = validate_agent_name("MyAssistant")
        assert valid is False
        assert "lowercase" in msg.lower()

    def test_rejects_names_starting_with_digit(self):
        """validate_agent_name rejects names starting with a digit."""
        valid, msg = validate_agent_name("1bad")
        assert valid is False
        assert "start with a lowercase letter" in msg

        valid, msg = validate_agent_name("123claw")
        assert valid is False
        assert "start with a lowercase letter" in msg

    def test_rejects_names_starting_with_hyphen(self):
        """validate_agent_name rejects names starting with a hyphen."""
        valid, msg = validate_agent_name("-bad")
        assert valid is False
        assert "start with a lowercase letter" in msg

    def test_rejects_names_starting_with_underscore(self):
        """validate_agent_name rejects names starting with an underscore."""
        valid, msg = validate_agent_name("_bad")
        assert valid is False
        assert "start with a lowercase letter" in msg

    def test_returns_error_message(self):
        """validate_agent_name returns descriptive error messages."""
        valid, msg = validate_agent_name("")
        assert len(msg) > 0


class TestIsNameAvailableOnHost:
    """Tests for is_name_available_on_host function."""

    def test_returns_true_for_available_name(self):
        """is_name_available_on_host returns True for unused name."""
        host = {"agents": {"openclaw": {"agent_name": "clever-einstein"}}}
        assert is_name_available_on_host("swift-curie", host) is True

    def test_returns_false_for_used_name(self):
        """is_name_available_on_host returns False for already used name."""
        host = {"agents": {"openclaw": {"agent_name": "clever-einstein"}}}
        assert is_name_available_on_host("clever-einstein", host) is False

    def test_checks_all_claw_types(self):
        """is_name_available_on_host checks uniqueness across all claw types."""
        host = {
            "agents": {
                "openclaw": {"agent_name": "clever-einstein"},
                "zeroclaw": {"agent_name": "swift-curie"},
            }
        }
        assert is_name_available_on_host("clever-einstein", host) is False
        assert is_name_available_on_host("swift-curie", host) is False
        assert is_name_available_on_host("bold-tesla", host) is True

    def test_handles_empty_claws(self):
        """is_name_available_on_host handles host with no claws."""
        host = {"agents": {}}
        assert is_name_available_on_host("clever-einstein", host) is True

    def test_handles_missing_claws_field(self):
        """is_name_available_on_host handles host without claws field."""
        host = {}
        assert is_name_available_on_host("clever-einstein", host) is True

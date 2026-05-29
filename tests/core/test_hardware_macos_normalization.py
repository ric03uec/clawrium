"""Tests for Darwin fact normalization in core/hardware.py (issue #469, step 2).

Ansible reports macOS as `ansible_distribution == "MacOSX"`. We normalize to
`"macos"` (lowercase, single canonical token) so manifest entries can match.
"""

from clawrium.core.hardware import extract_hardware_from_facts


def test_macos_distribution_normalized():
    facts = {
        "ansible_distribution": "MacOSX",
        "ansible_distribution_version": "14.5",
        "ansible_architecture": "arm64",
        "ansible_processor_cores": 8,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 16384,
        "ansible_product_name": "Mac mini",
        "ansible_system_vendor": "Apple Inc.",
    }
    hw = extract_hardware_from_facts(facts)
    assert hw["os"] == "macos"
    assert hw["os_version"] == "14.5"
    assert hw["architecture"] == "arm64"


def test_linux_distribution_unchanged():
    """Regression: Linux normalization (lowercase) is untouched."""
    facts = {
        "ansible_distribution": "Ubuntu",
        "ansible_distribution_version": "24.04",
        "ansible_architecture": "x86_64",
        "ansible_processor_cores": 4,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 8192,
    }
    hw = extract_hardware_from_facts(facts)
    assert hw["os"] == "ubuntu"
    assert hw["os_version"] == "24.04"


def test_macos_version_string_coerced():
    facts = {
        "ansible_distribution": "MacOSX",
        "ansible_distribution_version": 26.5,
        "ansible_architecture": "arm64",
        "ansible_processor_cores": 8,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 16384,
    }
    hw = extract_hardware_from_facts(facts)
    assert hw["os"] == "macos"
    assert hw["os_version"] == "26.5"

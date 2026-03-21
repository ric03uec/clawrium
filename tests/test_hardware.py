"""Tests for hardware detection via ansible-runner."""

import pytest


def test_parse_ansible_facts_basic():
    """Test extracting basic hardware from Ansible facts."""
    from clawrium.core.hardware import extract_hardware_from_facts

    facts = {
        "ansible_architecture": "x86_64",
        "ansible_processor_cores": 4,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 16384,
        "ansible_mounts": [],
    }

    hardware = extract_hardware_from_facts(facts)

    assert hardware["architecture"] == "x86_64"
    assert hardware["processor_cores"] == 4
    assert hardware["processor_count"] == 1
    assert hardware["memtotal_mb"] == 16384


def test_parse_ansible_facts_mounts():
    """Test extracting mount information from Ansible facts."""
    from clawrium.core.hardware import extract_hardware_from_facts

    facts = {
        "ansible_architecture": "x86_64",
        "ansible_processor_cores": 4,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 16384,
        "ansible_mounts": [
            {
                "mount": "/",
                "size_total": 500000000000,
                "size_available": 200000000000,
                "fstype": "ext4",
                "device": "/dev/sda1",
            }
        ],
    }

    hardware = extract_hardware_from_facts(facts)

    assert len(hardware["mounts"]) == 1
    assert hardware["mounts"][0]["mount"] == "/"
    assert hardware["mounts"][0]["size_total"] == 500000000000
    assert hardware["mounts"][0]["size_available"] == 200000000000


def test_detect_gpu_nvidia():
    """Test GPU detection for NVIDIA cards."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = "01:00.0 VGA compatible controller: NVIDIA Corporation GP106 [GeForce GTX 1060 6GB]"

    result = parse_gpu_output(lspci_output)

    assert result["present"] is True
    assert result["vendor"] == "nvidia"


def test_detect_gpu_amd():
    """Test GPU detection for AMD cards."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 10"

    result = parse_gpu_output(lspci_output)

    assert result["present"] is True
    assert result["vendor"] == "amd"


def test_detect_gpu_intel():
    """Test GPU detection for Intel integrated graphics."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = (
        "00:02.0 VGA compatible controller: Intel Corporation UHD Graphics 630"
    )

    result = parse_gpu_output(lspci_output)

    assert result["present"] is True
    assert result["vendor"] == "intel"


def test_detect_gpu_none():
    """Test GPU detection when no GPU present."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = ""

    result = parse_gpu_output(lspci_output)

    assert result["present"] is False
    assert result["vendor"] is None


def test_gather_hardware_full(monkeypatch):
    """Test full hardware gathering via ansible-runner."""
    from clawrium.core.hardware import gather_hardware

    # Mock ansible_runner.run
    class MockResult:
        status = "successful"
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "stdout": "01:00.0 VGA compatible controller: NVIDIA Corporation"
                    }
                },
            }
        ]

        def get_fact_cache(self, hostname):
            return {
                "ansible_architecture": "x86_64",
                "ansible_processor_cores": 8,
                "ansible_processor_count": 1,
                "ansible_memtotal_mb": 32768,
                "ansible_mounts": [
                    {
                        "mount": "/",
                        "size_total": 1000000000000,
                        "size_available": 500000000000,
                    }
                ],
            }

    def mock_run(*args, **kwargs):
        return MockResult()

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", mock_run)

    hardware = gather_hardware("192.168.1.100", user="xclm")

    assert hardware["architecture"] == "x86_64"
    assert hardware["processor_cores"] == 8
    assert hardware["processor_count"] == 1
    assert hardware["memtotal_mb"] == 32768
    assert len(hardware["mounts"]) == 1
    assert hardware["gpu"]["present"] is True
    assert hardware["gpu"]["vendor"] == "nvidia"

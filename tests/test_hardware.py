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


def test_parse_ansible_facts_all_missing():
    """Test extracting hardware when all facts are missing."""
    from clawrium.core.hardware import extract_hardware_from_facts

    facts = {}

    hardware = extract_hardware_from_facts(facts)

    assert hardware["architecture"] == "unknown"
    assert hardware["processor_cores"] == 0
    assert hardware["processor_count"] == 0
    assert hardware["memtotal_mb"] == 0
    assert hardware["mounts"] == []


def test_parse_ansible_facts_os_detection():
    """Test extracting OS information from Ansible facts."""
    from clawrium.core.hardware import extract_hardware_from_facts

    facts = {
        "ansible_architecture": "x86_64",
        "ansible_processor_cores": 4,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 16384,
        "ansible_mounts": [],
        "ansible_distribution": "Ubuntu",
        "ansible_distribution_version": "24.04",
    }

    hardware = extract_hardware_from_facts(facts)

    assert hardware["os"] == "ubuntu"
    assert hardware["os_version"] == "24.04"


def test_parse_ansible_facts_os_missing():
    """Test extracting hardware when OS facts are missing."""
    from clawrium.core.hardware import extract_hardware_from_facts

    facts = {
        "ansible_architecture": "x86_64",
        "ansible_processor_cores": 4,
        "ansible_processor_count": 1,
        "ansible_memtotal_mb": 16384,
        "ansible_mounts": [],
    }

    hardware = extract_hardware_from_facts(facts)

    assert hardware["os"] == "unknown"
    assert hardware["os_version"] == "unknown"


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
    assert result["error"] is None


def test_detect_gpu_unknown():
    """Test GPU detection for unknown vendor."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = "01:00.0 VGA compatible controller: Cirrus Logic GD 5446"

    result = parse_gpu_output(lspci_output)

    assert result["present"] is True
    assert result["vendor"] == "unknown"
    assert result["error"] is None


def test_detect_gpu_3d_controller():
    """Test GPU detection for NVIDIA compute cards (3D controller class)."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = "00:04.0 3D controller: NVIDIA Corporation A100 80GB PCIe"

    result = parse_gpu_output(lspci_output)

    assert result["present"] is True
    assert result["vendor"] == "nvidia"


def test_detect_gpu_lspci_not_installed():
    """Test GPU detection when lspci is not installed."""
    from clawrium.core.hardware import parse_gpu_output

    lspci_output = "__NO_LSPCI__"

    result = parse_gpu_output(lspci_output)

    assert result["present"] is None
    assert result["vendor"] is None
    assert result["error"] == "lspci not installed"


def test_gather_hardware_full(monkeypatch):
    """Test full hardware gathering via ansible-runner."""
    from unittest.mock import Mock

    from clawrium.core.hardware import gather_hardware

    # Create distinct mock results for setup and GPU calls
    class SetupResult:
        status = "successful"
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "ansible_facts": {
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
                            "ansible_distribution": "Ubuntu",
                            "ansible_distribution_version": "24.04",
                        }
                    }
                },
            }
        ]

    class GpuResult:
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
            return None

    # Use side_effect to return different results per call
    mock_run = Mock(side_effect=[SetupResult(), GpuResult()])

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", mock_run)

    hardware = gather_hardware("192.168.1.100", user="xclm")

    # Verify both calls were made with correct modules
    assert mock_run.call_count == 2
    first_call = mock_run.call_args_list[0]
    second_call = mock_run.call_args_list[1]
    assert first_call.kwargs["module"] == "setup"
    assert second_call.kwargs["module"] == "shell"

    assert hardware["architecture"] == "x86_64"
    assert hardware["processor_cores"] == 8
    assert hardware["processor_count"] == 1
    assert hardware["memtotal_mb"] == 32768
    assert len(hardware["mounts"]) == 1
    assert hardware["gpu"]["present"] is True
    assert hardware["gpu"]["vendor"] == "nvidia"
    assert hardware["os"] == "ubuntu"
    assert hardware["os_version"] == "24.04"


def test_gather_hardware_passes_inventory_to_runner(monkeypatch, tmp_path):
    """Test that gather_hardware passes inventory dict to ansible_runner.run."""
    from unittest.mock import Mock

    # Create a valid SSH key file in allowed directory
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_file = ssh_dir / "test_key"
    key_file.write_text("fake key")
    key_file.chmod(0o600)

    # Mock Path.home() to return tmp_path
    monkeypatch.setattr("clawrium.core.hardware.Path.home", lambda: tmp_path)

    captured_calls = []

    class SetupResult:
        status = "successful"
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "ansible_facts": {
                            "ansible_architecture": "x86_64",
                            "ansible_processor_cores": 4,
                            "ansible_processor_count": 1,
                            "ansible_memtotal_mb": 16384,
                            "ansible_mounts": [],
                        }
                    }
                },
            }
        ]

    class GpuResult:
        status = "successful"
        events = []

    mock_run = Mock(side_effect=[SetupResult(), GpuResult()])

    def capture_run(*args, **kwargs):
        captured_calls.append(kwargs)
        return mock_run(*args, **kwargs)

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", capture_run)

    from clawrium.core.hardware import gather_hardware

    gather_hardware("192.168.1.100", user="testuser", port=2222, ssh_key=str(key_file))

    # Should be called twice (setup module + lspci)
    assert len(captured_calls) == 2

    # Both calls should have inventory parameter
    for call in captured_calls:
        assert "inventory" in call, (
            "inventory parameter must be passed to ansible_runner.run"
        )
        inv = call["inventory"]
        assert "all" in inv
        assert "hosts" in inv["all"]
        assert "192.168.1.100" in inv["all"]["hosts"]
        host_vars = inv["all"]["hosts"]["192.168.1.100"]
        assert host_vars["ansible_user"] == "testuser"
        assert host_vars["ansible_port"] == 2222
        assert host_vars["ansible_ssh_private_key_file"] == str(key_file)


def test_gather_hardware_no_ssh_key(monkeypatch):
    """Test that inventory omits ssh key when not provided."""
    from unittest.mock import Mock

    captured_calls = []

    class SetupResult:
        status = "successful"
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "ansible_facts": {
                            "ansible_architecture": "x86_64",
                            "ansible_processor_cores": 4,
                            "ansible_processor_count": 1,
                            "ansible_memtotal_mb": 16384,
                            "ansible_mounts": [],
                        }
                    }
                },
            }
        ]

    class GpuResult:
        status = "successful"
        events = []

    mock_run = Mock(side_effect=[SetupResult(), GpuResult()])

    def capture_run(*args, **kwargs):
        captured_calls.append(kwargs)
        return mock_run(*args, **kwargs)

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", capture_run)

    from clawrium.core.hardware import gather_hardware

    gather_hardware("192.168.1.100", user="testuser", port=2222)

    # Verify inventory does not contain ssh key
    inv = captured_calls[0]["inventory"]
    host_vars = inv["all"]["hosts"]["192.168.1.100"]
    assert "ansible_ssh_private_key_file" not in host_vars


def test_gather_hardware_timeout_raises(monkeypatch):
    """Test that timeout status raises RuntimeError."""
    from unittest.mock import Mock

    class TimeoutResult:
        status = "timeout"
        events = []

        def get_fact_cache(self, hostname):
            return None

    mock_run = Mock(return_value=TimeoutResult())

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", mock_run)

    from clawrium.core.hardware import gather_hardware

    with pytest.raises(RuntimeError, match="timed out after 30 seconds"):
        gather_hardware("192.168.1.100")


def test_gather_hardware_failed_raises(monkeypatch):
    """Test that failed status raises RuntimeError."""
    from unittest.mock import Mock

    class FailedResult:
        status = "failed"
        events = []

        def get_fact_cache(self, hostname):
            return None

    mock_run = Mock(return_value=FailedResult())

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", mock_run)

    from clawrium.core.hardware import gather_hardware

    with pytest.raises(RuntimeError, match="Fact gathering failed: failed"):
        gather_hardware("192.168.1.100")


def test_gather_hardware_no_facts_raises(monkeypatch):
    """Test that empty events (no ansible_facts) raises RuntimeError."""
    from unittest.mock import Mock

    class NoFactsResult:
        status = "successful"
        # Empty events means no ansible_facts found
        events = []

    mock_run = Mock(return_value=NoFactsResult())

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", mock_run)

    from clawrium.core.hardware import gather_hardware

    with pytest.raises(RuntimeError, match="No facts returned from host"):
        gather_hardware("192.168.1.100")


def test_gather_hardware_gpu_failure_logged(monkeypatch, caplog):
    """Test that GPU detection failure is logged and encoded in result."""
    from unittest.mock import Mock

    import logging

    class SetupResult:
        status = "successful"
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "res": {
                        "ansible_facts": {
                            "ansible_architecture": "x86_64",
                            "ansible_processor_cores": 4,
                            "ansible_processor_count": 1,
                            "ansible_memtotal_mb": 16384,
                            "ansible_mounts": [],
                        }
                    }
                },
            }
        ]

    class GpuFailedResult:
        status = "failed"
        events = []

    mock_run = Mock(side_effect=[SetupResult(), GpuFailedResult()])

    import ansible_runner

    monkeypatch.setattr(ansible_runner, "run", mock_run)

    from clawrium.core.hardware import gather_hardware

    with caplog.at_level(logging.WARNING):
        hardware = gather_hardware("192.168.1.100")

    # GPU should indicate failure, not "no GPU"
    assert hardware["gpu"]["present"] is None
    assert hardware["gpu"]["vendor"] is None
    assert "failed" in hardware["gpu"]["error"]

    # Warning should be logged
    assert "GPU detection failed" in caplog.text


def test_ssh_key_outside_allowed_dir_raises(monkeypatch, tmp_path):
    """Test that SSH key outside allowed directories raises ValueError."""
    # Create a key file outside allowed directories
    key_file = tmp_path / "unsafe_key"
    key_file.write_text("fake key")
    key_file.chmod(0o600)

    # Mock Path.home() to return a different path
    mock_home = tmp_path / "home"
    mock_home.mkdir()
    (mock_home / ".ssh").mkdir()
    monkeypatch.setattr("clawrium.core.hardware.Path.home", lambda: mock_home)

    from clawrium.core.hardware import gather_hardware

    with pytest.raises(ValueError, match="outside allowed directories"):
        gather_hardware("192.168.1.100", ssh_key=str(key_file))


def test_ssh_key_path_boundary_attack_blocked(monkeypatch, tmp_path):
    """Test that path boundary attacks like .sshmalicious are blocked."""
    # Create mock home
    mock_home = tmp_path / "home"
    mock_home.mkdir()
    (mock_home / ".ssh").mkdir()

    # Create .sshmalicious directory (would pass naive startswith check)
    malicious_dir = mock_home / ".sshmalicious"
    malicious_dir.mkdir()
    key_file = malicious_dir / "key"
    key_file.write_text("fake key")
    key_file.chmod(0o600)

    monkeypatch.setattr("clawrium.core.hardware.Path.home", lambda: mock_home)

    from clawrium.core.hardware import gather_hardware

    # Should be blocked - .sshmalicious is not inside .ssh
    with pytest.raises(ValueError, match="outside allowed directories"):
        gather_hardware("192.168.1.100", ssh_key=str(key_file))


def test_ssh_key_insecure_permissions_raises(monkeypatch, tmp_path):
    """Test that SSH key with insecure permissions raises ValueError."""
    # Create SSH dir in mock home
    mock_home = tmp_path / "home"
    mock_home.mkdir()
    ssh_dir = mock_home / ".ssh"
    ssh_dir.mkdir()

    # Create key with insecure permissions (world-readable)
    key_file = ssh_dir / "bad_key"
    key_file.write_text("fake key")
    key_file.chmod(0o644)  # Insecure!

    monkeypatch.setattr("clawrium.core.hardware.Path.home", lambda: mock_home)

    from clawrium.core.hardware import gather_hardware

    with pytest.raises(ValueError, match="insecure permissions"):
        gather_hardware("192.168.1.100", ssh_key=str(key_file))


def test_ssh_key_not_exists_raises(monkeypatch, tmp_path):
    """Test that non-existent SSH key raises ValueError."""
    mock_home = tmp_path / "home"
    mock_home.mkdir()
    ssh_dir = mock_home / ".ssh"
    ssh_dir.mkdir()

    monkeypatch.setattr("clawrium.core.hardware.Path.home", lambda: mock_home)

    from clawrium.core.hardware import gather_hardware

    with pytest.raises(ValueError, match="does not exist"):
        gather_hardware("192.168.1.100", ssh_key=str(ssh_dir / "nonexistent"))

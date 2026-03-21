"""Shared test fixtures for Clawrium tests."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config directory and set XDG_CONFIG_HOME."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def isolated_config(tmp_config_dir: Path) -> Path:
    """Return path where clawrium config should be created."""
    return tmp_config_dir / "clawrium"


@pytest.fixture
def mock_ssh_client():
    """Mock paramiko SSHClient that succeeds by default."""
    mock_client = MagicMock()

    # Mock connect() to succeed by default
    mock_client.connect = MagicMock(return_value=None)

    # Mock exec_command() to return connection success
    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b"Connection OK"
    mock_client.exec_command = MagicMock(
        return_value=(MagicMock(), mock_stdout, MagicMock())
    )

    # Mock close() as no-op
    mock_client.close = MagicMock(return_value=None)

    return mock_client


@pytest.fixture
def mock_ssh_client_fail():
    """Mock paramiko SSHClient that raises AuthenticationException."""
    import paramiko

    mock_client = MagicMock()
    mock_client.connect = MagicMock(side_effect=paramiko.AuthenticationException("Authentication failed"))
    mock_client.close = MagicMock(return_value=None)

    return mock_client


@pytest.fixture
def mock_ansible_runner():
    """Mock ansible_runner.run() that returns successful hardware detection."""
    mock_result = MagicMock()
    mock_result.status = 'successful'

    # Mock get_fact_cache to return sample hardware facts
    mock_result.get_fact_cache = MagicMock(return_value={
        'ansible_architecture': 'x86_64',
        'ansible_processor_cores': 4,
        'ansible_processor_count': 1,
        'ansible_memtotal_mb': 16384,
        'ansible_mounts': [
            {
                'mount': '/',
                'size_total': 500000000000,
                'size_available': 200000000000
            }
        ]
    })

    # Mock events list for GPU detection
    mock_event = {
        'event': 'runner_on_ok',
        'event_data': {
            'res': {
                'stdout': 'VGA compatible controller: NVIDIA Corporation Device 1234'
            }
        }
    }
    mock_result.events = [mock_event]

    return mock_result


@pytest.fixture
def mock_ssh_config():
    """Mock paramiko SSHConfig that returns test configuration."""
    mock_config = MagicMock()

    # Mock lookup() to return sample SSH config
    mock_config.lookup = MagicMock(return_value={
        'hostname': '192.168.1.100',
        'user': 'xclm',
        'port': 22
    })

    return mock_config


@pytest.fixture
def sample_host_data():
    """Return a complete host dict per D-04 schema."""
    return {
        'hostname': '192.168.1.100',
        'port': 22,
        'user': 'xclm',
        'auth_method': 'key',
        'alias': 'testhost',
        'hardware': {
            'architecture': 'x86_64',
            'processor_cores': 4,
            'processor_count': 1,
            'memtotal_mb': 16384,
            'mounts': [
                {
                    'mount': '/',
                    'size_total': 500000000000,
                    'size_available': 200000000000
                }
            ],
            'gpu': {
                'present': True,
                'vendor': 'nvidia'
            }
        },
        'metadata': {
            'added_at': '2026-03-21T00:00:00Z',
            'last_seen': '2026-03-21T00:00:00Z',
            'tags': ['dev', 'gpu']
        }
    }

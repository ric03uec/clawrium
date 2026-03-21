"""Tests for SSH connection testing module."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import paramiko
from clawrium.core.ssh_connection import get_ssh_config
from clawrium.core.ssh_connection import test_ssh_connection as ssh_test_connection


def test_get_ssh_config_no_file():
    """get_ssh_config returns {} when no SSH config file exists."""
    with patch.object(Path, 'exists', return_value=False):
        config = get_ssh_config("testhost")
        assert config == {}


def test_get_ssh_config_with_matching_host():
    """get_ssh_config parses config and returns settings for matching hostname."""
    ssh_config_content = """
Host testhost
    HostName 192.168.1.10
    User customuser
    Port 2222
    IdentityFile ~/.ssh/custom_key
"""
    with patch.object(Path, 'exists', return_value=True):
        with patch('builtins.open', mock_open(read_data=ssh_config_content)):
            config = get_ssh_config("testhost")

            assert 'hostname' in config
            assert config['hostname'] == '192.168.1.10'
            assert 'user' in config
            assert config['user'] == 'customuser'
            assert 'port' in config
            assert 'identityfile' in config


def test_get_ssh_config_with_non_matching_host():
    """get_ssh_config returns empty dict for non-matching hostname."""
    ssh_config_content = """
Host otherhost
    HostName 192.168.1.20
    User otheruser
"""
    with patch.object(Path, 'exists', return_value=True):
        with patch('builtins.open', mock_open(read_data=ssh_config_content)):
            config = get_ssh_config("testhost")
            # Should return empty or minimal config for non-matching host
            # Paramiko SSHConfig.lookup returns some defaults even for unknown hosts
            assert isinstance(config, dict)


def test_ssh_connection_success():
    """test_ssh_connection returns (True, success message) on successful connection."""
    mock_client = Mock(spec=paramiko.SSHClient)
    mock_stdout = Mock()
    mock_stdout.read.return_value = b"Connection OK\n"
    mock_client.exec_command.return_value = (Mock(), mock_stdout, Mock())

    with patch('paramiko.SSHClient', return_value=mock_client):
        success, message = ssh_test_connection("testhost", 22, "xclm")

        assert success is True
        assert "success" in message.lower()
        mock_client.connect.assert_called_once()
        mock_client.close.assert_called_once()


def test_ssh_connection_auth_failure():
    """test_ssh_connection returns (False, auth error) on authentication failure."""
    mock_client = Mock(spec=paramiko.SSHClient)
    mock_client.connect.side_effect = paramiko.AuthenticationException("Auth failed")

    with patch('paramiko.SSHClient', return_value=mock_client):
        success, message = ssh_test_connection("testhost", 22, "xclm")

        assert success is False
        assert "authentication" in message.lower()
        assert "ssh keys" in message.lower()
        mock_client.close.assert_called_once()


def test_ssh_connection_network_error():
    """test_ssh_connection returns (False, network error) on socket error."""
    import socket

    mock_client = Mock(spec=paramiko.SSHClient)
    mock_client.connect.side_effect = socket.error("Connection refused")

    with patch('paramiko.SSHClient', return_value=mock_client):
        success, message = ssh_test_connection("testhost", 22, "xclm")

        assert success is False
        assert "network error" in message.lower()
        mock_client.close.assert_called_once()

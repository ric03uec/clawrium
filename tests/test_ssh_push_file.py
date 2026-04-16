"""Tests for SFTP file push functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import paramiko
import socket

from clawrium.core.ssh_connection import (
    push_file_to_remote,
    HostKeyVerificationRequired,
    StrictHostKeyPolicy,
)


class TestPushFileToRemote:
    """Tests for push_file_to_remote function."""

    def test_success_path(self, tmp_path):
        """push_file_to_remote returns (True, None) on successful transfer."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is True
            assert error is None

            # B2: Verify StrictHostKeyPolicy is set
            mock_client.set_missing_host_key_policy.assert_called_once()
            policy_arg = mock_client.set_missing_host_key_policy.call_args[0][0]
            assert isinstance(policy_arg, StrictHostKeyPolicy)

            # B3: Verify load_system_host_keys is called
            mock_client.load_system_host_keys.assert_called_once()

            # B3: Verify connection parameters include timeout
            connect_kwargs = mock_client.connect.call_args.kwargs
            assert connect_kwargs.get("timeout") == 10

            mock_client.connect.assert_called_once()
            mock_sftp.put.assert_called_once_with(
                str(local_file), "/home/xclm/.openclaw/openclaw.json"
            )
            mock_sftp.close.assert_called_once()
            mock_client.close.assert_called_once()

    def test_success_with_permissions(self, tmp_path):
        """push_file_to_remote sets file permissions when specified."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
                permissions=0o600,
            )

            assert success is True
            assert error is None
            mock_sftp.chmod.assert_called_once_with(
                "/home/xclm/.openclaw/openclaw.json", 0o600
            )

    def test_chmod_failure_after_successful_put(self, tmp_path):
        """push_file_to_remote returns error when chmod fails after successful put.

        B1: This is a security-critical test - a chmod failure after put would
        leave a secret file world-readable.
        """
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp
        # put() succeeds, chmod() fails
        mock_sftp.chmod.side_effect = paramiko.SFTPError("Permission denied")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
                permissions=0o600,
            )

            assert success is False
            assert "Permission denied" in error
            # W3: Verify SFTP flow was initiated
            mock_client.open_sftp.assert_called_once()
            # Verify put was called (file was uploaded)
            mock_sftp.put.assert_called_once()
            # Verify chmod was attempted
            mock_sftp.chmod.assert_called_once()
            # Verify cleanup happened
            mock_sftp.close.assert_called_once()
            mock_client.close.assert_called_once()

    def test_local_file_not_found(self, tmp_path):
        """push_file_to_remote returns error when local file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.json"

        success, error = push_file_to_remote(
            hostname="testhost",
            port=22,
            username="xclm",
            private_key_path="/path/to/key",
            local_path=nonexistent,
            remote_path="/home/xclm/.openclaw/openclaw.json",
        )

        assert success is False
        assert "Local file not found" in error

    def test_local_path_is_directory(self, tmp_path):
        """push_file_to_remote returns error when local path is a directory."""
        success, error = push_file_to_remote(
            hostname="testhost",
            port=22,
            username="xclm",
            private_key_path="/path/to/key",
            local_path=tmp_path,  # directory, not file
            remote_path="/home/xclm/.openclaw/openclaw.json",
        )

        assert success is False
        assert "not a file" in error

    def test_network_error(self, tmp_path):
        """push_file_to_remote returns error on network failure."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_client.connect.side_effect = socket.error("Connection refused")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is False
            assert "Network error" in error
            assert "testhost:22" in error
            mock_client.close.assert_called_once()

    def test_auth_failure(self, tmp_path):
        """push_file_to_remote returns error on authentication failure."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_client.connect.side_effect = paramiko.AuthenticationException("Auth failed")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is False
            assert "Authentication failed" in error
            assert "xclm@testhost" in error
            mock_client.close.assert_called_once()

    def test_bad_host_key(self, tmp_path):
        """push_file_to_remote returns error on host key mismatch."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_key = Mock()
        mock_key.get_base64.return_value = "AAAA"
        mock_client.connect.side_effect = paramiko.BadHostKeyException(
            "testhost", mock_key, mock_key
        )

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is False
            assert "Host key" in error
            assert "changed" in error
            mock_client.close.assert_called_once()

    def test_raises_host_key_verification_required(self, tmp_path):
        """push_file_to_remote propagates HostKeyVerificationRequired for TOFU flow."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)

        def raise_verification(*args, **kwargs):
            raise HostKeyVerificationRequired("testhost", "ssh-rsa", "aa:bb:cc:dd")

        mock_client.connect.side_effect = raise_verification

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            with pytest.raises(HostKeyVerificationRequired) as exc_info:
                push_file_to_remote(
                    hostname="testhost",
                    port=22,
                    username="xclm",
                    private_key_path="/path/to/key",
                    local_path=local_file,
                    remote_path="/home/xclm/.openclaw/openclaw.json",
                )

            assert exc_info.value.hostname == "testhost"
            assert exc_info.value.key_type == "ssh-rsa"
            assert exc_info.value.fingerprint == "aa:bb:cc:dd"
            mock_client.close.assert_called_once()

    def test_ssh_exception(self, tmp_path):
        """push_file_to_remote returns error on generic SSH exception."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_client.connect.side_effect = paramiko.SSHException("Protocol error")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is False
            assert "SSH connection failed" in error
            mock_client.close.assert_called_once()

    def test_remote_permission_denied(self, tmp_path):
        """push_file_to_remote returns error when remote write is denied."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.put.side_effect = paramiko.SFTPError("Permission denied")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/root/forbidden/openclaw.json",
            )

            assert success is False
            assert "Permission denied" in error
            mock_sftp.close.assert_called_once()
            mock_client.close.assert_called_once()

    def test_remote_directory_not_found(self, tmp_path):
        """push_file_to_remote returns error when remote directory doesn't exist."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.put.side_effect = paramiko.SFTPError("No such file or directory")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/nonexistent/dir/openclaw.json",
            )

            assert success is False
            assert "Remote directory does not exist" in error
            mock_sftp.close.assert_called_once()
            mock_client.close.assert_called_once()

    def test_sftp_generic_error(self, tmp_path):
        """push_file_to_remote returns error message for generic SFTP errors."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.put.side_effect = paramiko.SFTPError("Disk full")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is False
            assert "File transfer failed" in error
            assert "Disk full" in error
            mock_sftp.close.assert_called_once()
            mock_client.close.assert_called_once()

    def test_cleanup_on_sftp_open_failure(self, tmp_path):
        """push_file_to_remote cleans up SSH client when SFTP open fails.

        S1: Also verifies that sftp.close() is NOT called when SFTP was never opened,
        ensuring the None guard in the finally block is exercised.
        """
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()  # Create mock to verify it's NOT closed
        mock_client.open_sftp.side_effect = paramiko.SSHException("SFTP not available")

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=local_file,
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is False
            # SSH client cleanup still happens
            mock_client.close.assert_called_once()
            # S1: SFTP close should NOT be called since open_sftp raised
            assert mock_sftp.close.call_count == 0

    def test_accepts_path_object(self, tmp_path):
        """push_file_to_remote accepts Path objects for local_path."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=Path(local_file),  # Explicitly use Path
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is True
            assert error is None

    def test_accepts_string_path(self, tmp_path):
        """push_file_to_remote accepts string paths for local_path."""
        local_file = tmp_path / "test.json"
        local_file.write_text('{"key": "value"}')

        mock_client = Mock(spec=paramiko.SSHClient)
        mock_sftp = Mock()
        mock_client.open_sftp.return_value = mock_sftp

        with patch("clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client):
            success, error = push_file_to_remote(
                hostname="testhost",
                port=22,
                username="xclm",
                private_key_path="/path/to/key",
                local_path=str(local_file),  # String path
                remote_path="/home/xclm/.openclaw/openclaw.json",
            )

            assert success is True
            assert error is None

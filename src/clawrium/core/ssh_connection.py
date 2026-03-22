"""SSH connection testing for Clawrium."""

import logging
import os
import socket
import paramiko
from pathlib import Path

__all__ = [
    "get_ssh_config",
    "test_ssh_connection",
    "accept_host_key",
    "HostKeyVerificationRequired",
]

logger = logging.getLogger(__name__)


def get_ssh_config(hostname: str) -> dict:
    """Parse SSH config and return settings for hostname.

    Reads ~/.ssh/config and extracts settings for the given hostname.

    Args:
        hostname: The hostname to look up in SSH config.

    Returns:
        Dictionary with SSH config settings (hostname, user, port, identityfile).
        Empty dict if config file doesn't exist.
    """
    ssh_config = paramiko.SSHConfig()
    config_file = Path.home() / ".ssh" / "config"

    if not config_file.exists():
        return {}

    with open(config_file) as f:
        ssh_config.parse(f)

    config = ssh_config.lookup(hostname)

    # Normalize config to standard dict with only relevant keys
    result = {}
    if "hostname" in config:
        result["hostname"] = config["hostname"]
    if "user" in config:
        result["user"] = config["user"]
    if "port" in config:
        result["port"] = config["port"]
    if "identityfile" in config:
        result["identityfile"] = config["identityfile"]

    return result


class HostKeyVerificationRequired(Exception):
    """Raised when host key verification is needed from user."""

    def __init__(self, hostname: str, key_type: str, fingerprint: str):
        self.hostname = hostname
        self.key_type = key_type
        self.fingerprint = fingerprint
        super().__init__(f"Unknown host key for {hostname}")


class StrictHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Host key policy that requires explicit user verification.

    Raises HostKeyVerificationRequired when encountering unknown host keys,
    allowing the CLI layer to prompt for user confirmation (TOFU pattern).
    """

    def missing_host_key(self, client, hostname, key):
        fingerprint = key.get_fingerprint().hex()
        formatted_fp = ":".join(
            fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)
        )
        raise HostKeyVerificationRequired(
            hostname=hostname, key_type=key.get_name(), fingerprint=formatted_fp
        )


def test_ssh_connection(
    hostname: str, port: int = 22, user: str = "xclm", key_filename: str | None = None
) -> tuple[bool, str]:
    """Test SSH connection and return (success, message) or host key verification request.

    Attempts to connect to the specified host via SSH and execute
    a simple test command.

    Args:
        hostname: The hostname or IP address to connect to.
        port: SSH port (default 22).
        user: SSH username (default "xclm").
        key_filename: Optional explicit SSH key path.

    Returns:
        Tuple of (success: bool, message: str) indicating connection result,
        or HostKeyVerificationRequired if user must confirm host key.
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Use strict policy requiring explicit user verification
    client.set_missing_host_key_policy(StrictHostKeyPolicy())

    try:
        connect_kwargs = {
            "hostname": hostname,
            "port": port,
            "username": user,
            "timeout": 10,
        }
        if key_filename:
            connect_kwargs["key_filename"] = key_filename

        client.connect(**connect_kwargs)

        # Test that transport is active
        transport = client.get_transport()
        if not transport or not transport.is_active():
            return (False, "SSH transport not active")

        return (True, "Connection successful")

    except HostKeyVerificationRequired:
        # Re-raise for CLI to handle with user confirmation
        raise
    except paramiko.BadHostKeyException:
        return (
            False,
            "Host key verification failed - host key changed since last connection",
        )
    except paramiko.AuthenticationException:
        return (False, "Authentication failed - check SSH keys")
    except socket.error as e:
        # Log raw error for debugging, return sanitized message
        logger.debug(f"Socket error connecting to {hostname}:{port}: {e}")
        return (False, f"Network error: could not reach {hostname}:{port}")
    except paramiko.SSHException as e:
        # Log raw error for debugging, return sanitized message
        logger.debug(f"SSH error connecting to {hostname}:{port}: {e}")
        return (
            False,
            "SSH connection failed - check host availability and SSH configuration",
        )
    finally:
        client.close()


class VerifyingHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Host key policy that verifies fingerprint matches expected value before saving."""

    def __init__(self, expected_fingerprint: str):
        self.expected_fingerprint = expected_fingerprint
        self.key_accepted = False

    def missing_host_key(self, client, hostname, key):
        fingerprint = key.get_fingerprint().hex()
        formatted_fp = ":".join(
            fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)
        )

        if formatted_fp != self.expected_fingerprint:
            raise paramiko.SSHException(
                f"Host key fingerprint mismatch: expected {self.expected_fingerprint}, got {formatted_fp}"
            )

        # Fingerprint matches - accept the key
        client._host_keys.add(hostname, key.get_name(), key)
        self.key_accepted = True


def accept_host_key(
    hostname: str, port: int = 22, expected_fingerprint: str = ""
) -> bool:
    """Accept and save a host key to known_hosts after verifying fingerprint.

    Called after user confirms the host key fingerprint. Re-verifies that the
    key matches to prevent MITM attacks between confirmation and save.

    Args:
        hostname: The hostname to accept key for.
        port: SSH port.
        expected_fingerprint: The fingerprint user confirmed (colon-separated hex).

    Returns:
        True if key was saved successfully with matching fingerprint.
    """
    if not expected_fingerprint:
        logger.error("No fingerprint provided for verification")
        return False

    client = paramiko.SSHClient()
    client.load_system_host_keys()

    known_hosts_path = Path.home() / ".ssh" / "known_hosts"

    # Use verifying policy that checks fingerprint before accepting
    policy = VerifyingHostKeyPolicy(expected_fingerprint)
    client.set_missing_host_key_policy(policy)

    fingerprint_mismatch = False

    try:
        # Connect briefly to get and verify the key (auth_timeout >= 5s for reliability)
        client.connect(hostname, port=port, timeout=5, auth_timeout=5)
    except paramiko.AuthenticationException:
        # Auth failure is expected - we just want the host key saved
        pass
    except paramiko.SSHException as e:
        # Fingerprint mismatch - don't save
        logger.debug("SSH error during host key verification: %s", e)
        fingerprint_mismatch = True
    except (socket.timeout, OSError) as e:
        # Network error - but key may have been accepted before error
        logger.debug("Connection error during host key verification: %s", e)
    finally:
        client.close()

    # Don't save if fingerprint didn't match
    if fingerprint_mismatch:
        return False

    # Save host keys only if key was accepted (fingerprint matched)
    if policy.key_accepted:
        # Set restrictive umask for known_hosts write
        old_umask = os.umask(0o077)
        try:
            # Re-open client just for saving (paramiko requires it)
            save_client = paramiko.SSHClient()
            save_client.load_system_host_keys()
            # Copy the accepted key to the save client
            for host_key_hostname in client._host_keys.keys():
                for key_type in client._host_keys[host_key_hostname].keys():
                    key = client._host_keys[host_key_hostname][key_type]
                    save_client._host_keys.add(host_key_hostname, key_type, key)
            save_client.save_host_keys(str(known_hosts_path))
            # Ensure known_hosts has correct permissions
            os.chmod(known_hosts_path, 0o600)
        except Exception as e:
            logger.debug(f"Error saving host keys: {e}")
            return False
        finally:
            os.umask(old_umask)

    return policy.key_accepted

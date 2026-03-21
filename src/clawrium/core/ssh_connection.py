"""SSH connection testing for Clawrium."""

import logging
import socket
import paramiko
from pathlib import Path

__all__ = ["get_ssh_config", "test_ssh_connection"]

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
    if 'hostname' in config:
        result['hostname'] = config['hostname']
    if 'user' in config:
        result['user'] = config['user']
    if 'port' in config:
        result['port'] = config['port']
    if 'identityfile' in config:
        result['identityfile'] = config['identityfile']

    return result


class WarningHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Host key policy that warns user but allows first connection.

    For local network use, we warn about MITM risks but allow the connection.
    The host key is saved after first connection for future verification.
    """

    def missing_host_key(self, client, hostname, key):
        logger.warning(
            f"Unknown host key for {hostname}. Fingerprint: {key.get_fingerprint().hex()}. "
            "Accepting for first connection - verify this is your intended host."
        )
        # Add key to known_hosts for future verification
        client._host_keys.add(hostname, key.get_name(), key)
        if client._host_keys_filename is not None:
            client.save_host_keys(client._host_keys_filename)


def test_ssh_connection(
    hostname: str,
    port: int = 22,
    user: str = "xclm",
    key_filename: str | None = None
) -> tuple[bool, str]:
    """Test SSH connection and return (success, message).

    Attempts to connect to the specified host via SSH and execute
    a simple test command.

    Args:
        hostname: The hostname or IP address to connect to.
        port: SSH port (default 22).
        user: SSH username (default "xclm").
        key_filename: Optional explicit SSH key path.

    Returns:
        Tuple of (success: bool, message: str) indicating connection result.
    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Use warning policy that logs fingerprint but allows first connection
    client.set_missing_host_key_policy(WarningHostKeyPolicy())

    try:
        connect_kwargs = {
            'hostname': hostname,
            'port': port,
            'username': user,
            'timeout': 10
        }
        if key_filename:
            connect_kwargs['key_filename'] = key_filename

        client.connect(**connect_kwargs)

        # Test command execution
        stdin, stdout, stderr = client.exec_command('echo "Connection OK"')
        result = stdout.read().decode().strip()
        if result != "Connection OK":
            logger.debug(f"Unexpected test command output: {result}")

        return (True, "Connection successful")

    except paramiko.BadHostKeyException:
        return (False, "Host key verification failed - host key changed since last connection")
    except paramiko.AuthenticationException:
        return (False, "Authentication failed - check SSH keys")
    except socket.error as e:
        # Log raw error for debugging, return sanitized message
        logger.debug(f"Socket error connecting to {hostname}:{port}: {e}")
        return (False, f"Network error: could not reach {hostname}:{port}")
    except paramiko.SSHException as e:
        # Log raw error for debugging, return sanitized message
        logger.debug(f"SSH error connecting to {hostname}:{port}: {e}")
        return (False, "SSH connection failed - check host availability and SSH configuration")
    finally:
        client.close()

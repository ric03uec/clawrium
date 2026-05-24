"""Tests for CLI host commands."""

import os
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from clawrium.cli.main import app

runner = CliRunner()


def create_test_keypair(config_dir: Path, hostname: str) -> None:
    """Create a test keypair for a host (required before host add)."""
    key_dir = config_dir / "keys" / hostname
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "xclm_ed25519").write_text("test-private-key")
    (key_dir / "xclm_ed25519").chmod(0o600)
    (key_dir / "xclm_ed25519.pub").write_text("ssh-ed25519 AAAA... clawrium")


def test_host_add_success(isolated_config: Path, mock_ssh_client, mock_ansible_runner):
    """clm host add with valid connection saves host."""
    # Setup: create keypair (required before host add)
    create_test_keypair(isolated_config, "192.168.1.100")

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        with patch(
            "clawrium.core.hardware.ansible_runner.run",
            return_value=mock_ansible_runner,
        ):
            result = runner.invoke(
                app, ["host", "add", "192.168.1.100"], env=os.environ
            )

            assert result.exit_code == 0
            assert (
                "192.168.1.100" in result.output or "success" in result.output.lower()
            )


def test_host_add_with_flags(
    isolated_config: Path, mock_ssh_client, mock_ansible_runner
):
    """clm host add with flags uses provided values."""
    # Setup: create keypair for alias (key_id = alias when alias provided)
    create_test_keypair(isolated_config, "myhost")

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        with patch(
            "clawrium.core.hardware.ansible_runner.run",
            return_value=mock_ansible_runner,
        ):
            result = runner.invoke(
                app,
                [
                    "host",
                    "add",
                    "192.168.1.100",
                    "--user",
                    "xclm",
                    "--port",
                    "22",
                    "--alias",
                    "myhost",
                ],
                env=os.environ,
            )

            assert result.exit_code == 0


def test_host_add_connection_failed(isolated_config: Path, mock_ssh_client_fail):
    """clm host add with connection failure shows error, exits 1."""
    # Setup: create keypair (required before host add)
    create_test_keypair(isolated_config, "badhost")

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient",
        return_value=mock_ssh_client_fail,
    ):
        result = runner.invoke(app, ["host", "add", "badhost"], env=os.environ)

        assert result.exit_code == 1
        assert (
            "authentication" in result.output.lower()
            or "failed" in result.output.lower()
        )


def test_host_add_duplicate(isolated_config: Path, sample_host_data: dict):
    """Adding same hostname twice shows error, exits 1."""
    # Setup: create keypair and hosts.json with existing host
    create_test_keypair(isolated_config, "192.168.1.100")
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(app, ["host", "add", "192.168.1.100"], env=os.environ)

    assert result.exit_code == 1
    assert "already" in result.output.lower() or "exists" in result.output.lower()


def test_host_add_requires_keypair(isolated_config: Path):
    """clm host add without keypair shows error and suggests init."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(app, ["host", "add", "192.168.1.100"], env=os.environ)

    assert result.exit_code == 1
    assert "no keypair" in result.output.lower()
    assert "host create --bootstrap" in result.output.lower()


def test_host_list_empty(isolated_config: Path):
    """clm host list with no hosts shows 'No hosts registered'."""
    # Ensure config dir exists but no hosts.json
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(app, ["host", "list"], env=os.environ)

    assert result.exit_code == 0
    assert "no hosts" in result.output.lower() or "empty" in result.output.lower()


def test_host_list_table(isolated_config: Path, sample_host_data: dict):
    """clm host list with hosts shows table with Alias, Host, Architecture columns."""
    # Setup: create hosts.json with sample data
    isolated_config.mkdir(parents=True, exist_ok=True)
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(app, ["host", "list"], env=os.environ)

    assert result.exit_code == 0
    # Check for table headers
    assert "alias" in result.output.lower() or "host" in result.output.lower()
    # Check for sample data
    assert "testhost" in result.output.lower() or "192.168.1.100" in result.output


def test_host_remove_with_confirmation(
    isolated_config: Path, sample_host_data: dict, monkeypatch
):
    """clm host remove prompts for confirmation."""
    # Setup: create hosts.json with sample data
    isolated_config.mkdir(parents=True, exist_ok=True)
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    # Mock confirmation to abort
    result = runner.invoke(
        app, ["host", "remove", "192.168.1.100"], input="n\n", env=os.environ
    )

    assert "confirm" in result.output.lower() or "remove" in result.output.lower()


def test_host_remove_force(isolated_config: Path, sample_host_data: dict):
    """clm host remove --force skips confirmation."""
    # Setup: create hosts.json with sample data
    isolated_config.mkdir(parents=True, exist_ok=True)
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app, ["host", "remove", "192.168.1.100", "--force"], env=os.environ
    )

    assert result.exit_code == 0
    # Should not prompt for confirmation
    assert "removed" in result.output.lower() or "success" in result.output.lower()


def test_host_remove_deletes_keys(isolated_config: Path, sample_host_data: dict):
    """clm host remove also deletes per-host keys."""
    # Setup: create hosts.json and keypair
    create_test_keypair(isolated_config, "192.168.1.100")
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    key_dir = isolated_config / "keys" / "192.168.1.100"
    assert key_dir.exists()

    result = runner.invoke(
        app, ["host", "remove", "192.168.1.100", "--force"], env=os.environ
    )

    assert result.exit_code == 0
    assert not key_dir.exists(), "Key directory should be deleted"
    assert "keypair" in result.output.lower() or "deleted" in result.output.lower()


def test_host_remove_not_found(isolated_config: Path):
    """clm host remove nonexistent shows error, exits 1."""
    # Ensure config dir exists but no hosts
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(app, ["host", "remove", "nonexistent"], env=os.environ)

    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "error" in result.output.lower()


def test_host_ps_connected(
    isolated_config: Path, sample_host_data: dict, mock_ssh_client
):
    """clm host ps with reachable host shows 'Connected'."""
    # Setup: create hosts.json with sample data and keypair
    create_test_keypair(isolated_config, "192.168.1.100")
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        result = runner.invoke(app, ["host", "ps", "192.168.1.100"], env=os.environ)

        assert result.exit_code == 0
        assert "connected" in result.output.lower()


def test_host_ps_disconnected(
    isolated_config: Path, sample_host_data: dict, mock_ssh_client_fail
):
    """clm host ps with unreachable host shows 'Disconnected'."""
    # Setup: create hosts.json with sample data and keypair
    create_test_keypair(isolated_config, "192.168.1.100")
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient",
        return_value=mock_ssh_client_fail,
    ):
        result = runner.invoke(app, ["host", "ps", "192.168.1.100"], env=os.environ)

        # May exit 0 and show "disconnected" status, or exit 1 depending on design
        assert (
            "disconnected" in result.output.lower() or "failed" in result.output.lower()
        )


def test_host_add_stores_key_id_from_alias(
    isolated_config: Path, mock_ssh_client, mock_ansible_runner
):
    """clm host add with alias stores key_id = alias."""
    create_test_keypair(isolated_config, "myserver")

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        with patch(
            "clawrium.core.hardware.ansible_runner.run",
            return_value=mock_ansible_runner,
        ):
            result = runner.invoke(
                app,
                ["host", "add", "192.168.1.100", "--alias", "myserver"],
                env=os.environ,
            )

            assert result.exit_code == 0

            # Verify key_id is stored
            import json

            hosts = json.loads((isolated_config / "hosts.json").read_text())
            assert hosts[0].get("key_id") == "myserver"


def test_host_add_stores_key_id_from_hostname(
    isolated_config: Path, mock_ssh_client, mock_ansible_runner
):
    """clm host add without alias stores key_id = hostname."""
    create_test_keypair(isolated_config, "webserver")

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        with patch(
            "clawrium.core.hardware.ansible_runner.run",
            return_value=mock_ansible_runner,
        ):
            result = runner.invoke(app, ["host", "add", "webserver"], env=os.environ)

            assert result.exit_code == 0

            import json

            hosts = json.loads((isolated_config / "hosts.json").read_text())
            # key_id should be the hostname when no alias provided
            assert hosts[0].get("key_id") == "webserver"


def test_host_ps_uses_key_id(isolated_config: Path, mock_ssh_client):
    """clm host ps looks up keys by key_id, not hostname."""
    # Create keypair under alias name, not IP
    create_test_keypair(isolated_config, "myserver")

    # Create host record with key_id and alias
    import json

    host_data = {
        "hostname": "192.168.1.100",
        "alias": "myserver",  # Need alias so get_host can find it
        "key_id": "myserver",
        "port": 22,
        "agent_name": "xclm",
        "auth_method": "key",
        "hardware": {},
        "metadata": {"added_at": "2026-03-21", "last_seen": "2026-03-21", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file.write_text(json.dumps([host_data]))

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        result = runner.invoke(app, ["host", "ps", "myserver"], env=os.environ)

        # Should succeed because key lookup uses key_id "myserver", not hostname "192.168.1.100"
        assert result.exit_code == 0
        assert "connected" in result.output.lower()


def test_host_remove_uses_key_id(isolated_config: Path):
    """clm host remove deletes keys by key_id, not hostname."""
    # Create keypair under alias name, not IP
    create_test_keypair(isolated_config, "myserver")

    # Create host record with key_id different from hostname
    import json

    host_data = {
        "hostname": "192.168.1.100",
        "alias": "myserver",
        "key_id": "myserver",  # Keys stored here, not under hostname
        "port": 22,
        "agent_name": "xclm",
        "auth_method": "key",
        "hardware": {},
        "metadata": {"added_at": "2026-03-21", "last_seen": "2026-03-21", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file.write_text(json.dumps([host_data]))

    # Verify key exists under key_id, not hostname
    key_dir_by_key_id = isolated_config / "keys" / "myserver"
    key_dir_by_hostname = isolated_config / "keys" / "192.168.1.100"
    assert key_dir_by_key_id.exists()
    assert not key_dir_by_hostname.exists()

    result = runner.invoke(
        app, ["host", "remove", "myserver", "--force"], env=os.environ
    )

    assert result.exit_code == 0
    # Keys should be deleted using key_id
    assert not key_dir_by_key_id.exists(), (
        "Key directory should be deleted using key_id"
    )
    assert "keypair" in result.output.lower() or "deleted" in result.output.lower()


def test_host_ps_refresh(
    isolated_config: Path, sample_host_data: dict, mock_ssh_client, mock_ansible_runner
):
    """clm host ps --refresh updates hardware info."""
    # Setup: create hosts.json with sample data and keypair
    create_test_keypair(isolated_config, "192.168.1.100")
    import json

    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        with patch(
            "clawrium.core.hardware.ansible_runner.run",
            return_value=mock_ansible_runner,
        ):
            result = runner.invoke(
                app, ["host", "ps", "192.168.1.100", "--refresh"], env=os.environ
            )

            assert result.exit_code == 0
            assert (
                "hardware" in result.output.lower()
                or "refresh" in result.output.lower()
            )


# Tests for clm host init command


def test_host_init_generates_keypair(isolated_config: Path):
    """clm host init generates keypair for host when none exists."""
    # Setup: ensure no keys exist
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Mock SSH to fail (manual setup path)
    mock_client = MagicMock()
    mock_client.connect = MagicMock(side_effect=Exception("Connection failed"))
    mock_client.close = MagicMock()
    mock_client.load_system_host_keys = MagicMock()
    mock_client.set_missing_host_key_policy = MagicMock()

    with patch("clawrium.cli.host.paramiko.SSHClient", return_value=mock_client):
        result = runner.invoke(app, ["host", "init", "192.168.1.100"], env=os.environ)

        # Should exit 1 (manual setup required = failure for scripting, B2 fix)
        assert result.exit_code == 1, (
            f"Unexpected exit code: {result.exit_code}, output: {result.output}"
        )

        # Should generate keypair (even though setup failed)
        key_dir = isolated_config / "keys" / "192.168.1.100"
        assert (key_dir / "xclm_ed25519").exists()
        assert (key_dir / "xclm_ed25519.pub").exists()

        # Should display public key path
        assert "192.168.1.100" in result.output


def test_host_init_auto_setup_success(isolated_config: Path, mock_ssh_client):
    """clm host init with successful connection creates xclm user."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Mock exec_command for setup commands
    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b"OK"
    mock_stdout.channel.recv_exit_status.return_value = 0
    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b""
    mock_ssh_client.exec_command = MagicMock(
        return_value=(MagicMock(), mock_stdout, mock_stderr)
    )

    # Create mock for transport
    mock_transport = MagicMock()
    mock_transport.is_active.return_value = True
    mock_ssh_client.get_transport.return_value = mock_transport

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        with patch(
            "clawrium.cli.host.paramiko.SSHClient", return_value=mock_ssh_client
        ):
            result = runner.invoke(
                app,
                ["host", "init", "192.168.1.100", "--user", "admin"],
                env=os.environ,
            )

            # Should succeed and show success message
            assert result.exit_code == 0, f"Failed with: {result.output}"
            assert "192.168.1.100" in result.output


def test_host_init_manual_fallback(isolated_config: Path):
    """clm host init shows manual commands when connection fails."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    # Mock SSH to fail completely
    mock_client = MagicMock()
    mock_client.connect = MagicMock(side_effect=Exception("Connection refused"))
    mock_client.close = MagicMock()
    mock_client.load_system_host_keys = MagicMock()
    mock_client.set_missing_host_key_policy = MagicMock()

    with patch("clawrium.cli.host.paramiko.SSHClient", return_value=mock_client):
        result = runner.invoke(
            app, ["host", "init", "192.168.1.100", "--user", "admin"], env=os.environ
        )

        # Should exit 1 (manual setup required = failure for scripting, B2 fix)
        assert result.exit_code == 1, (
            f"Unexpected exit code: {result.exit_code}, output: {result.output}"
        )

        # Should show manual setup commands
        assert "useradd" in result.output.lower() or "manual" in result.output.lower()
        # Should show public key
        assert "ssh-ed25519" in result.output


def test_host_init_existing_keypair_not_regenerated(isolated_config: Path):
    """clm host init does not regenerate existing keypair."""
    # Setup: create existing keypair
    key_dir = isolated_config / "keys" / "192.168.1.100"
    key_dir.mkdir(parents=True)
    private_key = key_dir / "xclm_ed25519"
    private_key.write_text("existing-key-content")
    (key_dir / "xclm_ed25519.pub").write_text("ssh-ed25519 EXISTING clawrium")

    # Mock SSH to fail
    mock_client = MagicMock()
    mock_client.connect = MagicMock(side_effect=Exception("Connection failed"))
    mock_client.close = MagicMock()
    mock_client.load_system_host_keys = MagicMock()
    mock_client.set_missing_host_key_policy = MagicMock()

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_client
    ):
        with patch("clawrium.cli.host.paramiko.SSHClient", return_value=mock_client):
            runner.invoke(app, ["host", "init", "192.168.1.100"], env=os.environ)

            # Key should not be regenerated
            assert private_key.read_text() == "existing-key-content"


# Tests for clm host alias command


def test_host_alias_set(isolated_config: Path, sample_host_data: dict):
    """clm host alias --set updates alias successfully."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app, ["host", "alias", "192.168.1.100", "--set", "new-alias"], env=os.environ
    )

    assert result.exit_code == 0
    assert "new-alias" in result.output

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0].get("alias") == "new-alias"


def test_host_alias_by_current_alias(isolated_config: Path, sample_host_data: dict):
    """clm host alias can target host by current alias."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    # Host with existing alias - use copy to avoid fixture mutation
    host_data = sample_host_data.copy()
    host_data["alias"] = "old-alias"
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app, ["host", "alias", "old-alias", "--set", "new-alias"], env=os.environ
    )

    assert result.exit_code == 0
    assert "new-alias" in result.output

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0].get("alias") == "new-alias"


def test_host_alias_duplicate_rejected(isolated_config: Path, sample_host_data: dict):
    """clm host alias rejects duplicate alias."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    # Two hosts, one with alias
    host1 = sample_host_data.copy()
    host2 = {
        "hostname": "192.168.1.101",
        "alias": "existing-alias",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "hardware": {},
        "metadata": {"added_at": "2026-03-21", "last_seen": "2026-03-21", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host1, host2]))

    result = runner.invoke(
        app,
        ["host", "alias", "192.168.1.100", "--set", "existing-alias"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "already in use" in result.output.lower()


def test_host_alias_hostname_conflict(isolated_config: Path, sample_host_data: dict):
    """clm host alias rejects alias that matches existing hostname."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    # Two hosts
    host1 = sample_host_data.copy()
    host2 = {
        "hostname": "192.168.1.101",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "hardware": {},
        "metadata": {"added_at": "2026-03-21", "last_seen": "2026-03-21", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host1, host2]))

    # Try to set alias to existing hostname
    result = runner.invoke(
        app,
        ["host", "alias", "192.168.1.100", "--set", "192.168.1.101"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "conflicts" in result.output.lower()


def test_host_alias_not_found(isolated_config: Path):
    """clm host alias shows error when host not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(
        app, ["host", "alias", "nonexistent", "--set", "new-alias"], env=os.environ
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# Tests for clm host tag command


def test_host_tag_add(isolated_config: Path, sample_host_data: dict):
    """clm host tag --add adds single tag."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app, ["host", "tag", "192.168.1.100", "--add", "production"], env=os.environ
    )

    assert result.exit_code == 0
    assert "production" in result.output

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert "production" in hosts[0]["metadata"]["tags"]


def test_host_tag_add_multiple(isolated_config: Path, sample_host_data: dict):
    """clm host tag --add adds multiple tags."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "tag", "192.168.1.100", "--add", "web", "--add", "api"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "web" in result.output
    assert "api" in result.output

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert "web" in hosts[0]["metadata"]["tags"]
    assert "api" in hosts[0]["metadata"]["tags"]


def test_host_tag_remove(isolated_config: Path, sample_host_data: dict):
    """clm host tag --remove removes existing tag."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    # Add initial tags - use deep copy to avoid fixture mutation
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["tags"] = ["production", "web", "api"]
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app, ["host", "tag", "192.168.1.100", "--remove", "web"], env=os.environ
    )

    assert result.exit_code == 0

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert "web" not in hosts[0]["metadata"]["tags"]
    assert "production" in hosts[0]["metadata"]["tags"]
    assert "api" in hosts[0]["metadata"]["tags"]


def test_host_tag_remove_nonexistent(isolated_config: Path, sample_host_data: dict):
    """clm host tag --remove gracefully handles missing tag."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["tags"] = ["production"]
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app, ["host", "tag", "192.168.1.100", "--remove", "nonexistent"], env=os.environ
    )

    # Should succeed (graceful handling)
    assert result.exit_code == 0

    # Original tag preserved
    hosts = json.loads(hosts_file.read_text())
    assert "production" in hosts[0]["metadata"]["tags"]


def test_host_tag_set(isolated_config: Path, sample_host_data: dict):
    """clm host tag --set replaces all tags."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["tags"] = ["old-tag"]
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        ["host", "tag", "192.168.1.100", "--set", "staging,backend"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "staging" in result.output
    assert "backend" in result.output

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["metadata"]["tags"] == ["staging", "backend"]


def test_host_tag_set_empty(isolated_config: Path, sample_host_data: dict):
    """clm host tag --set '' clears all tags."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["tags"] = ["production", "web"]
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app, ["host", "tag", "192.168.1.100", "--set", ""], env=os.environ
    )

    assert result.exit_code == 0
    assert "cleared" in result.output.lower()

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["metadata"]["tags"] == []


def test_host_tag_mutually_exclusive(isolated_config: Path, sample_host_data: dict):
    """clm host tag rejects --set combined with --add/--remove."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "tag", "192.168.1.100", "--set", "new-tag", "--add", "another"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "--set cannot be combined" in result.output


def test_host_tag_no_operation(isolated_config: Path, sample_host_data: dict):
    """clm host tag without operation shows error."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(app, ["host", "tag", "192.168.1.100"], env=os.environ)

    assert result.exit_code == 1
    assert "specify" in result.output.lower()


def test_host_tag_not_found(isolated_config: Path):
    """clm host tag shows error when host not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(
        app, ["host", "tag", "nonexistent", "--add", "test"], env=os.environ
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# Tests for clm host update command


def test_host_update_alias(isolated_config: Path, sample_host_data: dict):
    """clm host update --alias updates alias."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "update", "192.168.1.100", "--alias", "renamed"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "renamed" in result.output

    hosts = json.loads(hosts_file.read_text())
    assert hosts[0].get("alias") == "renamed"


def test_host_update_description_set(isolated_config: Path, sample_host_data: dict):
    """clm host update --description stores description in metadata."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "update", "192.168.1.100", "--description", "Primary build server"],
        env=os.environ,
    )

    assert result.exit_code == 0
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["metadata"]["description"] == "Primary build server"


def test_host_update_description_clear(isolated_config: Path, sample_host_data: dict):
    """clm host update --description '' clears existing description."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["description"] = "old text"
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        ["host", "update", "192.168.1.100", "--description", ""],
        env=os.environ,
    )

    assert result.exit_code == 0
    hosts = json.loads(hosts_file.read_text())
    assert "description" not in hosts[0]["metadata"]


def test_host_update_replace_tags(isolated_config: Path, sample_host_data: dict):
    """clm host update --tags replaces all tags."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["tags"] = ["old"]
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        ["host", "update", "192.168.1.100", "--tags", "prod,linux"],
        env=os.environ,
    )

    assert result.exit_code == 0
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["metadata"]["tags"] == ["prod", "linux"]


def test_host_update_add_remove_tags(isolated_config: Path, sample_host_data: dict):
    """clm host update --add-tag and --remove-tag modify tags incrementally."""
    import json
    import copy

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = copy.deepcopy(sample_host_data)
    host_data["metadata"]["tags"] = ["web", "api"]
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        [
            "host",
            "update",
            "192.168.1.100",
            "--add-tag",
            "prod",
            "--remove-tag",
            "api",
        ],
        env=os.environ,
    )

    assert result.exit_code == 0
    hosts = json.loads(hosts_file.read_text())
    tags = hosts[0]["metadata"]["tags"]
    assert "prod" in tags
    assert "web" in tags
    assert "api" not in tags


def test_host_update_combined_fields(isolated_config: Path, sample_host_data: dict):
    """clm host update can update alias, description, and tags in one call."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        [
            "host",
            "update",
            "192.168.1.100",
            "--alias",
            "combined",
            "--description",
            "all in one",
            "--tags",
            "a,b",
        ],
        env=os.environ,
    )

    assert result.exit_code == 0
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["alias"] == "combined"
    assert hosts[0]["metadata"]["description"] == "all in one"
    assert hosts[0]["metadata"]["tags"] == ["a", "b"]


def test_host_update_requires_field(isolated_config: Path, sample_host_data: dict):
    """clm host update with no fields shows error."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(app, ["host", "update", "192.168.1.100"], env=os.environ)

    assert result.exit_code == 1
    assert "at least one field" in result.output.lower()


def test_host_update_tags_mutually_exclusive(
    isolated_config: Path, sample_host_data: dict
):
    """--tags cannot combine with --add-tag/--remove-tag."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        [
            "host",
            "update",
            "192.168.1.100",
            "--tags",
            "a,b",
            "--add-tag",
            "c",
        ],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "cannot be combined" in result.output.lower()


def test_host_update_alias_conflict(isolated_config: Path, sample_host_data: dict):
    """clm host update --alias rejects duplicate alias."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    host1 = sample_host_data.copy()
    host2 = {
        "hostname": "192.168.1.101",
        "alias": "taken",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "hardware": {},
        "metadata": {"added_at": "2026-03-21", "last_seen": "2026-03-21", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host1, host2]))

    result = runner.invoke(
        app,
        ["host", "update", "192.168.1.100", "--alias", "taken"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "already in use" in result.output.lower()


def test_host_update_empty_alias_rejected(
    isolated_config: Path, sample_host_data: dict
):
    """clm host update --alias '' is rejected."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "update", "192.168.1.100", "--alias", "   "],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "cannot be empty" in result.output.lower()


def test_host_update_not_found(isolated_config: Path):
    """clm host update shows error when host not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(
        app,
        ["host", "update", "nonexistent", "--alias", "foo"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_host_update_by_alias(isolated_config: Path, sample_host_data: dict):
    """clm host update can target host by current alias."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    # sample_host_data has alias "testhost"
    result = runner.invoke(
        app,
        ["host", "update", "testhost", "--description", "via alias"],
        env=os.environ,
    )

    assert result.exit_code == 0
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["metadata"]["description"] == "via alias"


# Tests for clm host address commands


def test_address_add_success(isolated_config: Path, sample_host_data: dict):
    """clm host address add adds address successfully."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app, ["host", "address", "add", "192.168.1.100", "10.0.0.100"], env=os.environ
    )

    assert result.exit_code == 0
    assert "10.0.0.100" in result.output
    assert "added" in result.output.lower()

    # Verify persisted
    hosts = json.loads(hosts_file.read_text())
    addresses = hosts[0].get("addresses", [])
    assert len(addresses) == 2
    assert any(a["address"] == "10.0.0.100" for a in addresses)


def test_address_add_with_label(isolated_config: Path, sample_host_data: dict):
    """clm host address add with --label stores label."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "address", "add", "192.168.1.100", "10.0.0.100", "--label", "vpn"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "vpn" in result.output

    # Verify label persisted
    hosts = json.loads(hosts_file.read_text())
    addresses = hosts[0].get("addresses", [])
    vpn_addr = [a for a in addresses if a["address"] == "10.0.0.100"][0]
    assert vpn_addr["label"] == "vpn"


def test_address_add_duplicate_fails(isolated_config: Path, sample_host_data: dict):
    """clm host address add fails for duplicate address."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    # Try to add the same address that already exists (hostname)
    result = runner.invoke(
        app,
        ["host", "address", "add", "192.168.1.100", "192.168.1.100"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "already exists" in result.output.lower()


def test_address_remove_success(isolated_config: Path):
    """clm host address remove removes non-primary address."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = {
        "hostname": "192.168.1.100",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "addresses": [
            {
                "address": "192.168.1.100",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.100",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "hardware": {},
        "metadata": {"added_at": "2024-01-01", "last_seen": "2024-01-01", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        ["host", "address", "remove", "192.168.1.100", "10.0.0.100"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "removed" in result.output.lower()

    # Verify removed
    hosts = json.loads(hosts_file.read_text())
    addresses = hosts[0].get("addresses", [])
    assert len(addresses) == 1
    assert addresses[0]["address"] == "192.168.1.100"


def test_address_remove_primary_fails(isolated_config: Path):
    """clm host address remove fails for primary address."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = {
        "hostname": "192.168.1.100",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "addresses": [
            {
                "address": "192.168.1.100",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.100",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "hardware": {},
        "metadata": {"added_at": "2024-01-01", "last_seen": "2024-01-01", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        ["host", "address", "remove", "192.168.1.100", "192.168.1.100"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "cannot remove primary" in result.output.lower()


def test_address_list_shows_all(isolated_config: Path):
    """clm host address list shows all addresses."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = {
        "hostname": "192.168.1.100",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "addresses": [
            {
                "address": "192.168.1.100",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.100",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "hardware": {},
        "metadata": {"added_at": "2024-01-01", "last_seen": "2024-01-01", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app, ["host", "address", "list", "192.168.1.100"], env=os.environ
    )

    assert result.exit_code == 0
    assert "192.168.1.100" in result.output
    assert "10.0.0.100" in result.output
    assert "lan" in result.output
    assert "vpn" in result.output


def test_address_set_primary_success(isolated_config: Path):
    """clm host address set-primary switches primary address."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = {
        "hostname": "192.168.1.100",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "addresses": [
            {
                "address": "192.168.1.100",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.100",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "hardware": {},
        "metadata": {"added_at": "2024-01-01", "last_seen": "2024-01-01", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(
        app,
        ["host", "address", "set-primary", "192.168.1.100", "10.0.0.100"],
        env=os.environ,
    )

    assert result.exit_code == 0
    assert "10.0.0.100" in result.output

    # Verify hostname updated
    hosts = json.loads(hosts_file.read_text())
    assert hosts[0]["hostname"] == "10.0.0.100"


def test_host_list_shows_additional_count(isolated_config: Path):
    """clm host list shows [+N] for hosts with multiple addresses."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    host_data = {
        "hostname": "192.168.1.100",
        "alias": "mybox",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "addresses": [
            {
                "address": "192.168.1.100",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.100",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
            {
                "address": "mybox.example.com",
                "is_primary": False,
                "label": "external",
                "added_at": "2024-01-03T00:00:00Z",
            },
        ],
        "hardware": {},
        "metadata": {"added_at": "2024-01-01", "last_seen": "2024-01-01", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([host_data]))

    result = runner.invoke(app, ["host", "list"], env=os.environ)

    assert result.exit_code == 0
    assert "[+2]" in result.output


def test_host_ps_shows_all_addresses(isolated_config: Path, mock_ssh_client):
    """clm host ps shows all addresses when multiple exist."""
    import json

    create_test_keypair(isolated_config, "192.168.1.100")
    host_data = {
        "hostname": "192.168.1.100",
        "key_id": "192.168.1.100",
        "port": 22,
        "user": "xclm",
        "auth_method": "key",
        "addresses": [
            {
                "address": "192.168.1.100",
                "is_primary": True,
                "label": "lan",
                "added_at": "2024-01-01T00:00:00Z",
            },
            {
                "address": "10.0.0.100",
                "is_primary": False,
                "label": "vpn",
                "added_at": "2024-01-02T00:00:00Z",
            },
        ],
        "hardware": {},
        "metadata": {"added_at": "2024-01-01", "last_seen": "2024-01-01", "tags": []},
    }
    hosts_file = isolated_config / "hosts.json"
    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file.write_text(json.dumps([host_data]))

    with patch(
        "clawrium.core.ssh_connection.paramiko.SSHClient", return_value=mock_ssh_client
    ):
        result = runner.invoke(app, ["host", "ps", "192.168.1.100"], env=os.environ)

    assert result.exit_code == 0
    assert "Addresses:" in result.output
    assert "192.168.1.100" in result.output
    assert "10.0.0.100" in result.output
    assert "(lan)" in result.output
    assert "(vpn)" in result.output


def test_address_add_host_not_found(isolated_config: Path):
    """clm host address add fails when host not found."""
    isolated_config.mkdir(parents=True, exist_ok=True)

    result = runner.invoke(
        app, ["host", "address", "add", "nonexistent-host", "10.0.0.1"], env=os.environ
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_address_add_invalid_empty(isolated_config: Path, sample_host_data: dict):
    """clm host address add rejects empty address."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app, ["host", "address", "add", "192.168.1.100", ""], env=os.environ
    )

    assert result.exit_code == 1
    assert "empty" in result.output.lower()


def test_address_add_invalid_shell_chars(isolated_config: Path, sample_host_data: dict):
    """clm host address add rejects addresses with shell metacharacters."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "address", "add", "192.168.1.100", "host;rm -rf /"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "invalid" in result.output.lower()


def test_address_add_invalid_user_prefix(isolated_config: Path, sample_host_data: dict):
    """clm host address add rejects addresses with @ symbol."""
    import json

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_file = isolated_config / "hosts.json"
    hosts_file.write_text(json.dumps([sample_host_data]))

    result = runner.invoke(
        app,
        ["host", "address", "add", "192.168.1.100", "user@host.example.com"],
        env=os.environ,
    )

    assert result.exit_code == 1
    assert "@" in result.output

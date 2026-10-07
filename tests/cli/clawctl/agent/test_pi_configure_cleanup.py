"""Pi configure cleanup failures retain the local recovery attachment."""

import json

import paramiko
import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.lifecycle_canonical import CanonicalSyncResult

runner = CliRunner()


def _add_pi_agent(fleet_dir) -> None:
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["pi-test"] = {
        "type": "pi",
        "agent_name": "pi-test",
        "version": "0.73.1",
        "status": "installed",
        "installed_at": "2026-10-06T00:00:00+00:00",
    }
    hosts_path.write_text(json.dumps(hosts))


@pytest.mark.parametrize(
    ("transport_error", "raw_detail"),
    [
        (EOFError, "EOF cleanup secret OPENROUTER_API_KEY=should-not-print"),
        (
            paramiko.SSHException,
            "SSH cleanup secret OPENROUTER_API_KEY=should-not-print",
        ),
    ],
    ids=("eof", "ssh"),
)
def test_pi_configure_cleanup_transport_failure_retains_attachment(
    fleet_dir, monkeypatch, transport_error, raw_detail
):
    """A cleanup transport failure gives a safe detach retry instead of a traceback."""
    # The security-hardening branch validates existing config-dir modes;
    # make this disk-backed fixture private before exercising the CLI.
    fleet_dir.chmod(0o700)
    _add_pi_agent(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _name: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: CanonicalSyncResult(
            False, "pi-test", "host", (), (), (), error="partial sync failed"
        ),
    )

    def revoke(**_kwargs):
        raise transport_error(raw_detail)

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )

    assert result.exit_code != 0
    assert (
        "retry: clawctl agent provider detach router --agent pi-test" in result.output
    )
    assert "Traceback" not in result.output
    assert raw_detail not in result.output
    assert "OPENROUTER_API_KEY" not in result.output
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["pi-test"]["providers"] == ["router"]


@pytest.mark.parametrize(
    ("sync_error", "sync_detail"),
    [
        (EOFError, "EOF sync secret OPENROUTER_API_KEY=should-not-print"),
        (
            paramiko.SSHException,
            "SSH sync secret OPENROUTER_API_KEY=should-not-print",
        ),
        (OSError, "OS sync secret OPENROUTER_API_KEY=should-not-print"),
    ],
    ids=("eof", "ssh", "oserror"),
)
@pytest.mark.parametrize(
    ("cleanup_error", "cleanup_detail"),
    [
        (None, None),
        (EOFError, "EOF cleanup secret OPENROUTER_API_KEY=should-not-print"),
    ],
    ids=("cleanup-succeeds", "cleanup-fails"),
)
def test_pi_configure_sync_transport_failure_compensates_safely(
    fleet_dir,
    monkeypatch,
    sync_error,
    sync_detail,
    cleanup_error,
    cleanup_detail,
):
    """Sync transport failures use compensation without exposing transport details."""
    fleet_dir.chmod(0o700)
    _add_pi_agent(fleet_dir)
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _name: {
            "name": "router",
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
    )

    def sync(*_args, **_kwargs):
        raise sync_error(sync_detail)

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)

    if cleanup_error is None:
        monkeypatch.setattr(
            "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
            lambda **_kwargs: None,
        )
    else:

        def revoke(**_kwargs):
            raise cleanup_error(cleanup_detail)

        monkeypatch.setattr(
            "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke
        )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "pi-test",
            "--stage",
            "providers",
            "--provider",
            "router",
        ],
    )

    assert result.exit_code != 0
    assert (
        "Pi provider configuration failed: remote synchronization did not finish"
        in result.output
    )
    assert "Traceback" not in result.output
    assert sync_detail not in result.output
    assert "OPENROUTER_API_KEY" not in result.output
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    if cleanup_error is None:
        assert hosts[0]["agents"]["pi-test"].get("providers", []) == []
    else:
        assert hosts[0]["agents"]["pi-test"]["providers"] == ["router"]
        assert (
            "retry: clawctl agent provider detach router --agent pi-test"
            in result.output
        )
        assert cleanup_detail not in result.output

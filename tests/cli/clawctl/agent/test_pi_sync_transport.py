"""Pi sync transport errors have safe, actionable CLI output."""

import json

import paramiko
import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.lifecycle_canonical import CanonicalSyncError

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
        "providers": ["router"],
    }
    hosts_path.write_text(json.dumps(hosts))


@pytest.mark.parametrize(
    ("transport_error", "raw_detail"),
    [
        (EOFError, "EOF secret OPENROUTER_API_KEY=should-not-print"),
        (paramiko.SSHException, "SSH secret OPENROUTER_API_KEY=should-not-print"),
        (OSError, "OS secret OPENROUTER_API_KEY=should-not-print"),
    ],
    ids=("eof", "ssh", "oserror"),
)
def test_pi_sync_transport_failure_is_safe_and_retains_attachment(
    fleet_dir, monkeypatch, transport_error, raw_detail
):
    """Expected transport errors do not escape or mutate the local attachment."""
    # The security-hardening branch validates existing config-dir modes;
    # make this disk-backed fixture private before exercising the CLI.
    fleet_dir.chmod(0o700)
    _add_pi_agent(fleet_dir)

    def sync(*_args, **_kwargs):
        raise transport_error(raw_detail)

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)

    result = runner.invoke(app, ["agent", "sync", "pi-test"])

    assert result.exit_code != 0
    assert "Pi sync failed: remote synchronization did not finish" in result.output
    assert "Traceback" not in result.output
    assert raw_detail not in result.output
    assert "OPENROUTER_API_KEY" not in result.output
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["pi-test"]["providers"] == ["router"]


def test_pi_sync_canonical_error_detail_is_unchanged(fleet_dir, monkeypatch):
    """Canonical sync errors retain their existing structured diagnostic."""
    fleet_dir.chmod(0o700)
    _add_pi_agent(fleet_dir)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CanonicalSyncError("canonical synchronization failed")
        ),
    )

    result = runner.invoke(app, ["agent", "sync", "pi-test"])

    assert result.exit_code != 0
    assert "Pi sync failed: canonical synchronization failed" in result.output
    assert "remote synchronization did not finish" not in result.output

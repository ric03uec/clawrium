"""Tests for `clawctl host validate <hostname>` (Phase 3 of #11 / #945)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _stamp_nemoclaw(fleet_dir: Path, *, sandbox_name: str = "wise-hypatia") -> None:
    """Ensure the fixture's openclaw record carries Phase-3 runtime keys."""
    hosts_path = Path(fleet_dir) / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    config = hosts[0]["agents"]["openclaw"].setdefault("config", {})
    config["runtime"] = "nemoclaw"
    config["nemoclaw_version"] = "v0.0.97"
    config["sandbox_name"] = sandbox_name
    hosts_path.write_text(json.dumps(hosts, indent=2))


def _strip_bare_openclaw(fleet_dir: Path) -> None:
    """Leave the openclaw agent record without a sandbox_name so the
    validate command hits its `legacy` short-circuit."""
    hosts_path = Path(fleet_dir) / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["openclaw"].setdefault("config", {})
    hosts[0]["agents"]["openclaw"]["config"].pop("sandbox_name", None)
    hosts[0]["agents"]["openclaw"]["config"].pop("runtime", None)
    hosts_path.write_text(json.dumps(hosts, indent=2))


def test_validate_healthy_when_playbook_succeeds(fleet_dir, monkeypatch) -> None:
    _stamp_nemoclaw(fleet_dir)

    from clawrium.core import lifecycle

    monkeypatch.setattr(
        lifecycle, "_run_lifecycle_playbook", lambda **_kw: (True, None)
    )
    result = runner.invoke(app, ["host", "validate", "wolf-i"])
    assert result.exit_code == 0, result.output
    assert "wise-hypatia" in result.output
    assert "healthy" in result.output


def test_validate_unhealthy_when_playbook_fails(fleet_dir, monkeypatch) -> None:
    _stamp_nemoclaw(fleet_dir)

    from clawrium.core import lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_run_lifecycle_playbook",
        lambda **_kw: (False, "sandbox stopped"),
    )
    result = runner.invoke(app, ["host", "validate", "wolf-i"])
    assert result.exit_code == 1
    assert "unhealthy" in result.output
    assert "sandbox stopped" in result.output


def test_validate_legacy_bare_short_circuits(fleet_dir, monkeypatch) -> None:
    _strip_bare_openclaw(fleet_dir)

    from clawrium.core import lifecycle

    called: list[bool] = []

    def _sentinel(**_kw):
        called.append(True)
        return True, None

    monkeypatch.setattr(lifecycle, "_run_lifecycle_playbook", _sentinel)
    result = runner.invoke(app, ["host", "validate", "wolf-i"])
    assert result.exit_code == 1
    assert "legacy" in result.output
    assert "remove + re-create" in result.output
    assert called == [], (
        "playbook must not run for a legacy record — the "
        "short-circuit must trip before dispatch"
    )


def test_validate_host_without_openclaw_exits_zero_with_note(
    fleet_dir, monkeypatch
) -> None:
    # `kevin` has no agents at all in the fleet fixture.
    from clawrium.core import lifecycle

    monkeypatch.setattr(
        lifecycle, "_run_lifecycle_playbook", lambda **_kw: (True, None)
    )
    result = runner.invoke(app, ["host", "validate", "kevin"])
    assert result.exit_code == 0
    assert "no openclaw agents" in result.output


def test_validate_json_output(fleet_dir, monkeypatch) -> None:
    _stamp_nemoclaw(fleet_dir)

    from clawrium.core import lifecycle

    monkeypatch.setattr(
        lifecycle, "_run_lifecycle_playbook", lambda **_kw: (True, None)
    )
    result = runner.invoke(app, ["host", "validate", "wolf-i", "-o", "json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed and parsed[0]["status"] == "healthy"
    assert parsed[0]["sandbox"] == "wise-hypatia"

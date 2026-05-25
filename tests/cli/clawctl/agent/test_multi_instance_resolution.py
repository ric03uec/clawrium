"""Regression tests for bug #516 — lifecycle verb key resolution.

Pre-fix behaviour: `safe_resolve_agent(name)` returns the agent's *type*
string as its second tuple element (per its own docstring — see
`cli/clawctl/agent/_shared.py`). The lifecycle verbs (configure, start,
stop, sync, restart, delete) used that value as `agent_name=...` in
their core-lifecycle calls. On any host with >1 agent of the same type,
this fails:

- `start audit-2` would call `start_agent(claw_name='zeroclaw',
  agent_name='zeroclaw')` — both kwargs collapse to the type. Core
  side then can't disambiguate, either targets the wrong agent or
  errors out.

These tests fixture a multi-instance host (three zeroclaws keyed by
instance name) and assert each verb passes the *correct* instance name
to its core call. Without the fix, every parametrize case fails with
`agent_name == "zeroclaw"` instead of the expected `"audit-N"`.

The single-instance happy path is already covered by
`test_lifecycle.py`; this file deliberately limits scope to the
multi-instance dimension.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def multi_instance_fleet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fleet with 3 zeroclaws keyed by instance name on a single host.

    Mirrors the wolf-i shape that surfaced bug #516 during issue #435
    Gate 3: same type, distinct instance names, modern key-by-name.
    """
    config_dir = tmp_path / "clawrium"
    config_dir.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def _agent(name: str) -> dict:
        return {
            "type": "zeroclaw",
            "agent_name": name,
            "version": "0.4.2",
            "installed_at": _utcnow(),
            "status": "installed",
            "onboarding": {
                "state": "ready",
                "stages": {
                    "providers": {"state": "complete", "completed_at": _utcnow()},
                    "identity": {"state": "complete", "completed_at": _utcnow()},
                    "channels": {"state": "skipped"},
                    "validate": {"state": "complete", "completed_at": _utcnow()},
                },
            },
            "config": {"skills": []},
        }

    hosts = [
        {
            "hostname": "10.0.0.1",
            "key_id": "10.0.0.1",
            "port": 22,
            "user": "alice",
            "auth_method": "key",
            "alias": "wolf-i",
            "aliases": ["wolf-i"],
            "addresses": [
                {
                    "address": "10.0.0.1",
                    "is_primary": True,
                    "label": None,
                    "added_at": _utcnow(),
                }
            ],
            "metadata": {
                "added_at": _utcnow(),
                "last_seen": _utcnow(),
                "labels": {},
            },
            "hardware": {
                "architecture": "x86_64",
                "processor_cores": 8,
                "memtotal_mb": 16000,
            },
            "agents": {
                "audit-1": _agent("audit-1"),
                "audit-2": _agent("audit-2"),
                "audit-3": _agent("audit-3"),
            },
        }
    ]
    (config_dir / "hosts.json").write_text(json.dumps(hosts, indent=2))
    return config_dir


@pytest.mark.parametrize(
    "verb,mock_target,past_tense",
    [
        ("start", "clawrium.cli.clawctl.agent.start.start_agent", "started"),
        ("stop", "clawrium.cli.clawctl.agent.stop.stop_agent", "stopped"),
        ("restart", "clawrium.cli.clawctl.agent.restart.restart_agent", "restarted"),
    ],
)
@pytest.mark.parametrize("instance", ["audit-1", "audit-2", "audit-3"])
def test_lifecycle_verb_passes_instance_name_not_type(
    multi_instance_fleet,
    monkeypatch: pytest.MonkeyPatch,
    verb: str,
    mock_target: str,
    past_tense: str,
    instance: str,
) -> None:
    """Each lifecycle verb must pass the *instance name* as `agent_name`,
    not the type string. Pre-fix this passed `agent_name='zeroclaw'` for
    every instance, so the second/third audit-* agent would either be
    targeted incorrectly or error out at the core level.
    """
    captured: dict = {}

    def capturing_call(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(mock_target, capturing_call)
    result = runner.invoke(app, ["agent", verb, instance])

    assert result.exit_code == 0, f"{verb} {instance} failed: {result.output}"
    assert captured.get("agent_name") == instance, (
        f"{verb} {instance}: expected agent_name={instance!r}, got "
        f"{captured.get('agent_name')!r} (type was {captured.get('claw_name')!r})"
    )
    assert captured.get("claw_name") == "zeroclaw", (
        f"{verb} {instance}: expected claw_name='zeroclaw', got "
        f"{captured.get('claw_name')!r}"
    )


@pytest.mark.parametrize("instance", ["audit-1", "audit-2", "audit-3"])
def test_sync_passes_instance_name_not_type(
    multi_instance_fleet,
    monkeypatch: pytest.MonkeyPatch,
    instance: str,
) -> None:
    """sync has a different mock signature (returns dict with success).
    Verify the same instance/type contract.
    """
    captured: dict = {}

    def capturing_sync(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.sync.sync_agent", capturing_sync
    )
    result = runner.invoke(app, ["agent", "sync", instance])

    assert result.exit_code == 0, f"sync {instance} failed: {result.output}"
    assert captured.get("agent_name") == instance
    assert captured.get("claw_name") == "zeroclaw"


@pytest.mark.parametrize("instance", ["audit-1", "audit-2", "audit-3"])
def test_delete_passes_instance_name_not_type(
    multi_instance_fleet,
    monkeypatch: pytest.MonkeyPatch,
    instance: str,
) -> None:
    """delete is the verb where the bug bit hardest at Gate 3 — the
    remote cleanup script rejected the type-as-name with 'Multiple
    zeroclaw agents found. Specify instance name: …'.
    """
    captured: dict = {}

    def capturing_remove(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.delete.remove_agent", capturing_remove
    )
    result = runner.invoke(app, ["agent", "delete", instance, "--yes"])

    assert result.exit_code == 0, f"delete {instance} failed: {result.output}"
    assert captured.get("agent_name") == instance
    assert captured.get("claw_name") == "zeroclaw"


@pytest.mark.parametrize("instance", ["audit-1", "audit-2", "audit-3"])
def test_configure_passes_instance_name_to_onboarding(
    multi_instance_fleet,
    monkeypatch: pytest.MonkeyPatch,
    instance: str,
) -> None:
    """configure --stage validate must call `get_onboarding_state` with
    the instance name as `claw_name`. Pre-fix it called with the type
    string, surfacing `AgentNotFoundError: Agent 'zeroclaw' not found
    on host 'wolf-i'`.
    """
    from clawrium.core.onboarding import OnboardingState

    captured_get: dict = {}
    captured_run: dict = {}

    def capturing_get(host, claw_name, **_):
        captured_get["host"] = host
        captured_get["claw_name"] = claw_name
        return OnboardingState.READY

    def capturing_run(agent_type, host, claw_name, stage, **_):
        captured_run["agent_type"] = agent_type
        captured_run["host"] = host
        captured_run["claw_name"] = claw_name
        captured_run["stage"] = stage
        return True

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_onboarding_state",
        capturing_get,
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.run_stage",
        capturing_run,
    )

    result = runner.invoke(
        app, ["agent", "configure", instance, "--stage", "validate"]
    )
    assert result.exit_code == 0, f"configure {instance} failed: {result.output}"
    assert captured_get["claw_name"] == instance
    assert captured_run["claw_name"] == instance
    assert captured_run["agent_type"] == "zeroclaw"

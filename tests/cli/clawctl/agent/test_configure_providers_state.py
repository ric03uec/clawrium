"""Issue #541: `--stage providers --provider X` drives the onboarding
state machine forward and is idempotent across re-runs.

Before the fix, the v2 verb delegated to `core.onboarding.run_stage`,
which is a placeholder — it flipped the per-stage `status` flag but
never advanced the outer `state`, never pushed the provider config to
the remote host, and silently corrupted the onboarding record by
leaving `providers.provider_id = null` while marking the stage
complete. That stranded the agent at `state=pending` and blocked
every subsequent stage and `agent start`.

The fix routes the providers stage through `sync_agent`, which is the
same reconcile path that `clawctl agent sync` uses. These tests pin
the new contract: the provider attachment lands in `agents.<n>.providers`
(replace semantics, not append), `sync_agent` is invoked with the
agent's key, and a sync failure surfaces a clean CLI error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.hosts import HostsFileCorruptedError
from clawrium.core.lifecycle import LifecycleError
from clawrium.core.providers.storage import ProvidersFileCorruptedError

# `emit_error` writes to stderr. Current CliRunner merges stderr into
# `result.output` by default — that is what makes `"X in result.output"`
# assertions on error paths work below.
runner = CliRunner()


def _read_hosts(fleet_dir: Path) -> list[dict]:
    return json.loads((fleet_dir / "hosts.json").read_text())


def _stub_sync_agent_success(monkeypatch, captured: dict[str, Any]) -> None:
    def fake_sync_agent(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "agent": kwargs.get("agent_name"),
            "host": kwargs.get("hostname"),
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": None,
        }

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent",
        fake_sync_agent,
    )


def _stub_provider_registry(monkeypatch, provider_name: str = "clawrium-glm51") -> None:
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda name: {
            "name": provider_name,
            "type": "openai",
            "endpoint": "https://example.invalid",
            "default_model": "glm-5.1",
        }
        if name == provider_name
        else None,
    )


def test_providers_stage_with_provider_writes_attachment_and_invokes_sync(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """`--stage providers --provider X` writes the attachment into
    `agents.<key>.providers` and delegates to `sync_agent`.
    """
    _stub_provider_registry(monkeypatch)
    captured: dict[str, Any] = {}
    _stub_sync_agent_success(monkeypatch, captured)

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "stage providers complete" in result.output

    hosts = _read_hosts(fleet_dir)
    agent_record = hosts[0]["agents"]["openclaw"]
    assert agent_record["providers"] == ["clawrium-glm51"]

    assert captured["agent_name"] == "openclaw"
    assert captured["claw_name"] == "openclaw"
    assert captured["hostname"] == "10.0.0.1"


def test_providers_stage_replaces_existing_attachment(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """Idempotent re-assign: a second `--stage providers --provider Y` on
    an agent that already has provider X attached replaces, not appends.
    """
    _stub_provider_registry(monkeypatch, provider_name="clawrium-glm52")
    _stub_sync_agent_success(monkeypatch, {})

    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["openclaw"]["providers"] = ["clawrium-glm51"]
    hosts_path.write_text(json.dumps(hosts))

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm52",
        ],
    )

    assert result.exit_code == 0, result.output
    hosts_after = _read_hosts(fleet_dir)
    assert hosts_after[0]["agents"]["openclaw"]["providers"] == ["clawrium-glm52"]


def test_providers_stage_unknown_provider_fails_cleanly(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """Unknown provider name surfaces a 'not registered' error before
    any sync runs. No `providers` attachment is written.
    """
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider",
        lambda _name: None,
    )

    called = {"sync": False}

    def fake_sync_agent(**_kwargs):
        called["sync"] = True
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", fake_sync_agent
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "bogus-provider",
        ],
    )

    assert result.exit_code != 0
    assert "not registered" in result.output
    assert called["sync"] is False
    hosts = _read_hosts(fleet_dir)
    assert "providers" not in hosts[0]["agents"]["openclaw"]


def test_providers_stage_sync_failure_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """A `sync_agent` failure (e.g. Ansible push) surfaces as a clean
    CLI error rather than a traceback.
    """
    _stub_provider_registry(monkeypatch)

    def fake_sync_agent(**_kwargs):
        return {
            "success": False,
            "agent": "openclaw",
            "host": "10.0.0.1",
            "operation": "sync",
            "pid": None,
            "started_at": None,
            "error": "Configure failed: ansible push exited 2",
        }

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", fake_sync_agent
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "configure stage failed" in result.output
    assert "ansible push exited 2" in result.output


def test_providers_stage_sync_agent_lifecycle_error_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """B4: `sync_agent` raising `LifecycleError` (vs returning a dict
    with success=False) is the live `except` path. Verify it surfaces a
    clean message rather than a traceback.
    """
    _stub_provider_registry(monkeypatch)

    def raising_sync(**_kwargs):
        raise LifecycleError("ansible rc=2")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", raising_sync
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "configure stage failed" in result.output
    assert "ansible rc=2" in result.output


def test_providers_stage_corrupt_providers_file_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """B5: A corrupt `providers.json` must surface a clean error and
    must NOT call `sync_agent` (the attachment never lands).
    """

    def raise_corrupt(_name):
        raise ProvidersFileCorruptedError("malformed json near line 7")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.get_provider", raise_corrupt
    )

    called = {"sync": False}

    def fake_sync_agent(**_kwargs):
        called["sync"] = True
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", fake_sync_agent
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "malformed json" in result.output
    assert "providers.json" in result.output
    assert called["sync"] is False


def test_providers_stage_update_host_corrupt_hosts_file_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """ATX iter-3 W1: `update_host` raising `HostsFileCorruptedError`
    (malformed hosts.json) must surface a clean message — not a raw
    traceback exposing config-dir paths.
    """
    _stub_provider_registry(monkeypatch)

    def raise_corrupt(*_a, **_k):
        raise HostsFileCorruptedError("hosts.json: schema mismatch")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.update_host", raise_corrupt
    )

    called = {"sync": False}

    def fake_sync_agent(**_kwargs):
        called["sync"] = True
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", fake_sync_agent
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "hosts.json" in result.output
    assert called["sync"] is False


def test_providers_stage_update_host_oserror_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """ATX iter-3 W6: the `OSError` arm of the broadened `update_host`
    catch (e.g. read-only filesystem) must surface a clean message and
    must NOT leak the absolute hosts.json path via `str(OSError)`.
    """
    _stub_provider_registry(monkeypatch)

    def raise_oserror(*_a, **_k):
        raise OSError("[Errno 30] Read-only file system: '/secret/path/hosts.json'")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.update_host", raise_oserror
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "could not write hosts.json" in result.output
    # ATX iter-3 W4: confirm the leaking path is NOT in the error output.
    assert "/secret/path/hosts.json" not in result.output


def test_providers_stage_update_host_lifecycle_error_surfaces_clean_error(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """B7: `update_host` raising `LifecycleError` (e.g. agent record
    raced away between resolve and write) must surface a clean error.
    """
    _stub_provider_registry(monkeypatch)

    def raise_lifecycle(*_a, **_k):
        raise LifecycleError("agent record missing from host")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.update_host", raise_lifecycle
    )

    called = {"sync": False}

    def fake_sync_agent(**_kwargs):
        called["sync"] = True
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", fake_sync_agent
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "agent record missing" in result.output
    assert called["sync"] is False


def test_providers_stage_sync_failure_without_error_field_uses_fallback(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """W6: When `sync_agent` returns `{'success': False}` with no
    `error` key, the `'unknown error'` fallback must surface.
    """
    _stub_provider_registry(monkeypatch)

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent",
        lambda **_k: {"success": False},
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code != 0
    assert "unknown error" in result.output


def test_providers_stage_forwards_all_sync_events_to_user(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """W1/W7: the `on_event` callback forwards all sync progress lines,
    not just warning-prefixed ones — operators need to see ansible
    progress during the 30–60s push.
    """
    _stub_provider_registry(monkeypatch)

    def streaming_sync(**kwargs):
        on_event = kwargs.get("on_event")
        assert on_event is not None
        on_event("sync", "Configuring wise-hypatia...")
        on_event("sync", "warning: could not write state=READY")
        return {"success": True}

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.sync_agent", streaming_sync
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "clawrium-glm51",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Configuring wise-hypatia" in result.output
    assert "could not write state=READY" in result.output


def test_providers_stage_requires_provider_flag_on_tty(
    fleet_dir, monkeypatch
) -> None:
    """B1: `--stage providers` without `--provider` must fail
    unconditionally — without this guard the verb falls through to the
    placeholder `run_stage` path and silently corrupts the onboarding
    record. Patch both `stdin_is_tty` (in case the fixture binding
    diverges from `configure.py`'s direct import — ATX iter-3 W3) and
    `run_stage` (poison) so a regression that bypasses the guard fails
    the test loudly instead of vacuously passing.
    """
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.stdin_is_tty",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.run_stage",
        lambda *_a, **_k: pytest.fail("regression: providers fell through to run_stage"),
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
        ],
    )

    assert result.exit_code != 0
    assert "--provider" in result.output

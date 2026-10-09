"""Public disk-backed CLI coverage for Pi Codex provider replacement (#1040)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import configure as configure_mod
from clawrium.core.lifecycle_canonical import CanonicalSyncError, CanonicalSyncResult

AGENT = "pi-codex-replacement"
CODEX = "codex"
ROUTER = "router"
BEDROCK = "bedrock"


def _providers() -> list[dict[str, str]]:
    return [
        {
            "name": CODEX,
            "type": "openai-codex",
            "default_model": "gpt-5.4",
        },
        {
            "name": ROUTER,
            "type": "openrouter",
            "default_model": "openai/gpt-4o",
        },
        {
            "name": BEDROCK,
            "type": "bedrock",
            "credential_source": "aws-sso",
            "default_model": "anthropic.claude-3-haiku-20240307-v1:0",
            "aws_profile": "clawrium",
            "region": "us-east-1",
            "sso_start_url": "https://example.awsapps.com/start",
            "sso_region": "us-east-1",
            "sso_account_id": "123456789012",
            "sso_role_name": "BedrockRole",
        },
    ]


def _seed_pi(fleet_dir: Path) -> Path:
    """Seed the real hosts/providers stores used by the public command."""
    fleet_dir.chmod(0o700)
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"][AGENT] = {
        "type": "pi",
        "agent_name": AGENT,
        "status": "installed",
        "installed_at": "2026-01-01T00:00:00+00:00",
        "providers": [CODEX],
    }
    hosts_path.write_text(json.dumps(hosts))
    (fleet_dir / "providers.json").write_text(json.dumps(_providers()))
    return hosts_path


def _attachment(hosts_path: Path, *, agent: str = AGENT) -> list[str]:
    return json.loads(hosts_path.read_text())[0]["agents"][agent]["providers"]


def _recovery_required(hosts_path: Path, *, agent: str = AGENT) -> bool:
    return (
        json.loads(hosts_path.read_text())[0]["agents"][agent].get(
            "pi_codex_auth_recovery"
        )
        is True
    )


def _configure(provider: str = ROUTER, *, agent: str = AGENT):
    return CliRunner().invoke(
        app,
        ["agent", "configure", agent, "--stage", "providers", "--provider", provider],
    )


@pytest.mark.parametrize("target", [ROUTER, BEDROCK])
def test_codex_replacement_removes_auth_before_disk_attachment_and_sync(
    fleet_dir, monkeypatch, target
):
    """Codex -> OpenRouter/Bedrock removes dedicated auth before B is durable."""
    hosts_path = _seed_pi(fleet_dir)
    events: list[str] = []

    def revoke(*, agent_name: str, host: dict) -> None:
        assert agent_name == AGENT
        assert host["hostname"] == "10.0.0.1"
        assert _attachment(hosts_path) == [CODEX]
        events.append("remove-dedicated-codex-auth")

    def sync(name: str, **_kwargs) -> CanonicalSyncResult:
        assert name == AGENT
        assert _attachment(hosts_path) == [target]
        events.append(f"sync-after-{target}-attachment")
        return CanonicalSyncResult(True, AGENT, "10.0.0.1", (), (), ())

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_codex", revoke)
    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)
    if target == BEDROCK:
        monkeypatch.setattr(
            "clawrium.core.lifecycle_canonical.revoke_pi_openrouter",
            lambda **_kwargs: events.append("clear-bedrock-cache"),
        )

    result = _configure(target)

    assert result.exit_code == 0, result.output
    assert _attachment(hosts_path) == [target]
    assert _recovery_required(hosts_path) is False
    expected_events = ["remove-dedicated-codex-auth"]
    if target == BEDROCK:
        expected_events.append("clear-bedrock-cache")
    expected_events.append(f"sync-after-{target}-attachment")
    assert events == expected_events


def test_codex_replacement_cleanup_failure_retains_attachment_and_retries(
    fleet_dir, monkeypatch
):
    """A failed auth removal does not switch metadata or start target sync."""
    hosts_path = _seed_pi(fleet_dir)
    remote_auth_present = True
    sync_calls: list[str] = []

    def revoke(**_kwargs) -> None:
        nonlocal remote_auth_present
        if remote_auth_present:
            raise OSError("unreachable")

    def sync(name: str, **_kwargs) -> CanonicalSyncResult:
        sync_calls.append(name)
        assert _attachment(hosts_path) == [ROUTER]
        return CanonicalSyncResult(True, AGENT, "10.0.0.1", (), (), ())

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_codex", revoke)
    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)

    failed = _configure()

    assert failed.exit_code != 0
    assert "cleanup did not finish" in failed.output
    assert "retry the same provider configure command" in failed.output
    assert _attachment(hosts_path) == [CODEX]
    assert sync_calls == []

    remote_auth_present = False
    retried = _configure()

    assert retried.exit_code == 0, retried.output
    assert _attachment(hosts_path) == [ROUTER]
    assert sync_calls == [AGENT]


def test_codex_same_provider_refresh_never_removes_auth(fleet_dir, monkeypatch):
    """A Codex refresh keeps its dedicated OAuth document intact."""
    hosts_path = _seed_pi(fleet_dir)

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not revoke")),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda name, **_kwargs: CanonicalSyncResult(
            _attachment(hosts_path) == [CODEX], name, "10.0.0.1", (), (), ()
        ),
    )

    result = _configure(CODEX)

    assert result.exit_code == 0, result.output
    assert _attachment(hosts_path) == [CODEX]


def test_codex_cleanup_metadata_failure_sanitizes_stale_agent_login_hint(
    fleet_dir, monkeypatch
):
    """A hostile persisted agent name cannot spoof the recovery command."""
    hosts_path = _seed_pi(fleet_dir)
    hostile_agent = "pi-codex\u202e-switch"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"][hostile_agent] = hosts[0]["agents"].pop(AGENT)
    hosts[0]["agents"][hostile_agent]["agent_name"] = hostile_agent
    hosts_path.write_text(json.dumps(hosts))

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex", lambda **_kwargs: None
    )
    real_update = configure_mod.update_host
    update_calls = 0

    def fail_metadata_update(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 1:
            return real_update(*args, **kwargs)
        raise OSError()

    monkeypatch.setattr(configure_mod, "update_host", fail_metadata_update)

    result = _configure(agent=hostile_agent)

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "\u202e" not in result.output
    assert f"clawctl agent provider login {CODEX} --agent pi-codex-switch" in result.output
    assert _recovery_required(hosts_path, agent=hostile_agent)


def test_codex_cleanup_metadata_failure_sanitizes_stale_provider_login_hint(
    fleet_dir, monkeypatch
):
    """A hostile persisted selection cannot spoof the recovery command."""
    hosts_path = _seed_pi(fleet_dir)
    hostile_provider = "codex\u202e-switch"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"][AGENT]["providers"] = [hostile_provider]
    hosts_path.write_text(json.dumps(hosts))
    providers_path = fleet_dir / "providers.json"
    providers = json.loads(providers_path.read_text())
    providers[0]["name"] = hostile_provider
    providers_path.write_text(json.dumps(providers))

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex", lambda **_kwargs: None
    )
    real_update = configure_mod.update_host
    update_calls = 0

    def fail_metadata_update(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 1:
            return real_update(*args, **kwargs)
        raise OSError()

    monkeypatch.setattr(configure_mod, "update_host", fail_metadata_update)

    result = _configure()

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "\u202e" not in result.output
    assert (
        f"clawctl agent provider login codex-switch --agent {AGENT}" in result.output
    )
    assert _attachment(hosts_path) == [hostile_provider]
    assert _recovery_required(hosts_path)


def test_codex_to_bedrock_cleanup_failure_reports_stale_codex_relogin(
    fleet_dir, monkeypatch
):
    """A post-purge Bedrock cleanup failure leaves Codex selected but logged out."""
    hosts_path = _seed_pi(fleet_dir)
    events: list[str] = []

    def revoke_codex(**_kwargs) -> None:
        events.append("codex-auth-purged")

    def revoke_bedrock(**_kwargs) -> None:
        events.append("bedrock-cleanup-failed")
        raise CanonicalSyncError("cache cleanup failed")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex", revoke_codex
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_openrouter", revoke_bedrock
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not sync")),
    )

    result = _configure(BEDROCK)

    assert result.exit_code != 0
    assert _attachment(hosts_path) == [CODEX]
    assert _recovery_required(hosts_path)
    assert events == ["codex-auth-purged", "bedrock-cleanup-failed"]
    assert "local Codex selection was retained but remote OAuth was removed" in result.output
    assert f"clawctl agent provider login {CODEX} --agent {AGENT}" in result.output
    assert "Traceback" not in result.output


def test_codex_marker_write_failure_stops_before_remote_auth_purge(
    fleet_dir, monkeypatch
):
    """`emit_error` exits, so a failed durable gate cannot reach remote revoke."""
    hosts_path = _seed_pi(fleet_dir)

    monkeypatch.setattr(
        configure_mod,
        "update_host",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not revoke")),
    )

    result = _configure()

    assert result.exit_code != 0
    assert _attachment(hosts_path) == [CODEX]
    assert _recovery_required(hosts_path) is False
    assert "could not record recovery state; remote OAuth was not changed" in result.output
    assert "repair local storage and retry the target provider configure command" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("failure", ["result", "transport"])
def test_codex_sync_failure_restores_relogin_gated_codex_selection(
    fleet_dir, monkeypatch, failure
):
    """A post-purge sync failure cannot restore Codex without its recovery gate."""
    hosts_path = _seed_pi(fleet_dir)
    events: list[str] = []

    def revoke(**_kwargs) -> None:
        events.append("codex-auth-purged")

    def sync(*_args, **_kwargs):
        events.append("target-sync-failed")
        if failure == "transport":
            raise EOFError("transport failed")
        return CanonicalSyncResult(
            False, AGENT, "10.0.0.1", (), (), (), error="sync failed"
        )

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_codex", revoke)
    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)

    result = _configure()

    assert result.exit_code != 0
    assert events == ["codex-auth-purged", "target-sync-failed"]
    assert _attachment(hosts_path) == [CODEX]
    assert _recovery_required(hosts_path)
    assert "local Codex selection requires native re-login" in result.output
    assert f"clawctl agent provider login {CODEX} --agent {AGENT}" in result.output

    same_selection = _configure(CODEX)
    assert same_selection.exit_code != 0
    assert "requires native re-login" in same_selection.output


def test_codex_sync_failure_rollback_write_failure_keeps_target_selection(
    fleet_dir, monkeypatch
):
    """If rollback cannot persist, do not misrepresent either selection as safe."""
    hosts_path = _seed_pi(fleet_dir)
    real_update = configure_mod.update_host
    update_calls = 0

    def update_until_rollback(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 3:
            raise OSError("disk full")
        return real_update(*args, **kwargs)

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.revoke_pi_codex", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: CanonicalSyncResult(
            False, AGENT, "10.0.0.1", (), (), (), error="sync failed"
        ),
    )
    monkeypatch.setattr(configure_mod, "update_host", update_until_rollback)

    result = _configure()

    assert result.exit_code != 0
    assert _attachment(hosts_path) == [ROUTER]
    assert _recovery_required(hosts_path) is False
    assert "local recovery state could not be restored" in result.output
    assert "do not rely on the current provider selection" in result.output
    assert "Traceback" not in result.output


def test_codex_cleanup_metadata_write_failure_reports_relogin_or_target_retry(
    fleet_dir, monkeypatch
):
    """A stale local Codex selection is never presented as usable OAuth state."""
    hosts_path = _seed_pi(fleet_dir)
    remote_auth_present = True
    revoke_calls = 0
    real_update = configure_mod.update_host

    def revoke(**_kwargs) -> None:
        nonlocal remote_auth_present, revoke_calls
        revoke_calls += 1
        remote_auth_present = False

    update_calls = 0

    def fail_update(*args, **kwargs):
        nonlocal update_calls
        update_calls += 1
        if update_calls == 1:
            return real_update(*args, **kwargs)
        raise OSError("disk full")

    def sync(name: str, **_kwargs) -> CanonicalSyncResult:
        assert name == AGENT
        return CanonicalSyncResult(True, AGENT, "10.0.0.1", (), (), ())

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.revoke_pi_codex", revoke)
    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)
    monkeypatch.setattr(configure_mod, "update_host", fail_update)

    failed = _configure()

    assert failed.exit_code != 0
    assert "metadata update failed after remote Codex OAuth removal" in failed.output
    assert "Local Codex selection now requires native re-login" in failed.output
    assert f"clawctl agent provider login {CODEX} --agent {AGENT}" in failed.output
    assert "retry the target provider configure command" in failed.output
    assert _attachment(hosts_path) == [CODEX]
    assert _recovery_required(hosts_path)
    assert remote_auth_present is False

    # Even after local storage is repaired, same-provider configure remains
    # fail-closed until the native login operation clears the durable marker.
    monkeypatch.setattr(configure_mod, "update_host", real_update)
    same_selection = _configure(CODEX)
    assert same_selection.exit_code != 0
    assert "requires native re-login" in same_selection.output
    assert _attachment(hosts_path) == [CODEX]
    assert _recovery_required(hosts_path)

    # A failed, aborted, or merely clean-exit native login invokes no success
    # callback, so the preceding refusal and durable marker remain fail-closed.
    # This direct mutation models the provider-login callback only after its
    # agent-scoped, secret-free remote auth-presence validation succeeds.
    def successful_login_callback(host: dict) -> dict:
        host["agents"][AGENT].pop("pi_codex_auth_recovery", None)
        return host

    real_update("10.0.0.1", successful_login_callback)
    remote_auth_present = True
    recovered_selection = _configure(CODEX)
    assert recovered_selection.exit_code == 0, recovered_selection.output
    assert _attachment(hosts_path) == [CODEX]
    assert _recovery_required(hosts_path) is False
    assert remote_auth_present is True

    # Retrying the requested target is safe: revoke is idempotent and the
    # durable selection advances only after it returns.
    retried_target = _configure()
    assert retried_target.exit_code == 0, retried_target.output
    assert _attachment(hosts_path) == [ROUTER]
    assert _recovery_required(hosts_path) is False
    assert remote_auth_present is False
    assert revoke_calls == 2

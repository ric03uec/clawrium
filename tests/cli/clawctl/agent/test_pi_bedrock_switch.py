"""Public CLI regressions for Pi AWS SSO Bedrock provider changes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import configure as configure_mod
from clawrium.core.lifecycle_canonical import CanonicalSyncResult

AGENT = "pi-bedrock-switch"
A = "bedrock-a"
B = "bedrock-b"
OPENROUTER = "router-b"


def _provider(name: str, *, profile: str) -> dict[str, str]:
    return {
        "name": name,
        "type": "bedrock",
        "credential_source": "aws-sso",
        "default_model": "anthropic.claude-3-haiku-20240307-v1:0",
        "aws_profile": profile,
        "region": "us-east-1",
        "sso_start_url": "https://example.awsapps.com/start",
        "sso_region": "us-east-1",
        "sso_account_id": "123456789012",
        "sso_role_name": "BedrockRole",
    }


def _openrouter_provider() -> dict[str, str]:
    return {
        "name": OPENROUTER,
        "type": "openrouter",
        "default_model": "openai/gpt-4o",
    }


def _seed_pi(fleet_dir: Path, providers: list[dict[str, str]]) -> Path:
    """Seed the real disk stores consumed by the public configure command."""
    fleet_dir.chmod(0o700)
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"][AGENT] = {
        "type": "pi",
        "agent_name": AGENT,
        "status": "installed",
        "installed_at": "2026-01-01T00:00:00+00:00",
        "providers": [A],
    }
    hosts_path.write_text(json.dumps(hosts))
    (fleet_dir / "providers.json").write_text(json.dumps(providers))
    return hosts_path


def _attachment(hosts_path: Path) -> list[str]:
    return json.loads(hosts_path.read_text())[0]["agents"][AGENT]["providers"]


@dataclass
class _Remote:
    """SSH-bound revocation fake; the configure command remains real."""

    fail_purge: bool = False
    events: list[str] = field(default_factory=list)

    class _Stream:
        def __init__(self, status: int):
            self.channel = self
            self._status = status

        def recv_exit_status(self) -> int:
            return self._status

        def read(self) -> bytes:
            return b""

    class _Client:
        def __init__(self, remote: "_Remote"):
            self.remote = remote

        def exec_command(self, command: str, timeout: int):
            assert timeout == 30
            # The real revoker constructs this descriptor-anchored purge for
            # the Pi account root before deleting any activation files.
            assert f"/home/{AGENT}" in command
            self.remote.events.append("purge-A-cache-under-agent-root")
            stream = _Remote._Stream(1 if self.remote.fail_purge else 0)
            return stream, stream, stream

        def close(self) -> None:
            self.remote.events.append("close-revoke-ssh")


def _mock_remote_boundary(
    monkeypatch, remote: _Remote, hosts_path: Path, *, expected_provider: str = B
) -> None:
    """Replace SSH only; invoke the public CLI and real local disk mutation."""
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._open_ssh",
        lambda _host: _Remote._Client(remote),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: remote.events.append("verify-agent-root-marker"),
    )

    def remove_remote_activation(_client, *, path: str, body, **_kwargs) -> None:
        assert body is None
        remote.events.append(f"revoke-A:{path}")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        remove_remote_activation,
    )

    def sync(name: str, **_kwargs) -> CanonicalSyncResult:
        # This is the remote activation boundary.  Observing disk here proves
        # that configure durably committed B only after the A revoke returned.
        assert name == AGENT
        assert _attachment(hosts_path) == [expected_provider]
        remote.events.append(f"sync:{expected_provider}-after-durable-attachment")
        return CanonicalSyncResult(True, AGENT, "10.0.0.1", (), (), ())

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)


def _record_identity_validation(monkeypatch, events: list[str]) -> None:
    actual = configure_mod._pi_bedrock_sso_identity

    def validate(provider: str):
        events.append(f"validate:{provider}")
        return actual(provider)

    monkeypatch.setattr(configure_mod, "_pi_bedrock_sso_identity", validate)


def _configure(provider: str):
    return CliRunner().invoke(
        app,
        ["agent", "configure", AGENT, "--stage", "providers", "--provider", provider],
    )


def test_sync_rejects_provider_selection_without_mutating_attached_bedrock(
    fleet_dir,
):
    """Sync has no provider-selection option, so it cannot request an A→B switch."""
    hosts_path = _seed_pi(
        fleet_dir, [_provider(A, profile="a"), _provider(B, profile="b")]
    )

    result = CliRunner().invoke(app, ["agent", "sync", AGENT, "--provider", B])

    assert result.exit_code == 2
    assert "No such option: --provider" in result.output
    assert _attachment(hosts_path) == [A]


def test_configure_switches_bedrock_identity_after_root_bound_a_revoke(
    fleet_dir, monkeypatch
):
    """A→B validates both, purges A under its root, then durably activates B."""
    hosts_path = _seed_pi(
        fleet_dir, [_provider(A, profile="a"), _provider(B, profile="b")]
    )
    remote = _Remote()
    _mock_remote_boundary(monkeypatch, remote, hosts_path)
    _record_identity_validation(monkeypatch, remote.events)

    result = _configure(B)

    assert result.exit_code == 0, result.output
    assert _attachment(hosts_path) == [B]
    assert remote.events.index("validate:bedrock-a") < remote.events.index(
        "purge-A-cache-under-agent-root"
    )
    assert remote.events.index("validate:bedrock-b") < remote.events.index(
        "purge-A-cache-under-agent-root"
    )
    assert remote.events.index("purge-A-cache-under-agent-root") < remote.events.index(
        "sync:bedrock-b-after-durable-attachment"
    )
    assert (
        sum(event.endswith("/.pi/agent/clawrium-aws-config") for event in remote.events)
        == 1
    )
    assert (
        sum(
            event.endswith("/.pi/agent/clawrium-aws-credentials")
            for event in remote.events
        )
        == 1
    )


def test_configure_retries_a_revoke_before_committing_b_after_purge_failure(
    fleet_dir, monkeypatch
):
    """A failed root-bound purge retains A and prevents B sync until a retry."""
    hosts_path = _seed_pi(
        fleet_dir, [_provider(A, profile="a"), _provider(B, profile="b")]
    )
    remote = _Remote(fail_purge=True)
    _mock_remote_boundary(monkeypatch, remote, hosts_path)

    failed = _configure(B)

    assert failed.exit_code != 0
    assert _attachment(hosts_path) == [A]
    assert remote.events == [
        "verify-agent-root-marker",
        "purge-A-cache-under-agent-root",
        "close-revoke-ssh",
    ]

    remote.fail_purge = False
    retried = _configure(B)

    assert retried.exit_code == 0, retried.output
    assert _attachment(hosts_path) == [B]
    assert remote.events.count("purge-A-cache-under-agent-root") == 2
    assert remote.events[-1] == "sync:bedrock-b-after-durable-attachment"


def test_configure_bedrock_to_openrouter_revokes_a_before_durable_b_sync(
    fleet_dir, monkeypatch
):
    """A Bedrock→OpenRouter replacement clears A before B reaches disk or SSH."""
    hosts_path = _seed_pi(
        fleet_dir, [_provider(A, profile="a"), _openrouter_provider()]
    )
    remote = _Remote()
    _mock_remote_boundary(monkeypatch, remote, hosts_path, expected_provider=OPENROUTER)

    result = _configure(OPENROUTER)

    assert result.exit_code == 0, result.output
    assert _attachment(hosts_path) == [OPENROUTER]
    assert remote.events.index("purge-A-cache-under-agent-root") < remote.events.index(
        f"sync:{OPENROUTER}-after-durable-attachment"
    )


def test_configure_bedrock_to_openrouter_retries_purge_before_b_sync(
    fleet_dir, monkeypatch
):
    """A failed A purge retains A; a retry purges again before activating B."""
    hosts_path = _seed_pi(
        fleet_dir, [_provider(A, profile="a"), _openrouter_provider()]
    )
    remote = _Remote(fail_purge=True)
    _mock_remote_boundary(monkeypatch, remote, hosts_path, expected_provider=OPENROUTER)

    failed = _configure(OPENROUTER)

    assert failed.exit_code != 0
    assert _attachment(hosts_path) == [A]
    assert not any(event.startswith("sync:") for event in remote.events)

    remote.fail_purge = False
    retried = _configure(OPENROUTER)

    assert retried.exit_code == 0, retried.output
    assert _attachment(hosts_path) == [OPENROUTER]
    assert remote.events.count("purge-A-cache-under-agent-root") == 2
    assert remote.events[-1] == f"sync:{OPENROUTER}-after-durable-attachment"


def test_configure_bedrock_to_openrouter_persistence_failure_is_retryable(
    fleet_dir, monkeypatch
):
    """Post-purge local failure retains A without claiming its remote state remains."""
    hosts_path = _seed_pi(
        fleet_dir, [_provider(A, profile="a"), _openrouter_provider()]
    )
    remote = _Remote()
    _mock_remote_boundary(monkeypatch, remote, hosts_path, expected_provider=OPENROUTER)
    real_update_host = configure_mod.update_host
    calls = 0

    def fail_local_attachment_once(hostname: str, updater):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("disk full")
        return real_update_host(hostname, updater)

    monkeypatch.setattr(configure_mod, "update_host", fail_local_attachment_once)

    failed = _configure(OPENROUTER)

    assert failed.exit_code != 0
    assert _attachment(hosts_path) == [A]
    assert not any(event.startswith("sync:") for event in remote.events)
    assert "metadata update failed after credential cleanup" in failed.output
    assert "retry the provider configure command or run agent sync" in failed.output

    retried = _configure(OPENROUTER)

    assert retried.exit_code == 0, retried.output
    assert _attachment(hosts_path) == [OPENROUTER]
    assert remote.events.count("purge-A-cache-under-agent-root") == 2
    assert remote.events[-1] == f"sync:{OPENROUTER}-after-durable-attachment"


def test_configure_same_bedrock_sso_identity_skips_cache_revoke(fleet_dir, monkeypatch):
    """Changing an alias for the same SSO identity preserves its warm cache."""
    hosts_path = _seed_pi(
        fleet_dir,
        [_provider(A, profile="shared"), _provider(B, profile="shared")],
    )
    remote = _Remote()
    _mock_remote_boundary(monkeypatch, remote, hosts_path)

    result = _configure(B)

    assert result.exit_code == 0, result.output
    assert _attachment(hosts_path) == [B]
    assert remote.events == ["sync:bedrock-b-after-durable-attachment"]

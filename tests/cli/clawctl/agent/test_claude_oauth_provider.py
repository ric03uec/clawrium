"""Claude OAuth provider selection and secret-boundary contracts (#1013)."""

from __future__ import annotations

import hashlib
import json
import secrets
from types import SimpleNamespace

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core import claude_credentials, lifecycle_canonical
from clawrium.core.claude_credentials import (
    ANTHROPIC_API_KEY,
    CLAUDE_CODE_OAUTH_TOKEN,
    ClaudeOAuthSourceError,
    configure_claude_credentials,
)
from clawrium.core.secrets import get_instance_key, get_instance_secrets

runner = CliRunner()


def _add_claude_agent(fleet_dir) -> None:
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    hosts[0]["agents"]["claude-code"] = {
        "type": "claude",
        "agent_name": "claude-code",
        "version": "2.1.100",
        "status": "installed",
        "installed_at": "2026-10-03T00:00:00+00:00",
        "config": {},
    }
    hosts_path.write_text(json.dumps(hosts, indent=2))


def _instance_key() -> str:
    return get_instance_key("10.0.0.1", "claude", "claude-code")


def _create_claude_oauth_provider() -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "local-claude-oauth",
            "--type",
            "claude-oauth",
        ],
    )
    assert result.exit_code == 0, result.output


def test_claude_oauth_provider_is_selected_with_fake_reader_and_available_to_sync(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """Attach calls the local reader, even when an environment token exists."""
    _add_claude_agent(fleet_dir)
    _create_claude_oauth_provider()
    local_token = "oauth-" + secrets.token_urlsafe(24)
    environment_token = "environment-" + secrets.token_urlsafe(24)
    expected_digest = hashlib.sha256(local_token.encode()).hexdigest()
    monkeypatch.setenv(CLAUDE_CODE_OAUTH_TOKEN, environment_token)
    reader_calls: list[str] = []

    def fake_local_reader() -> str:
        reader_calls.append("called")
        return f"  Bearer {local_token}  "

    # Attach reaches the real provider importer, while this fake replaces only
    # its local-reader seam. No test invokes Claude Code or reads a credential
    # from the development machine.
    monkeypatch.setattr(
        claude_credentials, "read_local_claude_oauth_token", fake_local_reader
    )

    # Start in API-key mode to pin that selecting OAuth atomically removes the
    # conflicting credential mode before the existing activation path runs.
    configure_claude_credentials(
        "claude-code", anthropic_api_key="api-" + secrets.token_urlsafe(24)
    )

    attach = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "local-claude-oauth",
            "--agent",
            "claude-code",
        ],
    )

    assert attach.exit_code == 0, attach.output
    assert reader_calls == ["called"]
    assert local_token not in attach.output
    assert environment_token not in attach.output
    entries = get_instance_secrets(_instance_key())
    assert set(entries) == {CLAUDE_CODE_OAUTH_TOKEN}
    assert hashlib.sha256(
        entries[CLAUDE_CODE_OAUTH_TOKEN]["value"].encode()
    ).hexdigest() == (expected_digest)
    assert ANTHROPIC_API_KEY not in entries

    hosts_text = (fleet_dir / "hosts.json").read_text()
    providers_text = (fleet_dir / "providers.json").read_text()
    assert local_token not in hosts_text
    assert environment_token not in hosts_text
    assert local_token not in providers_text
    assert environment_token not in providers_text
    hosts = json.loads(hosts_text)
    assert hosts[0]["agents"]["claude-code"]["providers"] == ["local-claude-oauth"]

    activation: dict[str, str] = {}

    def fake_sync(agent_name: str, **_kwargs):
        key, value = lifecycle_canonical._validate_claude_credential_activation(
            agent_name
        )
        activation["key"] = key
        activation["digest"] = hashlib.sha256(value.encode()).hexdigest()
        return SimpleNamespace(
            success=True, files_written=(), files_unchanged=(), error=None
        )

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", fake_sync
    )
    synced = runner.invoke(app, ["agent", "sync", "claude-code"])

    assert synced.exit_code == 0, synced.output
    assert activation == {
        "key": CLAUDE_CODE_OAUTH_TOKEN,
        "digest": expected_digest,
    }
    assert local_token not in synced.output


def test_claude_oauth_reader_error_is_redacted_and_restores_attachment(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """A reader failure cannot leave a selected provider or reveal its detail."""
    _add_claude_agent(fleet_dir)
    _create_claude_oauth_provider()
    sensitive_detail = "reader-error-" + secrets.token_urlsafe(24)

    def failing_reader() -> str:
        raise ClaudeOAuthSourceError(sensitive_detail)

    monkeypatch.setattr(
        claude_credentials, "read_local_claude_oauth_token", failing_reader
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "local-claude-oauth",
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code != 0
    assert "could not import the local Claude OAuth credential" in result.output
    assert "category=unknown_reader_failure" in result.output
    assert sensitive_detail not in result.output
    hosts_text = (fleet_dir / "hosts.json").read_text()
    providers_text = (fleet_dir / "providers.json").read_text()
    assert sensitive_detail not in hosts_text
    assert sensitive_detail not in providers_text
    hosts = json.loads(hosts_text)
    assert "providers" not in hosts[0]["agents"]["claude-code"]
    assert get_instance_secrets(_instance_key()) == {}


def test_claude_oauth_reader_category_reaches_cli_without_output(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """The E2E can classify an artifact failure without exposing its contents."""
    _add_claude_agent(fleet_dir)
    _create_claude_oauth_provider()

    def unavailable_reader() -> str:
        # The concrete reader never reflects artifact contents through this
        # boundary; a fixed category is the only safe detail.
        raise ClaudeOAuthSourceError("credentials_artifact_unavailable")

    monkeypatch.setattr(
        claude_credentials, "read_local_claude_oauth_token", unavailable_reader
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "local-claude-oauth",
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code != 0
    assert "category=credentials_artifact_unavailable" in result.output
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert "providers" not in hosts[0]["agents"]["claude-code"]
    assert get_instance_secrets(_instance_key()) == {}


def test_claude_oauth_cancellation_restores_new_attachment(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """Cancelling browser authorization cannot leave OAuth selected without a token."""
    _add_claude_agent(fleet_dir)
    _create_claude_oauth_provider()

    def interrupted_reader() -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        claude_credentials, "read_local_claude_oauth_token", interrupted_reader
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "local-claude-oauth",
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code != 0
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert "providers" not in hosts[0]["agents"]["claude-code"]
    assert get_instance_secrets(_instance_key()) == {}


def test_claude_oauth_failure_does_not_overwrite_concurrent_attachment(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """Rollback is conditional when a long-running reader loses a metadata race."""
    _add_claude_agent(fleet_dir)
    _create_claude_oauth_provider()

    def concurrent_then_fail() -> str:
        hosts_path = fleet_dir / "hosts.json"
        hosts = json.loads(hosts_path.read_text())
        hosts[0]["agents"]["claude-code"]["providers"] = ["concurrent-provider"]
        hosts_path.write_text(json.dumps(hosts, indent=2))
        raise ClaudeOAuthSourceError("reader failure")

    monkeypatch.setattr(
        claude_credentials, "read_local_claude_oauth_token", concurrent_then_fail
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "local-claude-oauth",
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code != 0
    assert "rollback could not be confirmed" in result.output
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["claude-code"]["providers"] == ["concurrent-provider"]
    assert get_instance_secrets(_instance_key()) == {}


def test_claude_rejects_non_oauth_provider_without_invoking_reader(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    _add_claude_agent(fleet_dir)
    api_value = "api-" + secrets.token_urlsafe(24)
    created = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "ordinary-anthropic",
            "--type",
            "anthropic",
            "--api-key",
            api_value,
        ],
    )
    assert created.exit_code == 0, created.output

    def unexpected_reader() -> str:
        raise AssertionError(
            "a non-OAuth provider must fail before local credential import"
        )

    monkeypatch.setattr(
        claude_credentials, "read_local_claude_oauth_token", unexpected_reader
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "ordinary-anthropic",
            "--agent",
            "claude-code",
        ],
    )

    assert result.exit_code != 0
    assert "require a claude-oauth provider" in result.output
    assert api_value not in result.output
    assert get_instance_secrets(_instance_key()) == {}

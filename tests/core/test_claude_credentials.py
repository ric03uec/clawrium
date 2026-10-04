"""Local Claude Code credential-mode contracts (#999)."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

import pytest

from clawrium.core import claude_credentials, secrets as secrets_module
from clawrium.core.claude_credentials import (
    ANTHROPIC_API_KEY,
    CLAUDE_CODE_OAUTH_TOKEN,
    ClaudeCredentialError,
    ClaudeCredentialMode,
    ClaudeCredentialState,
    ClaudeOAuthSourceError,
    configure_claude_credentials,
    get_active_claude_credential,
    get_claude_credential_state,
    import_claude_oauth_from_environment,
    read_local_claude_oauth_token,
)
from clawrium.core.providers.storage import (
    get_provider_api_key,
    set_provider_api_key,
)
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
)


def _seed_claude_agent(config_dir: Path, *, agent_type: str = "claude") -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    hosts_path = config_dir / "hosts.json"
    hosts_path.write_text(
        json.dumps(
            [
                {
                    "hostname": "claude-host",
                    "key_id": "claude-host-key",
                    "agents": {
                        "claude-code": {
                            "type": agent_type,
                            "agent_name": "claude-code",
                            "status": "installed",
                            "installed_at": "2026-10-03T00:00:00+00:00",
                            "config": {"model": "claude-sonnet-4-5"},
                        }
                    },
                }
            ],
            indent=2,
        )
    )
    return hosts_path


def _claude_instance_key() -> str:
    return get_instance_key("claude-host-key", "claude", "claude-code")


def test_oauth_environment_import_normalizes_bearer_and_keeps_hosts_secret_free(
    isolated_config: Path,
):
    hosts_path = _seed_claude_agent(isolated_config)
    before_hosts = hosts_path.read_text()

    state = import_claude_oauth_from_environment(
        "claude-code",
        environment={CLAUDE_CODE_OAUTH_TOKEN: "  Bearer oauth-test-token  "},
    )

    assert state == ClaudeCredentialState(mode=ClaudeCredentialMode.OAUTH)
    entries = get_instance_secrets(_claude_instance_key())
    assert set(entries) == {CLAUDE_CODE_OAUTH_TOKEN}
    assert entries[CLAUDE_CODE_OAUTH_TOKEN]["value"] == "oauth-test-token"
    assert "oauth-test-token" not in repr(state)
    assert hosts_path.read_text() == before_hosts


def test_api_key_switch_replaces_oauth_without_provider_or_settings_state(
    isolated_config: Path,
):
    hosts_path = _seed_claude_agent(isolated_config)
    before_hosts = hosts_path.read_text()
    import_claude_oauth_from_environment(
        "claude-code", environment={CLAUDE_CODE_OAUTH_TOKEN: "oauth-test-token"}
    )

    state = configure_claude_credentials(
        "claude-code", anthropic_api_key="anthropic-api-test-key"
    )

    assert state == ClaudeCredentialState(mode=ClaudeCredentialMode.API_KEY)
    entries = get_instance_secrets(_claude_instance_key())
    assert set(entries) == {ANTHROPIC_API_KEY}
    assert entries[ANTHROPIC_API_KEY]["value"] == "anthropic-api-test-key"
    assert CLAUDE_CODE_OAUTH_TOKEN not in entries
    assert hosts_path.read_text() == before_hosts
    assert not (isolated_config / "providers.json").exists()


@pytest.mark.parametrize(
    ("credential_kwargs", "expected"),
    [
        (
            {"oauth_token": "oauth-active-test-token"},
            (CLAUDE_CODE_OAUTH_TOKEN, "oauth-active-test-token"),
        ),
        (
            {"anthropic_api_key": "api-active-test-key"},
            (ANTHROPIC_API_KEY, "api-active-test-key"),
        ),
    ],
)
def test_get_active_credential_returns_exactly_the_selected_mode(
    isolated_config: Path,
    credential_kwargs: dict[str, str],
    expected: tuple[str, str],
):
    _seed_claude_agent(isolated_config)
    configure_claude_credentials("claude-code", **credential_kwargs)

    assert get_active_claude_credential("claude-code") == expected


def test_get_active_credential_rejects_absent_or_malformed_secret_without_leaking(
    isolated_config: Path,
):
    _seed_claude_agent(isolated_config)
    with pytest.raises(ClaudeCredentialError) as absent:
        get_active_claude_credential("claude-code")
    assert "credential is not configured" in str(absent.value)

    malformed = "api malformed sentinel"
    set_instance_secret(_claude_instance_key(), ANTHROPIC_API_KEY, malformed)
    with pytest.raises(ClaudeCredentialError) as error:
        get_active_claude_credential("claude-code")
    assert "encrypted secrets store is invalid" in str(error.value)
    assert malformed not in str(error.value)


def test_get_active_credential_rejects_noncanonical_oauth_store_value(
    isolated_config: Path,
):
    _seed_claude_agent(isolated_config)
    stored_value = "Bearer oauth-noncanonical-test-token"
    set_instance_secret(_claude_instance_key(), CLAUDE_CODE_OAUTH_TOKEN, stored_value)

    with pytest.raises(ClaudeCredentialError) as error:
        get_active_claude_credential("claude-code")

    assert "encrypted secrets store is invalid" in str(error.value)
    assert stored_value not in str(error.value)


def test_get_active_credential_rejects_missing_or_invalid_store_entry(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    _seed_claude_agent(isolated_config)
    instance_key = _claude_instance_key()
    valid = {ANTHROPIC_API_KEY: {"value": "api-valid-test-key"}}

    for invalid in ({}, {ANTHROPIC_API_KEY: "not-a-mapping"}):
        calls = iter((valid, invalid))
        monkeypatch.setattr(
            claude_credentials, "get_instance_secrets", lambda _: next(calls)
        )
        with pytest.raises(
            ClaudeCredentialError, match="encrypted secrets store is invalid"
        ):
            get_active_claude_credential("claude-code")

    # Keep the local variable used above intentional: the public helper must
    # resolve this exact instance key, never accept an arbitrary secret scope.
    assert instance_key == _claude_instance_key()


def test_credential_inputs_and_tampered_dual_modes_are_rejected(
    isolated_config: Path,
):
    _seed_claude_agent(isolated_config)

    with pytest.raises(ClaudeCredentialError, match="exactly one"):
        configure_claude_credentials("claude-code")
    with pytest.raises(ClaudeCredentialError, match="exactly one"):
        configure_claude_credentials(
            "claude-code",
            oauth_token="oauth-test-token",
            anthropic_api_key="anthropic-api-test-key",
        )
    assert get_claude_credential_state("claude-code").mode is None

    instance_key = _claude_instance_key()
    set_instance_secret(instance_key, CLAUDE_CODE_OAUTH_TOKEN, "oauth-test-token")
    set_instance_secret(instance_key, ANTHROPIC_API_KEY, "anthropic-api-test-key")

    with pytest.raises(
        ClaudeCredentialError, match="conflicting Claude credential modes"
    ):
        get_claude_credential_state("claude-code")
    with pytest.raises(
        ClaudeCredentialError, match="conflicting Claude credential modes"
    ):
        configure_claude_credentials(
            "claude-code", anthropic_api_key="replacement-api-test-key"
        )


@pytest.mark.parametrize(
    ("credential_kwargs", "sensitive_value"),
    [
        ({"oauth_token": ""}, ""),
        ({"oauth_token": "Bearer "}, "Bearer "),
        (
            {"oauth_token": "oauth sentinel with whitespace"},
            "oauth sentinel with whitespace",
        ),
        ({"oauth_token": "oauth-sentinel\x00suffix"}, "oauth-sentinel\x00suffix"),
        ({"oauth_token": 123}, "123"),
        (
            {"anthropic_api_key": "api sentinel with whitespace"},
            "api sentinel with whitespace",
        ),
        ({"anthropic_api_key": "api-sentinel\x00suffix"}, "api-sentinel\x00suffix"),
        ({"anthropic_api_key": 456}, "456"),
    ],
)
def test_invalid_credentials_never_replace_a_valid_mode_or_appear_in_errors(
    isolated_config: Path, credential_kwargs: dict[str, object], sensitive_value: str
):
    _seed_claude_agent(isolated_config)
    configure_claude_credentials(
        "claude-code", anthropic_api_key="initial-api-test-key"
    )

    with pytest.raises(ClaudeCredentialError) as error:
        configure_claude_credentials("claude-code", **credential_kwargs)

    if sensitive_value:
        assert sensitive_value not in str(error.value)
        assert sensitive_value not in repr(error.value)
    entries = get_instance_secrets(_claude_instance_key())
    assert set(entries) == {ANTHROPIC_API_KEY}
    assert entries[ANTHROPIC_API_KEY]["value"] == "initial-api-test-key"


def test_oauth_environment_rejects_non_string_value_without_writing(
    isolated_config: Path,
):
    _seed_claude_agent(isolated_config)
    sensitive_value = "789"

    with pytest.raises(ClaudeCredentialError) as error:
        import_claude_oauth_from_environment(
            "claude-code",
            environment={CLAUDE_CODE_OAUTH_TOKEN: 789},  # type: ignore[dict-item]
        )

    assert sensitive_value not in str(error.value)
    assert sensitive_value not in repr(error.value)
    assert get_claude_credential_state("claude-code").mode is None


def test_oauth_import_refuses_unknown_local_sources_without_scraping(
    isolated_config: Path,
):
    _seed_claude_agent(isolated_config)

    with pytest.raises(ClaudeOAuthSourceError) as error:
        import_claude_oauth_from_environment("claude-code", environment={})

    assert error.value.category == "supplied_environment_token_absent"
    assert "category=supplied_environment_token_absent" in str(error.value)
    assert get_claude_credential_state("claude-code").mode is None


def test_failed_mode_switch_preserves_prior_secret_until_atomic_replacement_succeeds(
    isolated_config: Path, monkeypatch: pytest.MonkeyPatch
):
    _seed_claude_agent(isolated_config)
    configure_claude_credentials(
        "claude-code", anthropic_api_key="anthropic-api-test-key"
    )
    before = get_instance_secrets(_claude_instance_key())

    def fail_save(*_args, **_kwargs):
        raise OSError("simulated atomic write failure")

    monkeypatch.setattr(secrets_module, "_save_secrets_atomic", fail_save)
    with pytest.raises(OSError, match="simulated atomic write failure"):
        configure_claude_credentials("claude-code", oauth_token="oauth-test-token")

    after = get_instance_secrets(_claude_instance_key())
    assert set(after) == {ANTHROPIC_API_KEY}
    assert after[ANTHROPIC_API_KEY] == before[ANTHROPIC_API_KEY]
    assert CLAUDE_CODE_OAUTH_TOKEN not in after


def test_claude_per_instance_credentials_do_not_mutate_provider_credentials(
    isolated_config: Path,
):
    _seed_claude_agent(isolated_config)
    set_provider_api_key("shared-anthropic", "provider-api-test-key")

    configure_claude_credentials("claude-code", anthropic_api_key="agent-api-test-key")

    assert get_provider_api_key("shared-anthropic") == "provider-api-test-key"
    agent_entries = get_instance_secrets(_claude_instance_key())
    assert set(agent_entries) == {ANTHROPIC_API_KEY}
    assert agent_entries[ANTHROPIC_API_KEY]["value"] == "agent-api-test-key"


def _write_local_credentials_artifact(path: Path, access_token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": access_token}}))
    path.chmod(0o600)


def test_credentials_artifact_reader_uses_exact_access_token_not_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    artifact_token = "oauth-" + secrets.token_urlsafe(24)
    artifact = tmp_path / ".claude" / ".credentials.json"
    _write_local_credentials_artifact(artifact, artifact_token)
    monkeypatch.setattr(claude_credentials.sys, "platform", "linux")
    monkeypatch.setattr(claude_credentials, "_CLAUDE_CREDENTIALS_PATH", artifact)
    monkeypatch.setenv(
        CLAUDE_CODE_OAUTH_TOKEN, "environment-" + secrets.token_urlsafe(24)
    )
    monkeypatch.setenv(ANTHROPIC_API_KEY, "api-" + secrets.token_urlsafe(24))

    value = read_local_claude_oauth_token()

    assert (
        hashlib.sha256(value.encode()).hexdigest()
        == hashlib.sha256(artifact_token.encode()).hexdigest()
    )


def test_credentials_artifact_reader_rejects_insecure_file_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sensitive_token = "oauth-" + secrets.token_urlsafe(24)
    artifact = tmp_path / ".claude" / ".credentials.json"
    _write_local_credentials_artifact(artifact, sensitive_token)
    artifact.chmod(0o644)
    monkeypatch.setattr(claude_credentials.sys, "platform", "linux")
    monkeypatch.setattr(claude_credentials, "_CLAUDE_CREDENTIALS_PATH", artifact)

    with pytest.raises(ClaudeOAuthSourceError) as error:
        read_local_claude_oauth_token()

    assert error.value.category == "credentials_artifact_insecure"
    assert sensitive_token not in str(error.value)


def test_credentials_artifact_reader_rejects_missing_access_token_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sensitive_value = "oauth-" + secrets.token_urlsafe(24)
    artifact = tmp_path / ".claude" / ".credentials.json"
    _write_local_credentials_artifact(artifact, sensitive_value)
    artifact.write_text(
        json.dumps({"claudeAiOauth": {"refreshToken": sensitive_value}})
    )
    artifact.chmod(0o600)
    monkeypatch.setattr(claude_credentials.sys, "platform", "linux")
    monkeypatch.setattr(claude_credentials, "_CLAUDE_CREDENTIALS_PATH", artifact)

    with pytest.raises(ClaudeOAuthSourceError) as error:
        read_local_claude_oauth_token()

    assert error.value.category == "credentials_access_token_missing"
    assert sensitive_value not in str(error.value)


def test_credentials_artifact_reader_rejects_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    artifact = tmp_path / ".claude" / ".credentials.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"x" * (claude_credentials._CLAUDE_CREDENTIALS_MAX_BYTES + 1))
    artifact.chmod(0o600)
    monkeypatch.setattr(claude_credentials.sys, "platform", "linux")
    monkeypatch.setattr(claude_credentials, "_CLAUDE_CREDENTIALS_PATH", artifact)

    with pytest.raises(ClaudeOAuthSourceError) as error:
        read_local_claude_oauth_token()

    assert error.value.category == "credentials_artifact_too_large"


def test_credentials_artifact_reader_fails_closed_on_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(claude_credentials.sys, "platform", "darwin")
    monkeypatch.setattr(
        claude_credentials.os,
        "open",
        lambda *_args, **_kwargs: pytest.fail(
            "unsupported reader must not open a credential artifact"
        ),
    )

    with pytest.raises(ClaudeOAuthSourceError) as error:
        read_local_claude_oauth_token()

    assert error.value.category == "unsupported_controller_platform"
    assert "category=unsupported_controller_platform" in str(error.value)


def test_non_claude_agent_cannot_use_claude_credential_modes(isolated_config: Path):
    _seed_claude_agent(isolated_config, agent_type="openclaw")

    with pytest.raises(ClaudeCredentialError, match="not a Claude Code agent"):
        configure_claude_credentials(
            "claude-code", anthropic_api_key="anthropic-api-test-key"
        )

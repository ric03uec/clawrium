"""Pi #1038 OpenRouter mapping and finite chat contracts."""

import asyncio
import uuid

import pytest

from clawrium.core.chat_pi import PiChatBackend
from clawrium.core.pi import (
    PI_AWS_CONFIG_PATH,
    PiProvisioningError,
    PiProviderSelection,
    pi_chat_argv,
    render_bedrock_sso_config,
    render_bedrock_sso_environment,
    validate_bedrock_sso_provider,
    validate_pi_provider,
    render_openrouter_environment,
    validate_openrouter_provider,
)


def test_pi_accepts_only_unprefixed_openrouter_model_ids():
    assert (
        validate_openrouter_provider(
            {"type": "openrouter", "default_model": "moonshotai/kimi-k2.6"}
        )
        == "moonshotai/kimi-k2.6"
    )
    with pytest.raises(PiProvisioningError, match="only an OpenRouter"):
        validate_openrouter_provider({"type": "openai", "default_model": "gpt-4o"})
    with pytest.raises(PiProvisioningError, match="must not include"):
        validate_openrouter_provider(
            {"type": "openrouter", "default_model": "openrouter/openai/gpt-4o"}
        )
    with pytest.raises(PiProvisioningError, match="supported OpenRouter"):
        validate_openrouter_provider(
            {"type": "openrouter", "default_model": "bad model"}
        )


def test_pi_codex_selection_accepts_only_pinned_catalog_models():
    assert validate_pi_provider(
        {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"}
    ) == PiProviderSelection("openai-codex", "gpt-5.1-codex-mini")
    with pytest.raises(PiProvisioningError, match="supported by pinned Pi"):
        validate_pi_provider({"type": "openai-codex", "default_model": "unknown"})


def test_pi_bedrock_sso_selection_uses_only_profile_metadata():
    provider = {
        "type": "bedrock",
        "credential_source": "aws-sso",
        "default_model": "anthropic.claude-3-haiku-20240307-v1:0",
        "aws_profile": "pi-bedrock",
        "region": "us-east-1",
        "sso_start_url": "https://company.awsapps.com/start",
        "sso_region": "us-east-1",
        "sso_account_id": "123456789012",
        "sso_role_name": "BedrockPiRole",
    }
    assert validate_bedrock_sso_provider(provider) == provider["default_model"]
    assert validate_pi_provider(provider) == PiProviderSelection(
        "amazon-bedrock", provider["default_model"]
    )
    assert render_bedrock_sso_environment("pi-bedrock", "us-east-1") == (
        "AWS_PROFILE=pi-bedrock\nAWS_REGION=us-east-1\n"
        f"AWS_CONFIG_FILE=$HOME/{PI_AWS_CONFIG_PATH}\n"
    )
    config = render_bedrock_sso_config(provider)
    assert "sso_start_url = https://company.awsapps.com/start" in config
    assert "aws_access_key" not in config.lower()
    assert "secret" not in config.lower()
    with pytest.raises(PiProvisioningError, match="static AWS keys"):
        validate_bedrock_sso_provider({"type": "bedrock", "default_model": "model"})


def test_pi_bedrock_chat_argv_has_fixed_provider():
    session = "12345678-1234-1234-1234-123456789abc"
    argv = pi_chat_argv(
        "anthropic.claude-3-haiku-20240307-v1:0",
        session,
        resume=False,
        provider="amazon-bedrock",
    )
    assert argv[:4] == [
        "--provider",
        "amazon-bedrock",
        "--model",
        "anthropic.claude-3-haiku-20240307-v1:0",
    ]


def test_pi_environment_is_secret_only_and_rejects_empty_key():
    body = render_openrouter_environment("sk-secret;$(not-executed)")
    assert body == "OPENROUTER_API_KEY=sk-secret;$(not-executed)\n"
    with pytest.raises(PiProvisioningError, match="control characters"):
        render_openrouter_environment("key\nnext")


def test_pi_chat_argv_has_fixed_provider_and_session_resume():
    session = "12345678-1234-1234-1234-123456789abc"
    first = pi_chat_argv("moonshotai/kimi-k2.6", session, resume=False)
    second = pi_chat_argv("moonshotai/kimi-k2.6", session, resume=True)
    assert first[:6] == [
        "--provider",
        "openrouter",
        "--model",
        "moonshotai/kimi-k2.6",
        "--print",
        "--no-tools",
    ]
    assert "--no-mcp" not in first
    assert first[-2:] == ["--session-dir", f".pi/agent/clawrium-sessions/{session}"]
    assert second[-1:] == ["--continue"]


def test_pi_codex_chat_argv_never_uses_openai_api_key_mode():
    session = "12345678-1234-1234-1234-123456789abc"
    argv = pi_chat_argv(
        "gpt-5.1-codex-mini", session, resume=False, provider="openai-codex"
    )
    assert argv[:4] == ["--provider", "openai-codex", "--model", "gpt-5.1-codex-mini"]
    assert "--api-key" not in argv and "OPENAI_API_KEY" not in " ".join(argv)


def test_pi_chat_backend_continues_then_resets_without_exposing_credential():
    calls = []
    ids = iter(
        [
            uuid.UUID("12345678-1234-1234-1234-123456789abc"),
            uuid.UUID("87654321-1234-1234-1234-123456789abc"),
        ]
    )

    def runner(host, user, argv, prompt, timeout, cancelled, codex_recovery):
        calls.append((argv, prompt))
        return "answer", "", 0

    backend = PiChatBackend(
        "wolf-i",
        "pi-test",
        "moonshotai/kimi-k2.6",
        command_runner=runner,
        session_id_factory=lambda: next(ids),
    )

    async def run():
        await backend.connect()
        assert await backend.send_message("one", "main") == "answer"
        assert await backend.send_message("two", "main") == "answer"
        backend.clear_history()
        assert await backend.send_message("three", "main") == "answer"

    asyncio.run(run())
    assert calls[0][0][-2] == "--session-dir"
    assert calls[1][0][-1] == "--continue"
    assert calls[2][0][-2] == "--session-dir"
    assert all("OPENROUTER_API_KEY" not in str(call) for call in calls)

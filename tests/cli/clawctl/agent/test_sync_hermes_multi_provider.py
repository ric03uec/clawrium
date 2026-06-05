"""Issue #501 — sync_agent for hermes builds `config.providers` from
multi-provider attachments and still populates `config.provider` from
the primary for back-compat with downstream readers.

Mirrors the structure of test_sync_materializes_provider.py but
targets the hermes-only branch added in Phase 1.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from clawrium.core.lifecycle import LifecycleError, sync_agent


def _hermes_host(*, attachments: list, state: str = "ready") -> dict:
    return {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {
            "test-hermes": {
                "type": "hermes",
                "onboarding": {"state": state},
                "config": {"gateway": {"port": 45000}},
                "providers": attachments,
            }
        },
    }


def _provider_record(name: str, ptype: str = "anthropic") -> dict:
    return {
        "name": name,
        "type": ptype,
        "endpoint": f"https://api.{ptype}.example",
        "default_model": f"{ptype}-default-model",
    }


def test_hermes_multi_attachment_builds_providers_list_and_primary_overlay():
    """Hermes with primary + auxiliary attachments: bridge materializes
    `config.providers` (one overlay per attachment with role) and
    `config.provider` (the primary overlay, role-stripped) so
    Phase-1 readers keep working unchanged."""
    host = _hermes_host(
        attachments=[
            {"name": "anth", "role": "primary", "model": "claude-opus"},
            {"name": "dgx", "role": "compression", "model": "qwen-coder"},
        ]
    )

    by_name = {
        "anth": _provider_record("anth", "anthropic"),
        "dgx": _provider_record("dgx", "ollama"),
    }

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            side_effect=lambda n: by_name.get(n),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    cfg = captured["config_data"]

    # config.provider mirrors primary, with no `role` field leaked.
    primary = cfg["provider"]
    assert primary["name"] == "anth"
    assert primary["type"] == "anthropic"
    assert "role" not in primary

    # config.providers carries both attachments, each with role + model.
    providers = cfg["providers"]
    assert isinstance(providers, list) and len(providers) == 2

    primary_entry = next(p for p in providers if p["role"] == "primary")
    aux_entry = next(p for p in providers if p["role"] == "compression")
    assert primary_entry["name"] == "anth"
    assert primary_entry["model"] == "claude-opus"
    assert aux_entry["name"] == "dgx"
    assert aux_entry["type"] == "ollama"
    assert aux_entry["model"] == "qwen-coder"


def test_hermes_legacy_list_of_strings_migrates_to_primary():
    """A hermes agent record predating #501 stores providers as a
    list of strings. The bridge must migrate first-string → primary
    and emit a single-entry config.providers list."""
    host = _hermes_host(attachments=["anth"])

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_provider_record("anth", "anthropic"),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    providers = captured["config_data"]["providers"]
    assert len(providers) == 1
    assert providers[0]["name"] == "anth"
    assert providers[0]["role"] == "primary"


def test_hermes_primary_model_override_lands_in_default_model():
    """ATX iter-3 B1 (#613): when the primary attachment carries an
    explicit `--model` override, the rendered `config.provider.default_model`
    must reflect the override so the legacy hermes-config.yaml.j2 template
    (which reads default_model, not model) renders the operator's intent.
    """
    host = _hermes_host(
        attachments=[{"name": "anth", "role": "primary", "model": "claude-opus-4-5"}]
    )

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_provider_record("anth", "anthropic"),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    cfg = captured["config_data"]
    assert cfg["provider"]["default_model"] == "claude-opus-4-5"


def test_hermes_primary_no_model_override_keeps_registry_default():
    """ATX iter-3 B1 inverse (#613): primary attachment with no model
    override falls back to the registry's `default_model`. Pins the
    no-op-on-no-override behavior of the W2 fix guard."""
    host = _hermes_host(
        attachments=[{"name": "anth", "role": "primary", "model": ""}]
    )

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_provider_record("anth", "anthropic"),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    cfg = captured["config_data"]
    assert cfg["provider"]["default_model"] == "anthropic-default-model"


def test_hermes_attachment_model_falls_back_to_provider_default():
    """When the attachment has no `model` override, the rendered
    overlay carries the provider's `default_model`."""
    host = _hermes_host(
        attachments=[{"name": "anth", "role": "primary", "model": ""}]
    )

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_provider_record("anth", "anthropic"),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    providers = captured["config_data"]["providers"]
    assert providers[0]["model"] == "anthropic-default-model"


def test_hermes_invalid_attachment_state_raises_lifecycle_error():
    """Hand-edited hosts.json with two primaries must fail loudly with
    a LifecycleError pointing at the attach surface for remediation."""
    host = _hermes_host(
        attachments=[
            {"name": "anth", "role": "primary", "model": ""},
            {"name": "other", "role": "primary", "model": ""},
        ]
    )

    with patch("clawrium.core.lifecycle.get_host", return_value=host):
        with pytest.raises(LifecycleError) as exc_info:
            sync_agent("192.168.1.100", "hermes")

    msg = str(exc_info.value)
    assert "invalid provider attachments" in msg
    assert "exactly one primary" in msg
    assert "clawctl agent provider get" in msg


def test_hermes_duplicate_auxiliary_slot_rejected():
    host = _hermes_host(
        attachments=[
            {"name": "anth", "role": "primary", "model": ""},
            {"name": "a", "role": "compression", "model": ""},
            {"name": "b", "role": "compression", "model": ""},
        ]
    )

    with patch("clawrium.core.lifecycle.get_host", return_value=host):
        with pytest.raises(LifecycleError) as exc_info:
            sync_agent("192.168.1.100", "hermes")

    assert "already filled" in str(exc_info.value)

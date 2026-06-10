"""Targeted tests for the providers API route's accelerator_vendor wiring."""

import asyncio

from clawrium.gui.routes import providers as providers_mod
from clawrium.gui.routes.providers import (
    _resolve_accelerator_vendor,
    DEFAULT_ACCELERATOR_VENDOR,
    LOCAL_INFERENCE_TYPES,
    ProviderCreate,
    ProviderUpdate,
    create_provider,
    update_provider_endpoint,
)


# ─── _resolve_accelerator_vendor ─────────────────────────────────────


def test_resolve_returns_stored_nvidia():
    assert (
        _resolve_accelerator_vendor(
            {"name": "p", "type": "ollama", "accelerator_vendor": "nvidia"}
        )
        == "nvidia"
    )


def test_resolve_returns_stored_amd():
    assert (
        _resolve_accelerator_vendor(
            {"name": "p", "type": "ollama", "accelerator_vendor": "amd"}
        )
        == "amd"
    )


def test_resolve_defaults_ollama_to_nvidia():
    assert _resolve_accelerator_vendor({"name": "p", "type": "ollama"}) == "nvidia"


def test_resolve_ignores_unexpected_stored_value():
    """Garbage in providers.json must not leak through to the API response."""
    assert (
        _resolve_accelerator_vendor(
            {"name": "p", "type": "ollama", "accelerator_vendor": "intel"}
        )
        == DEFAULT_ACCELERATOR_VENDOR
    )


def test_resolve_returns_none_for_non_local_providers():
    for t in ("openai", "anthropic", "bedrock", "openrouter"):
        assert _resolve_accelerator_vendor({"name": "p", "type": t}) is None


def test_local_inference_types_includes_ollama():
    assert "ollama" in LOCAL_INFERENCE_TYPES


# ─── create_provider plumbs accelerator_vendor into providers.json ──


def _capture_add_provider(monkeypatch):
    """Patch add_provider to record the dict it was called with."""
    captured: dict = {}

    def fake_add(provider: dict) -> None:
        captured["provider"] = provider

    monkeypatch.setattr(providers_mod, "add_provider", fake_add)
    return captured


def _patch_secret_writes(monkeypatch):
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)


def test_create_ollama_provider_defaults_accelerator_to_nvidia(monkeypatch):
    captured = _capture_add_provider(monkeypatch)
    _patch_secret_writes(monkeypatch)

    body = ProviderCreate(
        name="local-llm",
        type="ollama",
        endpoint="http://10.0.0.5:11434",
    )
    asyncio.run(create_provider(body))

    assert captured["provider"]["accelerator_vendor"] == "nvidia"
    assert captured["provider"]["type"] == "ollama"
    assert captured["provider"]["name"] == "local-llm"


def test_create_ollama_provider_persists_explicit_amd(monkeypatch):
    captured = _capture_add_provider(monkeypatch)
    _patch_secret_writes(monkeypatch)

    body = ProviderCreate(
        name="local-llm",
        type="ollama",
        endpoint="http://10.0.0.5:11434",
        accelerator_vendor="amd",
    )
    asyncio.run(create_provider(body))

    assert captured["provider"]["accelerator_vendor"] == "amd"


def test_create_non_ollama_provider_does_not_persist_accelerator(monkeypatch):
    captured = _capture_add_provider(monkeypatch)
    _patch_secret_writes(monkeypatch)

    body = ProviderCreate(
        name="cloud-anthropic",
        type="anthropic",
        api_key="sk-test",
        accelerator_vendor="amd",  # should be silently ignored
    )
    asyncio.run(create_provider(body))

    assert "accelerator_vendor" not in captured["provider"]


# ─── update_provider_endpoint also threads accelerator_vendor ────────


def test_update_ollama_provider_writes_accelerator_vendor(monkeypatch):
    existing = {
        "name": "local-llm",
        "type": "ollama",
        "endpoint": "http://10.0.0.5:11434",
        "accelerator_vendor": "nvidia",
    }
    captured: dict = {}

    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)

    def fake_update(name: str, updater):
        captured["name"] = name
        captured["result"] = updater(existing)

    monkeypatch.setattr(providers_mod, "update_provider", fake_update)

    body = ProviderUpdate(accelerator_vendor="amd")
    asyncio.run(update_provider_endpoint("local-llm", body))

    assert captured["name"] == "local-llm"
    assert captured["result"]["accelerator_vendor"] == "amd"
    # Other fields must survive the merge.
    assert captured["result"]["endpoint"] == "http://10.0.0.5:11434"


def test_update_non_ollama_provider_ignores_accelerator_vendor(monkeypatch):
    existing = {"name": "cloud", "type": "openai"}
    captured: dict = {}

    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)

    def fake_update(name: str, updater):
        captured["result"] = updater(existing)

    monkeypatch.setattr(providers_mod, "update_provider", fake_update)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)

    body = ProviderUpdate(accelerator_vendor="amd", default_model="gpt-4o")
    asyncio.run(update_provider_endpoint("cloud", body))

    # Only default_model gets applied; accelerator_vendor is dropped because
    # it is meaningless for cloud providers.
    assert captured["result"].get("default_model") == "gpt-4o"
    assert "accelerator_vendor" not in captured["result"]


# ─── B4: SSRF guard on Ollama endpoints (POST + PUT) ──────────────────

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def test_create_ollama_rejects_cloud_metadata_endpoint(monkeypatch):
    """POST must call validate_ollama_url() and reject 169.254.x.x."""
    _capture_add_provider(monkeypatch)
    _patch_secret_writes(monkeypatch)

    body = ProviderCreate(
        name="evil",
        type="ollama",
        endpoint="http://169.254.169.254/latest/meta-data/",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400
    assert "metadata" in str(exc_info.value.detail).lower()


def test_create_ollama_rejects_non_http_scheme(monkeypatch):
    """POST must reject file:// and other non-http(s) schemes."""
    _capture_add_provider(monkeypatch)
    _patch_secret_writes(monkeypatch)

    body = ProviderCreate(
        name="evil",
        type="ollama",
        endpoint="file:///etc/passwd",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


def test_create_ollama_accepts_private_lan_endpoint(monkeypatch):
    """Private/loopback IPs are allowed for self-hosted Ollama servers."""
    captured = _capture_add_provider(monkeypatch)
    _patch_secret_writes(monkeypatch)

    body = ProviderCreate(
        name="local",
        type="ollama",
        endpoint="http://192.168.1.10:11434",
    )
    asyncio.run(create_provider(body))
    assert captured["provider"]["endpoint"].startswith("http://192.168.")


def test_update_ollama_rejects_cloud_metadata_endpoint(monkeypatch):
    """PUT on an ollama provider must reject 169.254.x.x."""
    existing = {"name": "local", "type": "ollama"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)

    body = ProviderUpdate(endpoint="http://169.254.169.254/")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("local", body))
    assert exc_info.value.status_code == 400


def test_update_cloud_provider_skips_ollama_validation(monkeypatch):
    """Cloud-provider endpoint overrides bypass validate_ollama_url()."""
    existing = {"name": "cloud", "type": "openai"}
    captured: dict = {}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)

    def fake_update(name: str, updater):
        captured["result"] = updater(existing)

    monkeypatch.setattr(providers_mod, "update_provider", fake_update)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)

    # 169.254.x.x would be rejected for ollama, but is accepted (today)
    # for cloud providers — broader cloud-endpoint validation is tracked
    # as a follow-up. Test pins current behavior so a future tightening
    # is explicit.
    body = ProviderUpdate(endpoint="http://169.254.169.254/")
    asyncio.run(update_provider_endpoint("cloud", body))
    assert captured["result"]["endpoint"] == "http://169.254.169.254/"


# ─── provider_types endpoint ────────────────────────────────────────


def test_provider_types_returns_rich_model_metadata():
    """`/types` returns full ModelInfo objects for cloud providers."""
    result = asyncio.run(providers_mod.provider_types())
    types = result["types"]

    # All seven provider types are present
    assert set(types.keys()) == {
        "openai", "anthropic", "openrouter", "bedrock",
        "vertex", "zai", "ollama",
    }

    # Cloud providers carry catalog-shaped models
    openai_models = types["openai"]["models"]
    assert isinstance(openai_models, list)
    assert len(openai_models) > 0
    first = openai_models[0]
    for key in ("id", "name", "lab", "context_window", "tags"):
        assert key in first, f"missing {key} in ModelInfo"

    # Auth flags survive
    assert types["openai"]["requires_api_key"] is True
    assert types["ollama"]["requires_api_key"] is False
    assert types["ollama"]["requires_endpoint"] is True

    # Ollama yields an empty catalog (models populated per-instance)
    assert types["ollama"]["models"] == []


# ─── bedrock branch (issue #694) ────────────────────────────────────


def test_provider_types_marks_bedrock_aws_credentials():
    result = asyncio.run(providers_mod.provider_types())
    bedrock = result["types"]["bedrock"]
    assert bedrock["requires_aws_credentials"] is True
    assert bedrock["default_region"] == "us-east-1"
    assert bedrock["requires_api_key"] is False
    # Non-bedrock providers must not advertise AWS affordances.
    openai = result["types"]["openai"]
    assert openai["requires_aws_credentials"] is False
    assert openai["default_region"] is None


def test_create_bedrock_stores_aws_creds_and_region(monkeypatch):
    captured = _capture_add_provider(monkeypatch)
    aws_calls: dict = {}

    def fake_set_aws(name, access, secret):
        aws_calls["args"] = (name, access, secret)

    monkeypatch.setattr(providers_mod, "set_provider_aws_credentials", fake_set_aws)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)

    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        default_model="claude-sonnet-4-6",
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secret",
        region="us-west-2",
    )
    asyncio.run(create_provider(body))

    assert captured["provider"]["region"] == "us-west-2"
    assert captured["provider"]["type"] == "bedrock"
    assert "accelerator_vendor" not in captured["provider"]
    assert aws_calls["args"] == ("aws-prod", "AKIATEST", "secret")


def test_create_bedrock_defaults_region_when_omitted(monkeypatch):
    captured = _capture_add_provider(monkeypatch)
    monkeypatch.setattr(
        providers_mod, "set_provider_aws_credentials", lambda *a, **kw: True
    )
    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secret",
    )
    asyncio.run(create_provider(body))
    assert captured["provider"]["region"] == "us-east-1"


def test_create_bedrock_rejects_api_key(monkeypatch):
    _capture_add_provider(monkeypatch)
    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        api_key="sk-bad",
        aws_access_key_id="AKIATEST",
        aws_secret_access_key="secret",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400
    assert "aws" in str(exc_info.value.detail).lower()


def test_create_bedrock_requires_aws_creds(monkeypatch):
    _capture_add_provider(monkeypatch)
    body = ProviderCreate(name="aws-prod", type="bedrock")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


def test_create_non_bedrock_rejects_aws_fields(monkeypatch):
    """AWS fields on a non-bedrock create must 400, not be silently dropped."""
    _capture_add_provider(monkeypatch)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)
    body = ProviderCreate(
        name="cloud",
        type="openrouter",
        api_key="sk-real",
        aws_access_key_id="AKIA-LEAK",
        aws_secret_access_key="leak",
        region="us-east-1",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


def test_update_bedrock_region_only(monkeypatch):
    existing = {
        "name": "aws-prod",
        "type": "bedrock",
        "region": "us-east-1",
    }
    captured: dict = {}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)

    def fake_update(name, updater):
        captured["result"] = updater(existing.copy())

    monkeypatch.setattr(providers_mod, "update_provider", fake_update)

    body = ProviderUpdate(region="us-west-2")
    asyncio.run(update_provider_endpoint("aws-prod", body))
    assert captured["result"]["region"] == "us-west-2"


def test_update_bedrock_rotates_keys_only(monkeypatch):
    existing = {"name": "aws-prod", "type": "bedrock", "region": "us-east-1"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(
        providers_mod,
        "get_provider_aws_credentials",
        lambda name: ("OLD_ACCESS", "OLD_SECRET"),
    )

    set_calls: dict = {}

    def fake_set_aws(name, access, secret):
        set_calls["args"] = (name, access, secret)

    monkeypatch.setattr(providers_mod, "set_provider_aws_credentials", fake_set_aws)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)

    # Rotate only the secret; access key should fall back to existing.
    body = ProviderUpdate(aws_secret_access_key="NEW_SECRET")
    asyncio.run(update_provider_endpoint("aws-prod", body))
    assert set_calls["args"] == ("aws-prod", "OLD_ACCESS", "NEW_SECRET")


def test_update_bedrock_rejects_api_key(monkeypatch):
    existing = {"name": "aws-prod", "type": "bedrock"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)

    body = ProviderUpdate(api_key="sk-bad")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("aws-prod", body))
    assert exc_info.value.status_code == 400


# ─── region validation (#694) ──────────────────────────────────────


def test_create_bedrock_rejects_empty_region(monkeypatch):
    _capture_add_provider(monkeypatch)
    monkeypatch.setattr(
        providers_mod, "set_provider_aws_credentials", lambda *a, **kw: True
    )
    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        aws_access_key_id="AKIA",
        aws_secret_access_key="s",
        region="   ",  # whitespace only
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400
    assert "region" in str(exc_info.value.detail).lower()


def test_create_bedrock_rejects_unsafe_region(monkeypatch):
    """A region with slashes or dots could redirect signed traffic."""
    _capture_add_provider(monkeypatch)
    monkeypatch.setattr(
        providers_mod, "set_provider_aws_credentials", lambda *a, **kw: True
    )
    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        aws_access_key_id="AKIA",
        aws_secret_access_key="s",
        region="us-east-1.evil.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


def test_create_bedrock_normalizes_region_case(monkeypatch):
    captured = _capture_add_provider(monkeypatch)
    monkeypatch.setattr(
        providers_mod, "set_provider_aws_credentials", lambda *a, **kw: True
    )
    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        aws_access_key_id="AKIA",
        aws_secret_access_key="s",
        region="  US-West-2  ",
    )
    asyncio.run(create_provider(body))
    assert captured["provider"]["region"] == "us-west-2"


def test_update_bedrock_rejects_unsafe_region(monkeypatch):
    existing = {"name": "aws-prod", "type": "bedrock", "region": "us-east-1"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    body = ProviderUpdate(region="us-east-1/../evil")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("aws-prod", body))
    assert exc_info.value.status_code == 400


# ─── credential rollback (W1) ──────────────────────────────────────


def test_create_bedrock_rolls_back_on_credential_failure(monkeypatch):
    """If AWS credential storage fails, the provider record must be
    rolled back so we don't leave an orphan record behind."""
    captured = _capture_add_provider(monkeypatch)
    rollback_calls: dict = {}

    def fake_remove(name):
        rollback_calls["name"] = name

    monkeypatch.setattr(providers_mod, "remove_provider", fake_remove)

    def fail_set(name, access, secret):
        raise RuntimeError("keyring offline")

    monkeypatch.setattr(providers_mod, "set_provider_aws_credentials", fail_set)

    body = ProviderCreate(
        name="aws-prod",
        type="bedrock",
        aws_access_key_id="AKIA",
        aws_secret_access_key="s",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 500
    # Generic detail — no exception text leaks.
    assert "keyring" not in str(exc_info.value.detail).lower()
    assert captured["provider"]["name"] == "aws-prod"
    assert rollback_calls.get("name") == "aws-prod"


# ─── delete sanitization (B1) ──────────────────────────────────────


def test_delete_provider_sanitizes_storage_error(monkeypatch):
    """`delete_provider`'s 500 detail must not leak filesystem paths."""
    monkeypatch.setattr(
        providers_mod, "get_provider", lambda name: {"name": name, "type": "openai"}
    )

    def fail_remove(name):
        raise PermissionError("/secret/path/providers.json: permission denied")

    monkeypatch.setattr(providers_mod, "remove_provider", fail_remove)

    from clawrium.gui.routes.providers import delete_provider

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(delete_provider("foo"))
    assert exc_info.value.status_code == 500
    assert "/secret/path" not in str(exc_info.value.detail)


def test_delete_provider_404_when_missing(monkeypatch):
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: None)
    from clawrium.gui.routes.providers import delete_provider

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(delete_provider("nope"))
    assert exc_info.value.status_code == 404


# ─── create error codes (B6) ────────────────────────────────────────


def test_create_duplicate_returns_409(monkeypatch):
    def fake_add(provider):
        from clawrium.core.providers.storage import DuplicateProviderError

        raise DuplicateProviderError("exists")

    monkeypatch.setattr(providers_mod, "add_provider", fake_add)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)
    body = ProviderCreate(name="dup", type="openai", api_key="sk")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 409


def test_create_invalid_name_returns_400(monkeypatch):
    body = ProviderCreate(name="bad name with spaces", type="openai", api_key="sk")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


def test_create_invalid_type_returns_400(monkeypatch):
    body = ProviderCreate(name="ok", type="not-a-real-type", api_key="sk")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


# ─── update 404 (B7) ────────────────────────────────────────────────


def test_update_provider_404_when_missing(monkeypatch):
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: None)
    body = ProviderUpdate(default_model="gpt-4o")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("nope", body))
    assert exc_info.value.status_code == 404


def test_update_bedrock_isolated_rotation_rejected_when_no_existing_creds(monkeypatch):
    """B7: rotating only the secret with no existing access key on file → 400."""
    existing = {"name": "aws-prod", "type": "bedrock"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(
        providers_mod, "get_provider_aws_credentials", lambda name: (None, None)
    )
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    body = ProviderUpdate(aws_secret_access_key="NEW_SECRET")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("aws-prod", body))
    assert exc_info.value.status_code == 400


# ─── _serialize_provider bedrock branch (B2/B3) ─────────────────────


def test_serialize_provider_bedrock_surfaces_aws_status(monkeypatch):
    monkeypatch.setattr(
        providers_mod,
        "get_provider_aws_credentials",
        lambda name: ("AKIA", "secret"),
    )
    monkeypatch.setattr(providers_mod, "get_provider_api_key", lambda name: None)
    out = providers_mod._serialize_provider(
        {
            "name": "aws-prod",
            "type": "bedrock",
            "region": "us-east-1",
            "default_model": "claude-sonnet-4-6",
        }
    )
    assert out["region"] == "us-east-1"
    assert out["has_aws_credentials"] is True
    assert out["has_api_key"] is False


def test_serialize_provider_bedrock_missing_creds(monkeypatch):
    monkeypatch.setattr(
        providers_mod, "get_provider_aws_credentials", lambda name: (None, None)
    )
    monkeypatch.setattr(providers_mod, "get_provider_api_key", lambda name: None)
    out = providers_mod._serialize_provider(
        {"name": "aws-prod", "type": "bedrock", "region": "us-east-1"}
    )
    assert out["has_aws_credentials"] is False


def test_serialize_provider_non_bedrock_omits_aws_check(monkeypatch):
    """Non-bedrock providers must never touch AWS credentials storage."""
    aws_calls: dict = {"count": 0}

    def fake_aws(name):
        aws_calls["count"] += 1
        return (None, None)

    monkeypatch.setattr(providers_mod, "get_provider_aws_credentials", fake_aws)
    monkeypatch.setattr(providers_mod, "get_provider_api_key", lambda name: "sk")
    out = providers_mod._serialize_provider({"name": "p", "type": "openai"})
    assert out["has_api_key"] is True
    assert out["has_aws_credentials"] is False
    assert out["region"] is None
    assert aws_calls["count"] == 0


# ─── B1/B2 iter2: cross-type AWS field rejection ────────────────────


def test_update_non_bedrock_with_aws_fields_rejected(monkeypatch):
    existing = {"name": "cloud", "type": "openrouter"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)
    body = ProviderUpdate(aws_access_key_id="AKIA")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("cloud", body))
    assert exc_info.value.status_code == 400


def test_update_bedrock_rejects_empty_aws_access_key(monkeypatch):
    """Empty string on AWS field is an error, not a silent keep-existing."""
    existing = {"name": "aws-prod", "type": "bedrock"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    body = ProviderUpdate(aws_access_key_id="")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("aws-prod", body))
    assert exc_info.value.status_code == 400


# ─── delete path credential cleanup (B10) ───────────────────────────


def test_delete_provider_calls_credential_removers(monkeypatch):
    monkeypatch.setattr(
        providers_mod, "get_provider", lambda name: {"name": name, "type": "bedrock"}
    )
    monkeypatch.setattr(providers_mod, "remove_provider", lambda name: True)
    api_calls: list = []
    aws_calls: list = []
    monkeypatch.setattr(
        providers_mod,
        "remove_provider_api_key",
        lambda name: api_calls.append(name),
    )
    monkeypatch.setattr(
        providers_mod,
        "remove_provider_aws_credentials",
        lambda name: aws_calls.append(name),
    )
    from clawrium.gui.routes.providers import delete_provider

    asyncio.run(delete_provider("aws-prod"))
    assert api_calls == ["aws-prod"]
    assert aws_calls == ["aws-prod"]


# ─── api_key="" clears stored key (B9 / B5 iter2) ───────────────────


def test_update_empty_api_key_calls_remove(monkeypatch):
    existing = {"name": "p", "type": "openai"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    remove_calls: list = []
    set_calls: list = []
    monkeypatch.setattr(
        providers_mod,
        "remove_provider_api_key",
        lambda name: remove_calls.append(name),
    )
    monkeypatch.setattr(
        providers_mod,
        "set_provider_api_key",
        lambda name, key: set_calls.append((name, key)),
    )
    body = ProviderUpdate(api_key="")
    asyncio.run(update_provider_endpoint("p", body))
    assert remove_calls == ["p"]
    assert set_calls == []


# ─── update path 500-sanitization (B8 partial) ──────────────────────


def test_update_api_key_storage_failure_returns_sanitized_500(monkeypatch):
    existing = {"name": "p", "type": "openai"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)

    def boom(name, key):
        raise RuntimeError("/var/keyring: write-only path")

    monkeypatch.setattr(providers_mod, "set_provider_api_key", boom)
    body = ProviderUpdate(api_key="sk-new")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("p", body))
    assert exc_info.value.status_code == 500
    assert "/var/keyring" not in str(exc_info.value.detail)


# ─── iter4: partial-write protection (PUT cross-field validation) ───


def test_update_bedrock_api_key_does_not_persist_default_model(monkeypatch):
    """Mismatched-family 400 must NOT leave a half-mutated record behind."""
    existing = {
        "name": "aws-prod",
        "type": "bedrock",
        "default_model": "claude-sonnet-4-6",
    }
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    update_calls: list = []

    def fake_update(name, updater):
        update_calls.append(name)

    monkeypatch.setattr(providers_mod, "update_provider", fake_update)

    body = ProviderUpdate(default_model="claude-opus-4-7", api_key="sk-leak")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("aws-prod", body))
    assert exc_info.value.status_code == 400
    # The write must not have run.
    assert update_calls == []


def test_update_bedrock_rejects_endpoint_override(monkeypatch):
    """Bedrock endpoint is region-derived; explicit override is rejected."""
    existing = {"name": "aws-prod", "type": "bedrock"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    body = ProviderUpdate(endpoint="https://evil.example/")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("aws-prod", body))
    assert exc_info.value.status_code == 400
    assert "region" in str(exc_info.value.detail).lower()


# ─── iter4: default_model character-set validation ─────────────────


def test_create_rejects_default_model_with_control_chars(monkeypatch):
    """default_model is interpolated into env templates; control chars rejected."""
    _capture_add_provider(monkeypatch)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)
    body = ProviderCreate(
        name="cloud",
        type="openai",
        api_key="sk",
        default_model="gpt-4o‮\nLEAK",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_provider(body))
    assert exc_info.value.status_code == 400


def test_create_accepts_legitimate_default_model_names(monkeypatch):
    """Real model IDs from the catalog must pass the character-set guard."""
    captured = _capture_add_provider(monkeypatch)
    monkeypatch.setattr(providers_mod, "set_provider_api_key", lambda *a, **kw: True)
    for model in (
        "gpt-4o",
        "claude-opus-4-7",
        "anthropic/claude-3.5-sonnet",
        "meta-llama/Llama-3.1-70B-Instruct:free",
    ):
        body = ProviderCreate(
            name="p", type="openai", api_key="sk", default_model=model
        )
        asyncio.run(create_provider(body))
        assert captured["provider"]["default_model"] == model


def test_update_rejects_invalid_default_model(monkeypatch):
    existing = {"name": "p", "type": "openai"}
    monkeypatch.setattr(providers_mod, "get_provider", lambda name: existing)
    monkeypatch.setattr(providers_mod, "update_provider", lambda *a, **kw: True)
    body = ProviderUpdate(default_model="bad\x00model")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_provider_endpoint("p", body))
    assert exc_info.value.status_code == 400


# ─── iter4: length caps on credentials ─────────────────────────────


def test_pydantic_caps_oversized_aws_secret():
    """Multi-MB secret payloads are rejected at the schema layer."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderCreate(
            name="p",
            type="bedrock",
            aws_access_key_id="AKIA",
            aws_secret_access_key="x" * 1000,
        )


def test_pydantic_caps_oversized_api_key():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderCreate(name="p", type="openai", api_key="x" * 10000)

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

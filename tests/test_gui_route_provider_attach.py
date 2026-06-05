"""Route-level tests for the GUI provider-attach surface (#615).

Mirrors the CLI semantics shipped under #612 for `clawctl agent
provider attach|detach` so the GUI is at functional parity with the
CLI: hermes requires `role`, non-hermes rejects `role`, the
single-provider invariant still pins on the non-hermes path, and the
primary-detach guard fires while aux attachments remain.

The tests drive the route handlers directly rather than spinning up a
FastAPI client — the wiring matters, not Starlette's path routing.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from clawrium.gui.routes import providers as providers_mod
from clawrium.gui.routes.providers import (
    AttachmentRequest,
    _available_roles,
    attach_provider_to_agent,
    detach_provider_from_agent,
    list_agent_attachments,
)


# ─── Fixtures ────────────────────────────────────────────────────────


def _make_host(agent_name: str, agent_type: str, providers: list | None = None):
    return {
        "hostname": f"host-{agent_name}",
        "agents": {
            agent_name: {
                "type": agent_type,
                "agent_name": agent_name,
                "providers": providers or [],
            }
        },
    }


def _install_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_name: str,
    agent_type: str,
    providers: list | None = None,
    provider_records: dict | None = None,
):
    """Wire mocks so the route handlers see a single agent + provider catalog."""
    host = _make_host(agent_name, agent_type, providers)
    state = {"host": host}

    def fake_resolve(name: str):
        if name == agent_name:
            return state["host"], agent_type, state["host"]["agents"][agent_name]
        return None

    def fake_update_host(hostname: str, updater):
        new_host = updater(state["host"])
        if new_host is not None:
            state["host"] = new_host
        return True

    def fake_get_provider(name: str):
        if provider_records and name in provider_records:
            return provider_records[name]
        return None

    monkeypatch.setattr(providers_mod, "_resolve_agent", fake_resolve)
    monkeypatch.setattr(providers_mod, "update_host", fake_update_host)
    monkeypatch.setattr(providers_mod, "get_provider", fake_get_provider)
    return state


def _run(coro):
    return asyncio.run(coro)


# ─── _available_roles unit tests ────────────────────────────────────


def test_available_roles_empty_hermes_returns_primary_only():
    assert _available_roles("hermes", []) == ["primary"]


def test_available_roles_with_primary_returns_aux_slots():
    roles = _available_roles(
        "hermes", [{"name": "anth", "role": "primary", "model": ""}]
    )
    assert "primary" not in roles
    assert "vision" in roles
    assert "title_generation" in roles


def test_available_roles_filters_filled_aux_slots():
    roles = _available_roles(
        "hermes",
        [
            {"name": "anth", "role": "primary", "model": ""},
            {"name": "openrt", "role": "vision", "model": ""},
        ],
    )
    assert "vision" not in roles
    assert "web_extract" in roles


def test_available_roles_non_hermes_returns_empty():
    assert _available_roles("openclaw", []) == []
    assert _available_roles("zeroclaw", []) == []


# ─── GET /attachments/{agent} ───────────────────────────────────────


def test_attachments_hermes_empty_lists_primary(monkeypatch):
    _install_fixture(monkeypatch, agent_name="sage", agent_type="hermes")
    resp = _run(list_agent_attachments("sage"))
    assert resp["supports_multi"] is True
    assert resp["agent_type"] == "hermes"
    assert resp["available_roles"] == ["primary"]
    assert resp["primary_attached"] is False
    assert resp["aux_count"] == 0


def test_attachments_hermes_with_primary_lists_aux(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[{"name": "anth", "role": "primary", "model": "m"}],
    )
    resp = _run(list_agent_attachments("sage"))
    assert resp["primary_attached"] is True
    assert "primary" not in resp["available_roles"]
    assert "vision" in resp["available_roles"]
    assert resp["aux_count"] == 0


def test_attachments_non_hermes_no_role_info(monkeypatch):
    _install_fixture(monkeypatch, agent_name="wise", agent_type="openclaw")
    resp = _run(list_agent_attachments("wise"))
    assert resp["supports_multi"] is False
    assert resp["available_roles"] == []


def test_attachments_unknown_agent_404(monkeypatch):
    _install_fixture(monkeypatch, agent_name="sage", agent_type="hermes")
    with pytest.raises(HTTPException) as exc:
        _run(list_agent_attachments("missing"))
    assert exc.value.status_code == 404


# ─── POST /{name}/attach (hermes) ───────────────────────────────────


def test_attach_hermes_without_role_rejected(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        provider_records={"anth": {"name": "anth", "default_model": "m"}},
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "anth", AttachmentRequest(agent="sage", role=None)
            )
        )
    assert exc.value.status_code == 400
    assert "role is required" in exc.value.detail


def test_attach_hermes_invalid_role_rejected(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        provider_records={"anth": {"name": "anth", "default_model": "m"}},
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "anth", AttachmentRequest(agent="sage", role="bogus")
            )
        )
    assert exc.value.status_code == 400
    assert "invalid role" in exc.value.detail


def test_attach_hermes_primary_succeeds(monkeypatch):
    state = _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        provider_records={"anth": {"name": "anth", "default_model": "model-x"}},
    )
    resp = _run(
        attach_provider_to_agent(
            "anth", AttachmentRequest(agent="sage", role="primary")
        )
    )
    assert resp["success"] is True
    assert resp["role"] == "primary"
    stored = state["host"]["agents"]["sage"]["providers"]
    assert stored == [{"name": "anth", "role": "primary", "model": "model-x"}]


def test_attach_hermes_aux_after_primary_succeeds(monkeypatch):
    state = _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[{"name": "anth", "role": "primary", "model": "m"}],
        provider_records={
            "openrt": {"name": "openrt", "default_model": "model-aux"},
        },
    )
    resp = _run(
        attach_provider_to_agent(
            "openrt", AttachmentRequest(agent="sage", role="vision")
        )
    )
    assert resp["success"] is True
    stored = state["host"]["agents"]["sage"]["providers"]
    assert len(stored) == 2
    assert stored[1] == {"name": "openrt", "role": "vision", "model": "model-aux"}


def test_attach_hermes_duplicate_aux_rejected(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[
            {"name": "anth", "role": "primary", "model": "m"},
            {"name": "openrt", "role": "vision", "model": ""},
        ],
        provider_records={"alt": {"name": "alt", "default_model": "x"}},
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "alt", AttachmentRequest(agent="sage", role="vision")
            )
        )
    # AttachmentError → HTTP 400
    assert exc.value.status_code == 400
    assert "vision" in exc.value.detail


def test_attach_unknown_provider_404(monkeypatch):
    _install_fixture(monkeypatch, agent_name="sage", agent_type="hermes")
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "ghost", AttachmentRequest(agent="sage", role="primary")
            )
        )
    assert exc.value.status_code == 404
    assert "ghost" in exc.value.detail


def test_attach_hermes_idempotent_same_role_returns_already_attached(monkeypatch):
    state = _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[{"name": "anth", "role": "primary", "model": "m"}],
        provider_records={"anth": {"name": "anth", "default_model": "m"}},
    )
    resp = _run(
        attach_provider_to_agent(
            "anth", AttachmentRequest(agent="sage", role="primary")
        )
    )
    assert resp["success"] is True
    assert resp["already_attached"] is True
    # State unchanged — still exactly one provider attached.
    assert state["host"]["agents"]["sage"]["providers"] == [
        {"name": "anth", "role": "primary", "model": "m"}
    ]


def test_attach_hermes_rebind_without_detach_rejected(monkeypatch):
    """Re-attaching a provider with a different role must require detach
    first — silently rebinding would lose track of the operator's
    intent."""
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[{"name": "anth", "role": "primary", "model": "m"}],
        provider_records={"anth": {"name": "anth", "default_model": "m"}},
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "anth", AttachmentRequest(agent="sage", role="vision")
            )
        )
    assert exc.value.status_code == 409
    assert "detach" in exc.value.detail.lower()


def test_available_roles_all_aux_filled_returns_empty():
    """Boundary case: every aux slot occupied plus primary → no roles
    left for a fresh attach. Pins the `→ []` branch in
    `_available_roles()`."""
    from clawrium.core.provider_attachments import AUXILIARY_SLOTS

    attachments = [
        {"name": "anth", "role": "primary", "model": ""},
    ] + [{"name": f"p-{slot}", "role": slot, "model": ""} for slot in AUXILIARY_SLOTS]
    assert _available_roles("hermes", attachments) == []


# ─── POST /{name}/attach (non-hermes) ───────────────────────────────


def test_attach_non_hermes_rejects_role(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="wise",
        agent_type="openclaw",
        provider_records={"anth": {"name": "anth", "default_model": "m"}},
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "anth", AttachmentRequest(agent="wise", role="primary")
            )
        )
    assert exc.value.status_code == 400
    assert "role is not supported" in exc.value.detail


def test_attach_non_hermes_singleton_invariant(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="wise",
        agent_type="openclaw",
        providers=["existing"],
        provider_records={"new": {"name": "new", "default_model": "m"}},
    )
    with pytest.raises(HTTPException) as exc:
        _run(
            attach_provider_to_agent(
                "new", AttachmentRequest(agent="wise", role=None)
            )
        )
    assert exc.value.status_code == 409
    assert "existing" in exc.value.detail


def test_attach_non_hermes_first_attach_succeeds(monkeypatch):
    state = _install_fixture(
        monkeypatch,
        agent_name="wise",
        agent_type="openclaw",
        provider_records={"anth": {"name": "anth", "default_model": "m"}},
    )
    resp = _run(
        attach_provider_to_agent(
            "anth", AttachmentRequest(agent="wise", role=None)
        )
    )
    assert resp["success"] is True
    assert resp["role"] is None
    assert state["host"]["agents"]["wise"]["providers"] == ["anth"]


# ─── DELETE /{name}/attach ──────────────────────────────────────────


def test_detach_primary_with_aux_remaining_rejected(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[
            {"name": "anth", "role": "primary", "model": "m"},
            {"name": "openrt", "role": "vision", "model": ""},
        ],
    )
    with pytest.raises(HTTPException) as exc:
        _run(detach_provider_from_agent("anth", agent="sage"))
    assert exc.value.status_code == 409
    assert "auxiliary" in exc.value.detail


def test_detach_primary_when_alone_succeeds(monkeypatch):
    state = _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[{"name": "anth", "role": "primary", "model": "m"}],
    )
    resp = _run(detach_provider_from_agent("anth", agent="sage"))
    assert resp["success"] is True
    assert state["host"]["agents"]["sage"]["providers"] == []


def test_detach_aux_first_then_primary(monkeypatch):
    state = _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[
            {"name": "anth", "role": "primary", "model": "m"},
            {"name": "openrt", "role": "vision", "model": ""},
        ],
    )
    _run(detach_provider_from_agent("openrt", agent="sage"))
    assert len(state["host"]["agents"]["sage"]["providers"]) == 1
    _run(detach_provider_from_agent("anth", agent="sage"))
    assert state["host"]["agents"]["sage"]["providers"] == []


def test_detach_unknown_provider_404(monkeypatch):
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[{"name": "anth", "role": "primary", "model": "m"}],
    )
    with pytest.raises(HTTPException) as exc:
        _run(detach_provider_from_agent("ghost", agent="sage"))
    assert exc.value.status_code == 404
    assert "ghost" in exc.value.detail


def test_detach_primary_409_lists_blocking_aux_names(monkeypatch):
    """Operator should see exactly which aux attachments are blocking
    the primary detach so they can act without an extra GET round-trip
    — parity with the CLI's `aux_hint` message."""
    _install_fixture(
        monkeypatch,
        agent_name="sage",
        agent_type="hermes",
        providers=[
            {"name": "anth", "role": "primary", "model": "m"},
            {"name": "openrt", "role": "vision", "model": ""},
            {"name": "alt", "role": "web_extract", "model": ""},
        ],
    )
    with pytest.raises(HTTPException) as exc:
        _run(detach_provider_from_agent("anth", agent="sage"))
    assert exc.value.status_code == 409
    assert "openrt" in exc.value.detail
    assert "alt" in exc.value.detail


def test_detach_non_hermes_singleton_succeeds(monkeypatch):
    """Exercise the `list[str]` normalize path on the detach surface so
    a regression in the non-hermes shape doesn't slip through."""
    state = _install_fixture(
        monkeypatch,
        agent_name="wise",
        agent_type="openclaw",
        providers=["anth"],
    )
    resp = _run(detach_provider_from_agent("anth", agent="wise"))
    assert resp["success"] is True
    assert resp["name"] == "anth"
    assert state["host"]["agents"]["wise"]["providers"] == []

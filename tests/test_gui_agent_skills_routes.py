"""Tests for the per-agent skills GUI routes (Phase 5).

Covers the exit gates from issue #384:

- ``GET /api/agents/{agent}/skills`` returns ``installed`` + ``available``
  arrays, with ``available`` filtered by the resolved ``agent_type``
  (clawrium-cross-agent + matching native registry only).
- ``POST /api/agents/{agent}/skills/{registry}/{skill}`` mutates desired
  state and dispatches ``apply_state``; idempotent on the no-op path.
- ``DELETE`` mirrors POST: state cleanup + unconditional apply.
- Error mapping: 404 unknown agent, 422 malformed ref, 502 on apply
  failure, 422 on incompatible-claw install.

We mock ``apply_state`` to avoid real ansible/SSH, and ``_resolve_agent``
to keep the test independent of the user's ``hosts.json``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from clawrium.core.skills import (
    ExternalSourceBlocked,
    parse_skill_ref,
)
from clawrium.core.skills_apply import (
    ApplyResult,
    SkillApplyError,
    SkillApplyNotSupported,
)
from clawrium.core.skills_state import read_state, write_state
from clawrium.gui.routes import agents as agents_route


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Per-test XDG_CONFIG_HOME so the desired-state file is fresh."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _run(coro):
    return asyncio.run(coro)


def _stub_resolved(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_name: str = "tdd-hermes",
    agent_type: str = "hermes",
    hostname: str = "wolf-i",
    resolved: bool = True,
) -> dict[str, Any]:
    """Stub _resolve_agent. Returns the agent_record dict for assertions."""
    agent_record = {"agent_name": agent_name}
    host_record = {"hostname": hostname}

    def fake(_key: str):
        if not resolved:
            return None
        return (host_record, agent_type, agent_record)

    monkeypatch.setattr(agents_route, "_resolve_agent", fake)
    return agent_record


def _stub_apply(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_type: str = "hermes",
    applied: list[str] | None = None,
    raises: Exception | None = None,
) -> list[str]:
    """Stub apply_state with a recorder that respects current desired state."""
    calls: list[str] = []

    def fake(agent_name: str, **_kwargs):
        calls.append(agent_name)
        if raises is not None:
            raise raises
        return ApplyResult(
            agent_name=agent_name,
            agent_type=agent_type,
            hostname="wolf-i",
            applied_skills=applied if applied is not None else read_state(agent_name),
            log_dir=Path("/tmp/fake-log"),
        )

    monkeypatch.setattr(agents_route, "apply_state", fake)
    return calls


# ---------- GET /api/agents/{agent}/skills ----------------------------------


def test_list_returns_404_when_agent_not_resolved(monkeypatch):
    _stub_resolved(monkeypatch, resolved=False)
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.list_agent_skills("ghost"))
    assert exc.value.status_code == 404


def test_list_includes_installed_and_available_for_hermes(monkeypatch):
    _stub_resolved(monkeypatch, agent_type="hermes")
    write_state("tdd-hermes", ["clawrium/tdd"])

    result = _run(agents_route.list_agent_skills("tdd-hermes"))

    assert result["agent_name"] == "tdd-hermes"
    assert result["agent_type"] == "hermes"

    installed_refs = [row["ref"] for row in result["installed"]]
    assert installed_refs == ["clawrium/tdd"]
    # Installed row carries summary metadata so the UI can render the
    # description without a second round-trip.
    tdd_row = result["installed"][0]
    assert tdd_row["registry"] == "clawrium"
    assert tdd_row["name"] == "tdd"
    assert tdd_row["description"]
    assert tdd_row["version"]

    # Available picker is filtered to clawrium/* + matching <claw>/*.
    available_registries = {row["registry"] for row in result["available"]}
    # hermes claw → no openclaw/zeroclaw native entries leak in.
    assert "openclaw" not in available_registries
    assert "zeroclaw" not in available_registries
    # clawrium/tdd is universally compatible so it must show up.
    available_refs = {row["ref"] for row in result["available"]}
    assert "clawrium/tdd" in available_refs


def test_list_filters_available_to_openclaw_only(monkeypatch):
    _stub_resolved(monkeypatch, agent_name="tdd-openclaw", agent_type="openclaw")
    result = _run(agents_route.list_agent_skills("tdd-openclaw"))

    for row in result["available"]:
        assert row["registry"] in {"clawrium", "openclaw"}, row


def test_list_filters_available_to_zeroclaw_only(monkeypatch):
    _stub_resolved(monkeypatch, agent_name="tdd-zeroclaw", agent_type="zeroclaw")
    result = _run(agents_route.list_agent_skills("tdd-zeroclaw"))

    for row in result["available"]:
        assert row["registry"] in {"clawrium", "zeroclaw"}, row


def test_list_handles_empty_desired_state(monkeypatch):
    _stub_resolved(monkeypatch)
    result = _run(agents_route.list_agent_skills("tdd-hermes"))
    assert result["installed"] == []
    assert any(r["ref"] == "clawrium/tdd" for r in result["available"])


# ---------- POST /api/agents/{agent}/skills/{registry}/{skill} ---------------


def test_install_writes_state_and_calls_apply(monkeypatch):
    _stub_resolved(monkeypatch)
    calls = _stub_apply(monkeypatch, applied=["clawrium/tdd"])

    result = _run(agents_route.install_agent_skill("tdd-hermes", "clawrium", "tdd"))

    assert result["success"] is True
    assert result["ref"] == "clawrium/tdd"
    assert result["changed"] is True
    assert result["installed"] == ["clawrium/tdd"]
    assert calls == ["tdd-hermes"]
    assert read_state("tdd-hermes") == ["clawrium/tdd"]


def test_install_is_idempotent_but_still_applies(monkeypatch):
    """Re-installing an already-installed skill is the documented drift
    recovery path — state is unchanged but the playbook still runs."""
    _stub_resolved(monkeypatch)
    write_state("tdd-hermes", ["clawrium/tdd"])
    calls = _stub_apply(monkeypatch, applied=["clawrium/tdd"])

    result = _run(agents_route.install_agent_skill("tdd-hermes", "clawrium", "tdd"))

    assert result["changed"] is False
    assert calls == ["tdd-hermes"], "apply_state must run on re-install"


def test_install_404_when_agent_missing(monkeypatch):
    _stub_resolved(monkeypatch, resolved=False)
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.install_agent_skill("ghost", "clawrium", "tdd"))
    assert exc.value.status_code == 404


def test_install_422_on_unknown_registry(monkeypatch):
    """An unknown registry token (``http:``, ``bogus``, …) routed through
    the path-parameter form fails inside ``parse_skill_ref`` with
    ``InvalidSkillRef`` — *not* ``ExternalSourceBlocked``. The route maps
    both to 422 the same way; the test is renamed (ATX-1 W8) to match
    the actual exception class so a future reader doesn't think this
    line exercises the external-source guard.

    ``ExternalSourceBlocked`` is unreachable from a path-parameter
    request because the FastAPI router forbids a path segment from
    containing ``/`` or ``://`` — see
    ``test_external_source_blocked_at_parser_level`` for the direct
    parser test of that boundary.
    """
    _stub_resolved(monkeypatch)
    # apply_state must NOT be called — assert by raising if it is.
    monkeypatch.setattr(agents_route, "apply_state", _raises_if_called("apply_state"))
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.install_agent_skill("tdd-hermes", "http:", "bad"))
    assert exc.value.status_code == 422


def test_external_source_blocked_at_parser_level():
    """Direct parser test for the security boundary the GUI relies on.

    ATX-1 W8 flagged that the path-param route can't reach
    ``ExternalSourceBlocked`` (FastAPI strips the protocol delimiter).
    The actual guard lives in ``parse_skill_ref``; this asserts it
    fires for url-shaped inputs.
    """
    for ref in (
        "https://evil.example/skill",
        "http://evil.example/skill",
        "git+https://evil.example/skill",
    ):
        with pytest.raises(ExternalSourceBlocked):
            parse_skill_ref(ref)


def test_install_422_on_unsupported_claw_type(monkeypatch):
    """ATX-1 B3: cover the ``SkillApplyNotSupported`` → 422 mapping.

    Without this, the route could silently regress to 500 on an unknown
    claw type and the existing 200/422/502 tests would still pass.
    ATX-2 W6 also requires asserting the detail string is the original
    message, not the redacted ``Check server logs…`` text — that path
    is reserved for the genuine apply-failure class.
    """
    _stub_resolved(monkeypatch)
    detail = "Skills apply for 'nemoclaw' has no playbook"
    _stub_apply(monkeypatch, raises=SkillApplyNotSupported(detail))
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.install_agent_skill("tdd-hermes", "clawrium", "tdd"))
    assert exc.value.status_code == 422
    assert detail in str(exc.value.detail)
    assert "Check server logs" not in str(exc.value.detail)


def test_remove_422_on_unsupported_claw_type(monkeypatch):
    _stub_resolved(monkeypatch)
    detail = "Skills apply for 'nemoclaw' has no playbook"
    _stub_apply(monkeypatch, raises=SkillApplyNotSupported(detail))
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.remove_agent_skill("tdd-hermes", "clawrium", "tdd"))
    assert exc.value.status_code == 422
    assert detail in str(exc.value.detail)
    assert "Check server logs" not in str(exc.value.detail)


def test_remove_502_on_apply_error(monkeypatch):
    """ATX-2 W7: mirror the install-side path-scrubbing assertion on
    the DELETE side so the redaction can't regress only for removes.
    """
    _stub_resolved(monkeypatch)
    write_state("tdd-hermes", ["clawrium/tdd"])
    raw_msg = (
        "Skills apply failed (status=failed): host unreachable "
        "(log: /home/op/.config/clawrium/logs/skills_apply-x)."
    )
    _stub_apply(monkeypatch, raises=SkillApplyError(raw_msg))
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.remove_agent_skill("tdd-hermes", "clawrium", "tdd"))
    assert exc.value.status_code == 502
    assert "/home/op/.config/clawrium/logs" not in str(exc.value.detail)
    assert "Check server logs" in str(exc.value.detail)
    # Remove already mutated desired-state before apply_state ran;
    # an apply failure does not restore the removed ref — the user
    # retries with a fresh `clm agent skill install` if they want it
    # back. (ATX-3 S3 clarifies the W3 contract on the delete side.)
    assert read_state("tdd-hermes") == []


def test_install_422_on_incompatible_claw(monkeypatch):
    """Installing a hermes-native skill on an openclaw agent must surface
    as 422 (IncompatibleSkillRegistry) — caught inside apply_state's
    pre-check, not on the host."""
    _stub_resolved(monkeypatch, agent_name="tdd-openclaw", agent_type="openclaw")
    write_state("tdd-openclaw", [])

    # Real apply_state will refuse: write the state then let the real
    # code path validate. But we don't want a real run — supply a fake
    # apply_state that raises IncompatibleSkillRegistry.
    from clawrium.core.skills import IncompatibleSkillRegistry

    def fake(_name: str, **_kw):
        raise IncompatibleSkillRegistry(
            "Skill 'hermes/foo' from registry 'hermes' is not installable "
            "on openclaw agents."
        )

    monkeypatch.setattr(agents_route, "apply_state", fake)

    with pytest.raises(HTTPException) as exc:
        _run(agents_route.install_agent_skill("tdd-openclaw", "hermes", "foo"))
    assert exc.value.status_code == 422


def test_install_502_on_apply_error(monkeypatch):
    _stub_resolved(monkeypatch)
    # Reproduces the exact message shape core.skills_apply ships — embeds
    # a log dir absolute path so the test fails if we ever stop redacting.
    raw_msg = (
        "Skills apply failed (status=failed): host unreachable: "
        "/tmp/nope (log: /home/op/.config/clawrium/logs/skills_apply-x)."
    )
    _stub_apply(monkeypatch, raises=SkillApplyError(raw_msg))
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.install_agent_skill("tdd-hermes", "clawrium", "tdd"))
    assert exc.value.status_code == 502
    # ATX-1 B1: 502 detail must NOT echo the original path-bearing message.
    assert "/home/op/.config/clawrium/logs" not in str(exc.value.detail)
    assert "/tmp/nope" not in str(exc.value.detail)
    assert "Check server logs" in str(exc.value.detail)
    # State should still reflect the user's intent — apply failures
    # don't roll back desired state; the user will retry.
    assert read_state("tdd-hermes") == ["clawrium/tdd"]


# ---------- DELETE /api/agents/{agent}/skills/{registry}/{skill} -------------


def test_remove_drops_state_and_calls_apply(monkeypatch):
    _stub_resolved(monkeypatch)
    write_state("tdd-hermes", ["clawrium/tdd"])
    calls = _stub_apply(monkeypatch, applied=[])

    result = _run(agents_route.remove_agent_skill("tdd-hermes", "clawrium", "tdd"))

    assert result["success"] is True
    assert result["changed"] is True
    assert result["installed"] == []
    assert calls == ["tdd-hermes"]
    assert read_state("tdd-hermes") == []


def test_remove_is_idempotent_on_missing_skill(monkeypatch):
    _stub_resolved(monkeypatch)
    calls = _stub_apply(monkeypatch, applied=[])

    result = _run(agents_route.remove_agent_skill("tdd-hermes", "clawrium", "tdd"))

    assert result["changed"] is False
    assert calls == ["tdd-hermes"], "apply_state must run even on no-op remove"


def test_remove_404_when_agent_missing(monkeypatch):
    _stub_resolved(monkeypatch, resolved=False)
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.remove_agent_skill("ghost", "clawrium", "tdd"))
    assert exc.value.status_code == 404


def test_remove_422_on_malformed_ref(monkeypatch):
    _stub_resolved(monkeypatch)
    monkeypatch.setattr(agents_route, "apply_state", _raises_if_called("apply_state"))
    with pytest.raises(HTTPException) as exc:
        _run(agents_route.remove_agent_skill("tdd-hermes", "bogus", "tdd"))
    assert exc.value.status_code == 422


# ---------- Documented behavior on apply failure ------------------------------


def test_state_is_not_rolled_back_on_apply_failure(monkeypatch):
    """ATX-1 W3 documents the design choice (carried over from the CLI):
    on apply failure the desired-state mutation is *kept*, so the user
    can retry the apply without re-typing the ref. This test pins the
    behavior so any future change to "validate-before-write" is
    deliberate, not accidental.
    """
    _stub_resolved(monkeypatch)
    _stub_apply(monkeypatch, raises=SkillApplyError("host unreachable"))
    with pytest.raises(HTTPException):
        _run(agents_route.install_agent_skill("tdd-hermes", "clawrium", "tdd"))
    assert read_state("tdd-hermes") == ["clawrium/tdd"]


# ---------- _is_compatible_for_agent_type unit tests --------------------------


@pytest.mark.parametrize(
    "registry,name,agent_type,expected",
    [
        # Native registry, claw match: drop through to load+validate.
        (
            "hermes",
            "ANY",
            "hermes",
            False,
        ),  # no real hermes/ANY skill → loader fails-closed
        # Native registry, claw mismatch: short-circuit false without loading.
        ("hermes", "anything", "openclaw", False),
        ("openclaw", "anything", "zeroclaw", False),
        # Unknown source registry: short-circuit false.
        ("not-a-registry", "tdd", "hermes", False),
        # clawrium/tdd is the seed skill — compatible with every native claw.
        ("clawrium", "tdd", "hermes", True),
        ("clawrium", "tdd", "openclaw", True),
        ("clawrium", "tdd", "zeroclaw", True),
        # Unknown agent type fails closed via check_agent_compatibility.
        ("clawrium", "tdd", "nemoclaw", False),
        # Catalog row that doesn't exist fails closed at load_skill.
        ("clawrium", "missing-skill", "hermes", False),
    ],
)
def test_is_compatible_for_agent_type_matrix(
    registry: str, name: str, agent_type: str, expected: bool
):
    """ATX-1 B5/W2: every branch of the filter — including the
    fail-closed paths — is covered with a direct unit test, not just
    inferred via the route-level happy path."""
    assert (
        agents_route._is_compatible_for_agent_type(registry, name, agent_type)
        is expected
    )


# ---------- _skill_error_status mapping table ---------------------------------


def test_skill_error_status_table():
    """Pin every concrete ``SkillError`` subclass → status code so a
    future subclass added without wiring stays loud (defaults to 500
    via the fallback branch)."""
    from clawrium.core.skills import (
        InvalidSkillRef,
        MissingRegistryPrefix,
        SchemaValidationError,
    )
    from clawrium.core.skills_apply import (
        AgentNotFoundError,
        SkillApplyError,
        SkillApplyNotSupported,
    )

    cases: list[tuple[Exception, int]] = [
        (AgentNotFoundError("a"), 404),
        (SkillNotFoundLike(), 404),  # SkillNotFound — see helper below
        (SkillApplyError("x"), 502),
        (SkillApplyNotSupported("x"), 422),
        (MissingRegistryPrefix("x"), 422),
        (ExternalSourceBlocked("x"), 422),
        (InvalidSkillRef("x"), 422),
        (IncompatibleSkillRegistryLike(), 422),
        (SchemaValidationError("x"), 422),
    ]
    for error, expected in cases:
        assert agents_route._skill_error_status(error) == expected, error


def test_skill_error_status_falls_back_to_500_for_unknown_subclass():
    """A subclass added later without wiring should not silently
    register as a client error — fallback is 500."""
    from clawrium.core.skills import SkillError

    class _NovelSkillError(SkillError):
        pass

    assert agents_route._skill_error_status(_NovelSkillError("x")) == 500


# ---------- Helpers -----------------------------------------------------------


# Cannot construct SkillNotFound / IncompatibleSkillRegistry with the
# bare base-class init in some refactors; alias them at the import site
# so the table above stays declarative.
from clawrium.core.skills import (  # noqa: E402
    IncompatibleSkillRegistry,
    SkillNotFound,
)


class SkillNotFoundLike(SkillNotFound):
    def __init__(self) -> None:
        super().__init__("skill x not in catalog")


class IncompatibleSkillRegistryLike(IncompatibleSkillRegistry):
    def __init__(self) -> None:
        super().__init__("not compatible")


def _raises_if_called(label: str):
    def _raise(*_args, **_kwargs):
        raise AssertionError(f"{label} should not have been called")

    return _raise

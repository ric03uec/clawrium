"""Issue #612 — hermes multi-provider attach/detach via clawctl.

Covers the CLI surface added under parent #589:

- `--role primary` required for the first attach on hermes
- attach without `--role` rejected with a remediation hint
- second `--role <aux>` attach succeeds and shows up in `get`
- `get` table renders `name`, `role`, `model` columns
- `detach` of primary is rejected while aux attachments remain
- non-hermes still rejects the second attach with the verbatim
  `single-provider invariant` phrase pinned from
  `core/provider_attachments.validate()`
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _create_provider(name: str, ptype: str = "anthropic") -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            name,
            "--type",
            ptype,
            "--api-key",
            "k",
        ],
    )
    assert result.exit_code == 0, result.output


def test_hermes_attach_without_role_is_rejected(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    result = runner.invoke(
        app, ["agent", "provider", "attach", "anth", "--agent", "sage-hermes"]
    )
    assert result.exit_code != 0, result.output
    assert "--role is required" in result.output
    # Hint must surface primary as the canonical first-attach role.
    assert "primary" in result.output


def test_hermes_attach_primary_succeeds(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "attached" in result.output
    assert "primary" in result.output


def test_hermes_attach_aux_after_primary(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    _create_provider("openrt", ptype="openrouter")
    setup = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert setup.exit_code == 0, setup.output
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "openrt",
            "--agent",
            "sage-hermes",
            "--role",
            "vision",
        ],
    )
    assert result.exit_code == 0, result.output

    listed = runner.invoke(
        app, ["agent", "provider", "get", "--agent", "sage-hermes", "-o", "json"]
    )
    data = json.loads(listed.output)
    by_name = {p["name"]: p for p in data}
    assert by_name["anth"]["role"] == "primary"
    assert by_name["openrt"]["role"] == "vision"


def test_hermes_attach_invalid_role(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "not-a-real-slot",
        ],
    )
    assert result.exit_code != 0
    assert "invalid --role" in result.output


def test_hermes_attach_duplicate_primary_rejected(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    _create_provider("openrt", ptype="openrouter")
    setup = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert setup.exit_code == 0, setup.output
    # Attaching a second primary must fail (validate() enforces exactly
    # one primary). Pin the verbatim phrase from
    # `provider_attachments.validate()` — a refactor that re-routes the
    # error through a different code path would silently regress UX.
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "openrt",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert result.exit_code != 0, result.output
    assert "primary" in result.output
    assert "requires exactly one" in result.output


def test_hermes_attach_same_name_with_different_role_rejected(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    _create_provider("anth")
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "vision",
        ],
    )
    assert result.exit_code != 0
    assert "already attached" in result.output


def test_hermes_attach_idempotent_same_role(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert result.exit_code == 0
    assert "already attached" in result.output


def test_hermes_get_table_renders_role_and_model_columns(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    _create_provider("anth")
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    result = runner.invoke(
        app, ["agent", "provider", "get", "--agent", "sage-hermes"]
    )
    assert result.exit_code == 0, result.output
    assert "ROLE" in result.output
    assert "MODEL" in result.output


def test_hermes_detach_primary_blocked_when_aux_present(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    _create_provider("anth")
    _create_provider("openrt", ptype="openrouter")
    p_setup = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert p_setup.exit_code == 0, p_setup.output
    a_setup = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "openrt",
            "--agent",
            "sage-hermes",
            "--role",
            "vision",
        ],
    )
    assert a_setup.exit_code == 0, a_setup.output
    result = runner.invoke(
        app,
        ["agent", "provider", "detach", "anth", "--agent", "sage-hermes"],
    )
    assert result.exit_code != 0, result.output
    assert "primary" in result.output
    # Hint should mention detaching aux first.
    assert "openrt" in result.output


def test_hermes_detach_primary_succeeds_when_alone(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    _create_provider("anth")
    runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    result = runner.invoke(
        app,
        ["agent", "provider", "detach", "anth", "--agent", "sage-hermes"],
    )
    assert result.exit_code == 0, result.output


def test_hermes_detach_aux_then_primary(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    _create_provider("openrt", ptype="openrouter")
    for args in (
        ["anth", "--role", "primary"],
        ["openrt", "--role", "vision"],
    ):
        setup = runner.invoke(
            app,
            ["agent", "provider", "attach", args[0], "--agent", "sage-hermes"]
            + args[1:],
        )
        assert setup.exit_code == 0, setup.output
    # Detach aux first, then primary should succeed.
    aux = runner.invoke(
        app,
        ["agent", "provider", "detach", "openrt", "--agent", "sage-hermes"],
    )
    assert aux.exit_code == 0
    primary = runner.invoke(
        app,
        ["agent", "provider", "detach", "anth", "--agent", "sage-hermes"],
    )
    assert primary.exit_code == 0


def test_non_hermes_rejects_role_flag(hermes_fleet_dir, stdin_not_tty) -> None:
    _create_provider("anth")
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "wise-hypatia",
            "--role",
            "primary",
        ],
    )
    assert result.exit_code != 0
    assert "--role" in result.output


def test_non_hermes_singleton_invariant_preserved(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    """The verbatim `single-provider invariant` phrase from
    provider_attachments.validate() is pinned by docs + tests; the
    refactor must not regress the existing UX on zeroclaw/openclaw.

    The UX on the second-attach path is delivered via the
    `already has provider` clawctl-level error (the same message the
    pre-#612 code emitted) — the verbatim phrase remains the one
    `validate()` raises if attachments are ever forced past the CLI
    guard (e.g., by hand-editing hosts.json).
    """
    from clawrium.core.provider_attachments import AttachmentError, validate
    import pytest

    _create_provider("anth")
    _create_provider("openrt", ptype="openrouter")
    first = runner.invoke(
        app,
        ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        ["agent", "provider", "attach", "openrt", "--agent", "wise-hypatia"],
    )
    assert second.exit_code != 0
    assert "already has provider" in second.output
    assert "anth" in second.output

    # And the validate()-level phrase is still wired up exactly as docs
    # reference it.
    with pytest.raises(AttachmentError, match="single-provider invariant"):
        validate(["a", "b"], "openclaw")


def test_non_hermes_get_table_omits_role_and_model_columns(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-1 B3: pin the back-compat column layout on singleton
    agent types. If the `multi` gate ever mis-fires for openclaw, the
    table would silently grow ROLE/MODEL columns and break any tooling
    that grepped the legacy two-column output.
    """
    _create_provider("anth")
    setup = runner.invoke(
        app,
        ["agent", "provider", "attach", "anth", "--agent", "wise-hypatia"],
    )
    assert setup.exit_code == 0, setup.output

    result = runner.invoke(
        app, ["agent", "provider", "get", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0, result.output
    assert "NAME" in result.output
    assert "ROLE" not in result.output
    assert "MODEL" not in result.output


def test_hermes_attach_duplicate_aux_slot_rejected(
    hermes_fleet_dir, stdin_not_tty
) -> None:
    """Both ATX iter-1 W7 + lifecycle suggestion: same aux slot filled
    twice must error with the validate()-layer 'already filled' phrase
    so the UX is testable independent of the CLI guard.
    """
    _create_provider("anth")
    _create_provider("openrt", ptype="openrouter")
    primary = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "anth",
            "--agent",
            "sage-hermes",
            "--role",
            "primary",
        ],
    )
    assert primary.exit_code == 0, primary.output
    aux_a = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "openrt",
            "--agent",
            "sage-hermes",
            "--role",
            "vision",
        ],
    )
    assert aux_a.exit_code == 0, aux_a.output
    # Reuse the same vision slot with a third provider.
    _create_provider("oai", ptype="openai")
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "attach",
            "oai",
            "--agent",
            "sage-hermes",
            "--role",
            "vision",
        ],
    )
    assert result.exit_code != 0, result.output
    assert "vision" in result.output
    assert "already filled" in result.output


def test_set_attachments_validation_gate_blocks_persistence(
    hermes_fleet_dir, monkeypatch
) -> None:
    """ATX iter-1 B4: even if `emit_error` is patched to a no-op (or
    swallowed in tests), `_set_attachments` must NOT call
    `update_host()` when `validate()` rejects the attachments. Pins
    the early-return-after-emit-error contract.
    """
    from clawrium.cli.clawctl.agent import provider as provider_mod

    captured: dict[str, object] = {"errors": [], "updates": []}

    def fake_emit_error(message: str, **_: object) -> None:
        captured["errors"].append(message)  # type: ignore[attr-defined]
        # Intentionally do NOT raise — this is the test isolation
        # behavior the gate must survive.

    def fake_update_host(*args: object, **kwargs: object) -> bool:
        captured["updates"].append((args, kwargs))  # type: ignore[attr-defined]
        return True

    monkeypatch.setattr(provider_mod, "emit_error", fake_emit_error)
    monkeypatch.setattr(provider_mod, "update_host", fake_update_host)

    # Two primaries on hermes: validate() raises AttachmentError. The
    # function must surface the error AND return without persisting.
    result = provider_mod._set_attachments(
        "10.0.0.1",
        "sage-hermes",
        "hermes",
        [
            {"name": "a", "role": "primary", "model": ""},
            {"name": "b", "role": "primary", "model": ""},
        ],
    )
    assert result is False
    assert captured["errors"], "emit_error must surface the validation failure"
    assert not captured["updates"], (
        "update_host must NOT be called when validate() rejects the "
        "attachment list"
    )

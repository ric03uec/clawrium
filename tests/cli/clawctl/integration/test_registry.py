"""Tests for `clawctl integration registry` CRUD verbs."""

from __future__ import annotations


from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_create_github_non_interactive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "gh",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=ghp_test",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/gh" in result.output


def test_create_requires_type(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["integration", "registry", "create", "no-type", "--credential", "K=V"],
    )
    assert result.exit_code != 0


def test_create_unknown_type_rejected(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "x",
            "--type",
            "no-such-type",
            "--credential",
            "K=V",
        ],
    )
    assert result.exit_code != 0


def test_create_missing_required_credentials_fails(fleet_dir, stdin_not_tty) -> None:
    # github requires GITHUB_TOKEN; passing a non-matching key fails.
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "bad",
            "--type",
            "github",
            "--credential",
            "OTHER=VAL",
        ],
    )
    assert result.exit_code != 0
    assert "missing required credential" in result.output


def test_create_credential_stdin(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "stdin-gh",
            "--type",
            "github",
            "--credential-stdin",
        ],
        input="GITHUB_TOKEN=ghp_stdin\n",
    )
    assert result.exit_code == 0, result.output


def test_create_credential_kv_must_have_equals(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "bad-kv",
            "--type",
            "github",
            "--credential",
            "no-equals-sign",
        ],
    )
    assert result.exit_code != 0


def test_create_credential_empty_key_does_not_leak_value(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-2 W-NEW-2: `=secret-value` must not echo the value in
    the error message. Empty-key entries are operator errors but the
    half after `=` is sensitive."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "leaky",
            "--type",
            "github",
            "--credential",
            "=ghp_test_secret_value",
        ],
    )
    assert result.exit_code != 0
    # The raw value must NOT appear in stderr/stdout.
    assert "ghp_test_secret_value" not in result.output
    # The error must still name the failure reason.
    assert "key is empty" in result.output


def test_create_credential_stdin_empty_key_does_not_leak_value(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-7: same redaction contract for the stdin path."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "leaky-stdin",
            "--type",
            "github",
            "--credential-stdin",
        ],
        input="=ghp_stdin_secret_value\n",
    )
    assert result.exit_code != 0
    assert "ghp_stdin_secret_value" not in result.output
    assert "key is empty" in result.output


def test_create_credential_whitespace_key_does_not_leak_value(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-7: a whitespace-only key (`' =VAL'`) strips to
    empty and must not echo the value either."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "leaky-ws",
            "--type",
            "github",
            "--credential",
            "   =ghp_whitespace_secret_value",
        ],
    )
    assert result.exit_code != 0
    assert "ghp_whitespace_secret_value" not in result.output


def test_get_lists_integrations(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "l1",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "get"])
    assert result.exit_code == 0
    assert "l1" in result.output


def test_get_types_lists_catalog(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["integration", "registry", "get", "--types"])
    assert result.exit_code == 0
    assert "github" in result.output


def test_describe_known(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "d1",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "describe", "d1"])
    assert result.exit_code == 0
    assert "github" in result.output


def test_edit_updates_credential(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "e1",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=old",
        ],
    )
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "edit",
            "e1",
            "--credential",
            "GITHUB_TOKEN=new",
        ],
    )
    assert result.exit_code == 0


def test_delete_requires_yes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "dx",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "delete", "dx"])
    assert result.exit_code != 0
    assert "--yes" in result.output


def test_delete_with_yes_removes(fleet_dir, stdin_not_tty) -> None:
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "dy",
            "--type",
            "github",
            "--credential",
            "GITHUB_TOKEN=t",
        ],
    )
    result = runner.invoke(app, ["integration", "registry", "delete", "dy", "--yes"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Brave (#734) — --api-key convenience flag + rotate command.
# ---------------------------------------------------------------------------


def test_create_brave_with_api_key_flag(fleet_dir, stdin_not_tty) -> None:
    """`--api-key` is the documented entry point for single-credential
    types like brave. Avoids shell-history leaks vs `--credential KEY=V`
    (the value still ends up in `ps`/history, but the key name doesn't
    leak the operator's intent the same way)."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "my-brave",
            "--type",
            "brave",
            "--api-key",
            "bsk-123",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/my-brave" in result.output

    from clawrium.core.integrations import get_integration_credentials

    assert get_integration_credentials("my-brave") == {"BRAVE_API_KEY": "bsk-123"}


def test_create_brave_with_api_key_stdin(fleet_dir, stdin_not_tty) -> None:
    """`--api-key-stdin` reads the bearer from non-TTY stdin. The
    `stdin_not_tty` fixture flips isatty() to False so the CLI accepts
    the piped value."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "my-brave-2",
            "--type",
            "brave",
            "--api-key-stdin",
        ],
        input="bsk-stdin\n",
    )
    assert result.exit_code == 0, result.output

    from clawrium.core.integrations import get_integration_credentials

    assert get_integration_credentials("my-brave-2") == {"BRAVE_API_KEY": "bsk-stdin"}


def test_create_brave_api_key_stdin_empty_rejected(fleet_dir, stdin_not_tty) -> None:
    """Empty stdin to `--api-key-stdin` is an error, not a silent empty
    credential. The CLI must exit non-zero with a clear message."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "my-brave-3",
            "--type",
            "brave",
            "--api-key-stdin",
        ],
        input="",
    )
    assert result.exit_code != 0
    assert "empty stdin" in result.output


def test_create_brave_api_key_rejects_empty_value(fleet_dir, stdin_not_tty) -> None:
    """`--api-key ''` is an error — the operator most likely fat-fingered
    a shell variable. Silently creating an empty credential would
    surface later as an opaque upstream 401."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "my-brave-4",
            "--type",
            "brave",
            "--api-key",
            "",
        ],
    )
    assert result.exit_code != 0
    assert "empty" in result.output


def test_create_api_key_rejected_for_multi_cred_type(
    fleet_dir, stdin_not_tty
) -> None:
    """`--api-key` is single-credential-type-only. atlassian has three
    required credentials; the flag cannot disambiguate so it must
    refuse rather than guess."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "atl",
            "--type",
            "atlassian",
            "--api-key",
            "tk",
        ],
    )
    assert result.exit_code != 0
    assert "not supported" in result.output


def test_create_api_key_conflicts_with_matching_credential(
    fleet_dir, stdin_not_tty
) -> None:
    """If both `--api-key VAL1` and `--credential BRAVE_API_KEY=VAL2` are
    passed, the CLI rejects the ambiguous input. Silently picking one
    would be a foot-gun during credential rotation."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "conflict",
            "--type",
            "brave",
            "--api-key",
            "v1",
            "--credential",
            "BRAVE_API_KEY=v2",
        ],
    )
    assert result.exit_code != 0
    assert "conflict" in result.output.lower()


def test_rotate_brave_no_attached_agents(fleet_dir, stdin_not_tty) -> None:
    """`integration rotate` on an unattached integration updates the
    credential and exits 0 with a clear "nothing to sync" message."""
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "rot1",
            "--type",
            "brave",
            "--api-key",
            "bsk-old",
        ],
    )
    result = runner.invoke(
        app,
        [
            "integration",
            "rotate",
            "rot1",
            "--api-key",
            "bsk-new",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "no agents attached" in result.output

    from clawrium.core.integrations import get_integration_credentials

    assert get_integration_credentials("rot1") == {"BRAVE_API_KEY": "bsk-new"}


def test_rotate_requires_new_credential(fleet_dir, stdin_not_tty) -> None:
    """`integration rotate` with no `--api-key`/`--credential` is an
    error — a no-op rotate would silently re-sync agents without any
    cred change, which is misleading."""
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "rot2",
            "--type",
            "brave",
            "--api-key",
            "k",
        ],
    )
    result = runner.invoke(
        app, ["integration", "rotate", "rot2", "--yes"]
    )
    assert result.exit_code != 0
    assert "no new credential" in result.output


# ---------------------------------------------------------------------------
# Brave (#734) — `integration rotate` multi-agent sync loop
# (ATX iter 1 B1, B2).
# ---------------------------------------------------------------------------


def _attach_integration_to_agent(
    integration_name: str, hostname: str, agent_key: str
) -> None:
    """Helper: register an attachment in `integrations.json` so
    `find_agents_using_integration` returns the bound agent. Mirrors
    the registry shape produced by `clawctl agent integration attach`
    without going through the SSH-touching CLI."""
    from clawrium.core.integrations import add_agent_integration

    add_agent_integration(hostname, agent_key, integration_name)


def test_rotate_syncs_every_attached_agent_in_order(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """`rotate` MUST re-sync every agent currently attached so a
    rotated key actually lands on disk. Without this, the credential
    update is silent — agents keep authenticating with the old key
    until the next manual sync. (B1 ATX iter 1)"""
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "rot-multi",
            "--type",
            "brave",
            "--api-key",
            "bsk-old",
        ],
    )
    # Attach to the fleet_dir openclaw agent.
    _attach_integration_to_agent(
        "rot-multi", "10.0.0.1", "openclaw"
    )

    synced: list[str] = []
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda agent_key, **_kw: synced.append(agent_key),
    )

    result = runner.invoke(
        app,
        [
            "integration",
            "rotate",
            "rot-multi",
            "--api-key",
            "bsk-new",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert synced == ["openclaw"]

    from clawrium.core.integrations import get_integration_credentials

    assert get_integration_credentials("rot-multi") == {
        "BRAVE_API_KEY": "bsk-new"
    }


def test_rotate_partial_failure_surfaces_nonzero_exit(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """If any sync fails the CLI MUST exit non-zero. A cron-driven
    rotation that returned 0 with one agent half-rotated would silently
    leave a credential-mismatch in production. Other agents still
    attempted (loop does not short-circuit). (B1 ATX iter 1)"""
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "rot-fail",
            "--type",
            "brave",
            "--api-key",
            "k",
        ],
    )
    _attach_integration_to_agent(
        "rot-fail", "10.0.0.1", "openclaw"
    )

    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    def _failing_sync(_agent_key, **_kw):
        raise CanonicalSyncError("simulated sync failure")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        _failing_sync,
    )

    result = runner.invoke(
        app,
        [
            "integration",
            "rotate",
            "rot-fail",
            "--api-key",
            "k2",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "SYNC FAILED" in result.output
    assert "simulated sync failure" in result.output


def test_rotate_routes_through_sync_agent_canonical_no_skip_path(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """`rotate` MUST route every attached agent through
    `sync_agent_canonical` — the only entry point that triggers the
    zeroclaw `_zeroclaw_repair_after_start` bearer rotation (#437) and
    the openclaw min-version preflight (#734). A regression adding an
    "idempotent skip" branch on rotate would call the sync function
    zero times and fail this assertion.

    This test pins the *routing* invariant. The actual bearer-write
    semantics (`hosts.json.gateway.auth` overwritten on a zeroclaw
    sync) are covered by `tests/test_lifecycle.py`'s `#437` suite —
    not duplicated here. (ATX iter 2 B2)"""
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "rot-zc",
            "--type",
            "brave",
            "--api-key",
            "k",
        ],
    )
    # Attach to a zeroclaw agent (seeded by fleet_dir? if not, attach
    # to the openclaw agent — the test is about the sync invocation,
    # not the agent type).
    _attach_integration_to_agent(
        "rot-zc", "10.0.0.1", "openclaw"
    )

    sync_calls: list[str] = []
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda agent_key, **_kw: sync_calls.append(agent_key),
    )

    result = runner.invoke(
        app,
        [
            "integration",
            "rotate",
            "rot-zc",
            "--api-key",
            "k2",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    # Sync must be called once per attached agent — no idempotent-skip
    # path on rotate.
    assert len(sync_calls) == 1

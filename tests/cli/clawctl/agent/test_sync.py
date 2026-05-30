"""Tests for `clawctl agent sync` — dry-run path covers the streaming
contract without hitting the canonical pipeline (which requires a real
SSH target). Bundle 5 wires the live wolf-i integration test.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_sync_dry_run_emits_phase_lines(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", "--dry-run"])
    assert result.exit_code == 0
    expected_phrases = [
        "validating local state",
        "pushing config",
        "restarting unit",
        "verifying health",
    ]
    for phrase in expected_phrases:
        assert phrase in result.output, f"missing phase line: {phrase}"
    # #560: canonical pipeline does not re-pair the gateway; that phase
    # is intentionally absent from the post-#560 contract.
    assert "re-pairing gateway" not in result.output
    assert "dry-run complete" in result.output


def test_sync_dry_run_json_emits_ndjson(fleet_dir) -> None:
    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "-o", "json"]
    )
    assert result.exit_code == 0
    lines = [line for line in result.output.strip().split("\n") if line.strip()]
    parsed = [json.loads(line) for line in lines]
    for event in parsed:
        assert event["resource"] == "agent/wise-hypatia"
        assert "phase" in event
        assert "state" in event


def test_sync_skip_validate_drops_phase_1(fleet_dir) -> None:
    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "--skip-validate"]
    )
    assert result.exit_code == 0
    assert "validating local state" not in result.output
    assert "pushing config" in result.output


def test_sync_workspace_skips_restart(fleet_dir) -> None:
    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "--workspace"]
    )
    assert result.exit_code == 0
    assert "restarting unit" not in result.output


# ---------------------------------------------------------------------------
# #560 regression guards: --canonical was dropped; re-introduction as a no-op
# should be caught.
# ---------------------------------------------------------------------------


def test_sync_rejects_removed_canonical_flag(fleet_dir) -> None:
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", "--canonical"])
    assert result.exit_code != 0
    assert "--canonical" in result.output


# ---------------------------------------------------------------------------
# #560 B5: error-path coverage for the only sync pipeline.
#
# `result.output` from CliRunner is the mixed stdout+stderr stream
# (Click 8.2+); `emit_error()` writes to stderr but content lands here.
# ---------------------------------------------------------------------------


def _patch_canonical(monkeypatch, exc) -> None:
    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", _raise
    )


class _StubResult:
    files_written: list[str] = []
    files_unchanged: list[str] = []


def _patch_canonical_capture(monkeypatch) -> dict:
    captured: dict = {}

    def _cap(name, **kwargs):
        captured["name"] = name
        captured.update(kwargs)
        return _StubResult()

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", _cap
    )
    return captured


def test_sync_rejects_removed_force_flag(fleet_dir) -> None:
    """#560 Phase 1: `--force` was dropped alongside `--canonical`.
    Recovery from `channel detach` is via re-attach, not a flag."""
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", "--force"])
    assert result.exit_code != 0
    assert "--force" in result.output


def test_sync_workspace_flag_disables_restart_and_verify(
    fleet_dir, monkeypatch
) -> None:
    captured = _patch_canonical_capture(monkeypatch)
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", "--workspace"])
    assert result.exit_code == 0, result.output
    assert captured.get("restart") is False
    assert captured.get("verify") is False


def test_sync_surfaces_secret_removal_refused(fleet_dir, monkeypatch) -> None:
    """#560: with `--force` removed, the recovery path is re-attach /
    `clawctl secret set`, not a flag. The error message must reflect that."""
    from clawrium.core.lifecycle_canonical import SecretRemovalRefused

    _patch_canonical(
        monkeypatch,
        SecretRemovalRefused(
            "refusing to sync 'wise-hypatia': rendered body removes "
            "host-side secrets (.zeroclaw/config.toml: would remove "
            "['DISCORD_BOT_TOKEN']). Recovery: re-attach the channel/"
            "integration that owns the missing secret, or restore it "
            "via `clawctl secret set ...`."
        ),
    )
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia"])
    assert result.exit_code != 0
    assert "refusing to sync" in result.output
    assert "re-attach" in result.output
    # Regression guard: the message must NOT recommend `--force`, which
    # was removed in #560.
    assert "--force" not in result.output


def test_sync_surfaces_canonical_sync_error(fleet_dir, monkeypatch) -> None:
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    _patch_canonical(monkeypatch, CanonicalSyncError("ssh probe failed"))
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia"])
    assert result.exit_code != 0
    assert "sync failed" in result.output
    assert "ssh probe failed" in result.output


def test_sync_surfaces_remote_read_error(fleet_dir, monkeypatch) -> None:
    from clawrium.core.render_diff import RemoteReadError

    _patch_canonical(monkeypatch, RemoteReadError("connection refused"))
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia"])
    assert result.exit_code != 0
    assert "sync failed" in result.output
    assert "connection refused" in result.output


def test_sync_surfaces_agent_config_error(fleet_dir, monkeypatch) -> None:
    from clawrium.core.render import AgentConfigError

    _patch_canonical(monkeypatch, AgentConfigError("no provider attached"))
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia"])
    assert result.exit_code != 0
    assert "sync failed" in result.output
    assert "no provider attached" in result.output


# ---------------------------------------------------------------------------
# #560 ATX round 3: B1+B2 unit tests on `sync_agent_canonical` directly.
# ---------------------------------------------------------------------------


def test_canonical_sync_advances_state_to_ready(monkeypatch, fleet_dir) -> None:
    """B2: a successful canonical sync must call transition_state(READY)."""
    from clawrium.core import lifecycle_canonical
    from clawrium.core.render import RenderInputs, ProviderInputs
    from clawrium.core.render_diff import FileDiff

    captured: dict = {}

    def fake_build(name):
        return RenderInputs(
            agent_type="openclaw",
            agent_name=name,
            provider=ProviderInputs(
                name="p", type="ollama", endpoint="", default_model="x"
            ),
        )

    def fake_render(inputs):
        from clawrium.core.render import RenderedFiles

        return RenderedFiles(files={".openclaw/.env": "OPENROUTER_API_KEY=k\n"})

    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", fake_build)
    monkeypatch.setattr(
        lifecycle_canonical, "_RENDERERS", {"openclaw": fake_render}
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda n: ({"hostname": "test-host"}, n, {"type": "openclaw"}),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "diff_files",
        lambda **kw: [
            FileDiff(
                path=".openclaw/.env",
                remote_path="/home/x/.openclaw/.env",
                rendered_body="OPENROUTER_API_KEY=k\n",
                remote_body="",
                remote_present=False,
                unified_diff="+OPENROUTER_API_KEY=k\n",
            )
        ],
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_open_ssh", lambda host, timeout=15: MagicMock()
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "_atomic_write",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_restart_unit", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_verify_health", lambda *a, **kw: None
    )

    def fake_transition(host, agent_key, to_state):
        captured["host"] = host
        captured["agent_key"] = agent_key
        captured["to_state"] = to_state
        return True

    from clawrium.core import onboarding as onboarding_mod

    monkeypatch.setattr(onboarding_mod, "transition_state", fake_transition)

    lifecycle_canonical.sync_agent_canonical("test-agent")
    assert captured.get("to_state") is not None
    assert captured["to_state"].value == "ready"


def test_canonical_sync_repairs_zeroclaw_gateway(monkeypatch, fleet_dir) -> None:
    """B1: a successful canonical sync of a zeroclaw must re-pair the
    gateway bearer (#437) via _zeroclaw_repair_after_start."""
    from clawrium.core import lifecycle_canonical
    from clawrium.core.render import RenderInputs, ProviderInputs
    from clawrium.core.render_diff import FileDiff

    captured: dict = {}

    def fake_build(name):
        return RenderInputs(
            agent_type="zeroclaw",
            agent_name=name,
            provider=ProviderInputs(
                name="p", type="anthropic", endpoint="", default_model="x"
            ),
        )

    def fake_render(inputs):
        from clawrium.core.render import RenderedFiles

        return RenderedFiles(files={".zeroclaw/config.toml": "[gateway]\n"})

    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", fake_build)
    monkeypatch.setattr(
        lifecycle_canonical, "_RENDERERS", {"zeroclaw": fake_render}
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda n: ({"hostname": "test-host"}, n, {"type": "zeroclaw"}),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "diff_files",
        lambda **kw: [
            FileDiff(
                path=".zeroclaw/config.toml",
                remote_path="/home/x/.zeroclaw/config.toml",
                rendered_body="[gateway]\n",
                remote_body="",
                remote_present=False,
                unified_diff="+[gateway]\n",
            )
        ],
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_open_ssh", lambda host, timeout=15: MagicMock()
    )
    monkeypatch.setattr(lifecycle_canonical, "_atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr(lifecycle_canonical, "_restart_unit", lambda *a, **kw: None)
    monkeypatch.setattr(lifecycle_canonical, "_verify_health", lambda *a, **kw: None)

    def fake_repair(hostname, *, agent_name, on_event, reason):
        captured["repair_hostname"] = hostname
        captured["repair_agent"] = agent_name
        captured["repair_reason"] = reason
        return True, None

    from clawrium.core import lifecycle as lifecycle_mod

    monkeypatch.setattr(
        lifecycle_mod, "_zeroclaw_repair_after_start", fake_repair
    )
    from clawrium.core import onboarding as onboarding_mod

    monkeypatch.setattr(onboarding_mod, "transition_state", lambda *a, **kw: True)

    lifecycle_canonical.sync_agent_canonical("test-agent")
    assert captured.get("repair_reason") == "sync"
    assert captured.get("repair_agent") == "test-agent"


def test_canonical_sync_propagates_repair_failure(monkeypatch, fleet_dir) -> None:
    """B1: if `_zeroclaw_repair_after_start` returns failure, the canonical
    sync must raise CanonicalSyncError (no silent write of stale bearer)."""
    from clawrium.core import lifecycle_canonical
    from clawrium.core.render import RenderInputs, ProviderInputs
    from clawrium.core.render_diff import FileDiff
    import pytest as _pytest

    def fake_build(name):
        return RenderInputs(
            agent_type="zeroclaw",
            agent_name=name,
            provider=ProviderInputs(
                name="p", type="anthropic", endpoint="", default_model="x"
            ),
        )

    def fake_render(inputs):
        from clawrium.core.render import RenderedFiles

        return RenderedFiles(files={".zeroclaw/config.toml": "[gateway]\n"})

    monkeypatch.setattr(lifecycle_canonical, "build_render_inputs", fake_build)
    monkeypatch.setattr(
        lifecycle_canonical, "_RENDERERS", {"zeroclaw": fake_render}
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "get_agent_by_name",
        lambda n: ({"hostname": "test-host"}, n, {"type": "zeroclaw"}),
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "diff_files",
        lambda **kw: [
            FileDiff(
                path=".zeroclaw/config.toml",
                remote_path="/home/x/.zeroclaw/config.toml",
                rendered_body="[gateway]\n",
                remote_body="",
                remote_present=False,
                unified_diff="+[gateway]\n",
            )
        ],
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_open_ssh", lambda host, timeout=15: MagicMock()
    )
    monkeypatch.setattr(lifecycle_canonical, "_atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr(lifecycle_canonical, "_restart_unit", lambda *a, **kw: None)
    monkeypatch.setattr(lifecycle_canonical, "_verify_health", lambda *a, **kw: None)

    from clawrium.core import lifecycle as lifecycle_mod

    monkeypatch.setattr(
        lifecycle_mod,
        "_zeroclaw_repair_after_start",
        lambda hostname, *, agent_name, on_event, reason: (False, "pair playbook failed"),
    )

    with _pytest.raises(lifecycle_canonical.CanonicalSyncError) as excinfo:
        lifecycle_canonical.sync_agent_canonical("test-agent")
    assert "re-pair failed" in str(excinfo.value)


def test_sync_renders_gateway_token_rotated_as_yellow_notice(
    fleet_dir, monkeypatch
) -> None:
    """AGENTS.md §Gateway Token Lifecycle: `clawctl agent sync` must
    surface the `gateway_token_rotated` event as a yellow notice so
    operators see when remote chat sessions need to reconnect."""
    import json as _json

    def fake_sync(name, *, force, restart, verify, on_event):
        on_event(
            "gateway_token_rotated",
            _json.dumps(
                {
                    "agent_key": "wise-hypatia",
                    "old_prefix": "abc",
                    "new_prefix": "def",
                    "reason": "sync",
                }
            ),
        )

        class _R:
            files_written = [".zeroclaw/config.toml"]
            files_unchanged: list[str] = []

        return _R()

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical", fake_sync
    )
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia"])
    assert result.exit_code == 0, result.output
    assert "Gateway token rotated" in result.output
    assert "wise-hypatia" in result.output


def test_open_ssh_translates_bad_host_key_to_canonical_error(monkeypatch) -> None:
    """B3: paramiko's BadHostKeyException (MITM signal) is translated into
    a CanonicalSyncError with a remediation message — NOT swallowed."""
    import paramiko
    from clawrium.core import lifecycle_canonical
    import pytest as _pytest

    def boom(*args, **kwargs):
        raise paramiko.BadHostKeyException(
            "wolf-i", paramiko.RSAKey.generate(1024), paramiko.RSAKey.generate(1024)
        )

    fake_client = MagicMock()
    fake_client.connect.side_effect = boom
    monkeypatch.setattr(paramiko, "SSHClient", lambda: fake_client)
    monkeypatch.setattr(
        lifecycle_canonical, "get_host_private_key", lambda key_id: "/tmp/k"
    )

    with _pytest.raises(lifecycle_canonical.CanonicalSyncError) as excinfo:
        lifecycle_canonical._open_ssh(
            {"hostname": "wolf-i", "key_id": "wolf-i", "user": "xclm"}
        )
    msg = str(excinfo.value)
    assert "host key" in msg
    assert "MITM" in msg or "clawctl host create" in msg

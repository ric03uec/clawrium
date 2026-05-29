"""Tests for `clawctl agent sync --dry-run --diff` — F8 of parent #555.

The diff path is wired through `core/render_diff.py` which talks to
paramiko; tests patch the renderer and inject a fake remote reader so
no SSH connection is opened.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.render import (
    ProviderInputs,
    RenderInputs,
    RenderedFiles,
)


runner = CliRunner()


_INPUTS = RenderInputs(
    agent_name="wise-hypatia",
    agent_type="openclaw",
    provider=ProviderInputs(
        name="anthropic-primary",
        type="anthropic",
        default_model="claude-opus",
        api_key="sk-xxx",
    ),
)
_RENDERED = RenderedFiles(
    files={
        ".openclaw/.env": "ANTHROPIC_API_KEY='sk-xxx'\nOPENCLAW_DEFAULT_MODEL='claude-opus'\n",
    }
)


def _patch_render(monkeypatch) -> None:
    from clawrium.cli.clawctl.agent import sync as sync_mod
    from clawrium.core import render as render_mod

    monkeypatch.setattr(sync_mod, "_RENDERERS", {"openclaw": "render_openclaw"})
    monkeypatch.setattr(render_mod, "render_openclaw", lambda inputs: _RENDERED)
    # build_render_inputs is imported inside _emit_diff via deferred
    # import; patch the source module so the import resolves to our stub.
    monkeypatch.setattr(render_mod, "build_render_inputs", lambda name: _INPUTS)


def _patch_reader(monkeypatch, body: str, present: bool = True) -> None:
    """Replace `diff_files`'s `reader` default by patching the helper."""
    from clawrium.core import render_diff

    def fake_reader(**kwargs):
        return present, body

    # Patch the SSH key lookup so diff_files doesn't refuse early.
    monkeypatch.setattr(render_diff, "get_host_private_key", lambda key_id: Path("/dev/null"))
    monkeypatch.setattr(render_diff, "read_remote_file", fake_reader)


def test_diff_implies_dry_run(fleet_dir, monkeypatch) -> None:
    _patch_render(monkeypatch)
    _patch_reader(monkeypatch, body=_RENDERED.files[".openclaw/.env"])

    # No --dry-run flag: --diff must imply it (no host write).
    result = runner.invoke(app, ["agent", "sync", "wise-hypatia", "--diff"])
    assert result.exit_code == 0, result.output
    assert "dry-run complete" in result.output


def test_diff_no_changes_reports_no_changes(fleet_dir, monkeypatch) -> None:
    _patch_render(monkeypatch)
    # Remote == rendered → empty unified diff.
    _patch_reader(monkeypatch, body=_RENDERED.files[".openclaw/.env"])

    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "--diff"]
    )
    assert result.exit_code == 0, result.output
    assert "diff .openclaw/.env: no changes" in result.output


def test_diff_would_change_emits_unified_patch(fleet_dir, monkeypatch) -> None:
    _patch_render(monkeypatch)
    _patch_reader(
        monkeypatch,
        body="ANTHROPIC_API_KEY='old-key'\nOPENCLAW_DEFAULT_MODEL='claude-opus'\n",
    )

    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "--diff"]
    )
    assert result.exit_code == 0, result.output
    assert "would change" in result.output
    # Unified diff markers must appear verbatim.
    assert "--- host:/home/wise-hypatia/.openclaw/.env" in result.output
    assert "+++ rendered:.openclaw/.env" in result.output
    assert "-ANTHROPIC_API_KEY='old-key'" in result.output
    assert "+ANTHROPIC_API_KEY='sk-xxx'" in result.output


def test_diff_would_create_when_remote_missing(fleet_dir, monkeypatch) -> None:
    _patch_render(monkeypatch)
    _patch_reader(monkeypatch, body="", present=False)

    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "--diff"]
    )
    assert result.exit_code == 0, result.output
    assert "would create" in result.output


def test_diff_json_output(fleet_dir, monkeypatch) -> None:
    _patch_render(monkeypatch)
    _patch_reader(
        monkeypatch,
        body="ANTHROPIC_API_KEY='old-key'\nOPENCLAW_DEFAULT_MODEL='claude-opus'\n",
    )

    result = runner.invoke(
        app,
        ["agent", "sync", "wise-hypatia", "--dry-run", "--diff", "-o", "json"],
    )
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.output.strip().splitlines() if line]
    diff_events = [e for e in events if e.get("phase") == "diff"]
    assert diff_events, "expected at least one diff event"
    assert any(e["state"] == "result" for e in diff_events)
    result_event = next(e for e in diff_events if e["state"] == "result")
    assert result_event["path"] == ".openclaw/.env"
    assert result_event["changed"] is True
    assert result_event["remote_present"] is True
    assert "ANTHROPIC_API_KEY" in result_event["diff"]


def test_diff_render_error_surfaces_cleanly(fleet_dir, monkeypatch) -> None:
    from clawrium.cli.clawctl.agent import sync as sync_mod
    from clawrium.core import render as render_mod
    from clawrium.core.render import AgentConfigError

    monkeypatch.setattr(sync_mod, "_RENDERERS", {"openclaw": "render_openclaw"})

    def _raise(name: str):
        raise AgentConfigError("provider 'foo' not registered")

    monkeypatch.setattr(render_mod, "build_render_inputs", _raise)

    result = runner.invoke(
        app, ["agent", "sync", "wise-hypatia", "--dry-run", "--diff"]
    )
    # Diagnostic must not crash the session; sync still exits 0 in
    # dry-run mode, the failure surfaces as a diff-error line.
    assert result.exit_code == 0, result.output
    assert "diff error" in result.output
    assert "provider 'foo'" in result.output

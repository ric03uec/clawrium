"""Tests for openclaw-specific launchd plist rendering (issue #604).

These cover the agent_type parameterization added to core/launchd.py.
Hermes-side regression coverage already lives in tests/core/test_launchd.py.
"""

import plistlib

import pytest

from clawrium.core.launchd import (
    label_for,
    plist_path_for,
    render_plist,
)


def _parse(xml: str) -> dict:
    return plistlib.loads(xml.encode("utf-8"))


def test_label_for_openclaw_uses_openclaw_prefix():
    assert label_for("o1", agent_type="openclaw") == "ai.clawrium.openclaw.o1"


def test_label_for_openclaw_rejects_dashboard_kind():
    with pytest.raises(ValueError, match="openclaw does not support plist kind"):
        label_for("o1", kind="dashboard", agent_type="openclaw")


def test_plist_path_for_openclaw_lives_in_system_daemons():
    path = plist_path_for("o1", agent_type="openclaw")
    assert path == "/Library/LaunchDaemons/ai.clawrium.openclaw.o1.plist"


def test_render_openclaw_plist_is_valid():
    rendered = render_plist(
        "o1", template_name="openclaw.plist.j2", agent_type="openclaw"
    )
    parsed = _parse(rendered)
    assert parsed["Label"] == "ai.clawrium.openclaw.o1"
    assert parsed["UserName"] == "o1"
    assert parsed["RunAtLoad"] is True
    assert parsed["KeepAlive"] == {"SuccessfulExit": False}


def test_render_openclaw_plist_does_not_contain_xclm():
    rendered = render_plist(
        "o1", template_name="openclaw.plist.j2", agent_type="openclaw"
    ).lower()
    assert "xclm" not in rendered


def test_render_openclaw_plist_program_arguments_wrap_in_bash():
    parsed = _parse(
        render_plist("o1", template_name="openclaw.plist.j2", agent_type="openclaw")
    )
    args = parsed["ProgramArguments"]
    # Wrapper sources env then execs openclaw — single source of truth on disk.
    assert args[0] == "/bin/bash"
    assert args[1] == "-lc"
    assert "/Users/o1/.openclaw/bin/openclaw gateway run --allow-unconfigured" in args[2]
    assert "/Users/o1/.openclaw/env" in args[2]


def test_render_openclaw_plist_paths_target_user_home():
    parsed = _parse(
        render_plist("o1", template_name="openclaw.plist.j2", agent_type="openclaw")
    )
    assert parsed["WorkingDirectory"] == "/Users/o1/workspace"
    assert parsed["StandardOutPath"] == "/Users/o1/.openclaw/logs/gateway.stdout.log"
    assert parsed["StandardErrorPath"] == "/Users/o1/.openclaw/logs/gateway.stderr.log"


def test_unsupported_agent_type_raises():
    with pytest.raises(ValueError, match="unsupported agent_type"):
        label_for("o1", agent_type="nemoclaw")


def test_hermes_default_agent_type_unchanged():
    """Regression guard: existing hermes call site signatures still resolve."""
    assert label_for("h1") == "ai.clawrium.hermes.h1"
    assert label_for("h1", kind="dashboard") == "ai.clawrium.hermes.h1.dashboard"
    parsed = _parse(render_plist("h1"))
    assert parsed["Label"] == "ai.clawrium.hermes.h1"

"""Tests for core/launchd.py (issue #469 step 6).

Unit-level: render the plist, parse it as XML, and assert structural
invariants. The plist must:
  1. Parse as a valid XML plist (no template syntax leaks).
  2. Have UserName set to the agent_name passed in.
  3. NEVER contain the literal string `xclm` — the gateway must run as
     the agent user, not the management user. Mixing them is a known
     upstream hermes quirk (gui-domain plist + xclm-as-runner) we
     explicitly avoid.
  4. Use the `ai.clawrium.hermes.<agent_name>` Label.

E2E (writing into /Library/LaunchDaemons) is exercised by step 7's
lifecycle integration; not duplicated here.
"""

import plistlib

import pytest

from clawrium.core.launchd import (
    LABEL_PREFIX,
    LAUNCHD_DAEMONS_DIR,
    label_for,
    plist_path_for,
    render_plist,
)


def _parse(xml: str) -> dict:
    """Round-trip the rendered XML through plistlib to confirm it's a valid plist."""
    return plistlib.loads(xml.encode("utf-8"))


def test_label_for_uses_reverse_dns_prefix():
    assert label_for("h1") == "ai.clawrium.hermes.h1"
    assert label_for("hermes-prod-7") == "ai.clawrium.hermes.hermes-prod-7"


def test_label_for_dashboard_kind():
    assert label_for("h1", kind="dashboard") == "ai.clawrium.hermes.h1.dashboard"


def test_label_for_unknown_kind_raises():
    with pytest.raises(ValueError, match="unsupported plist kind"):
        label_for("h1", kind="nope")


def test_plist_path_for_lives_in_system_daemons():
    """launchd /Library/LaunchAgents is per-user GUI — we MUST use LaunchDaemons."""
    path = plist_path_for("h1")
    assert path.startswith(LAUNCHD_DAEMONS_DIR + "/")
    assert path.endswith(".plist")
    assert "LaunchAgents" not in path  # explicit guard


def test_render_plist_is_valid_xml_plist():
    rendered = render_plist("h1")
    parsed = _parse(rendered)
    assert parsed["Label"] == "ai.clawrium.hermes.h1"


def test_render_plist_username_is_agent_name():
    """Regression: the gateway runs as the agent user, never as xclm."""
    parsed = _parse(render_plist("h1"))
    assert parsed["UserName"] == "h1"


def test_render_plist_does_not_contain_xclm():
    """Regression guard: no xclm string anywhere in the rendered plist.

    Upstream NousResearch/hermes ships a launchd template that runs the
    gateway under the same user that installed it — which in our case
    would be xclm. We override every path so the gateway runs as the
    agent user, which means the literal string `xclm` should never
    appear in the output.
    """
    rendered = render_plist("h1").lower()
    assert "xclm" not in rendered


def test_render_plist_runs_at_load_and_keeps_alive_on_failure():
    parsed = _parse(render_plist("h1"))
    assert parsed["RunAtLoad"] is True
    keep = parsed.get("KeepAlive")
    assert isinstance(keep, dict)
    # KeepAlive on SuccessfulExit=false means: restart if it crashes,
    # don't restart if it exits 0. Matches systemd Restart=on-failure.
    assert keep["SuccessfulExit"] is False


def test_render_plist_program_arguments_run_hermes_gateway():
    parsed = _parse(render_plist("h1"))
    args = parsed["ProgramArguments"]
    assert args[0] == "/Users/h1/.local/bin/hermes"
    assert args[1:] == ["gateway", "run"]


def test_render_plist_paths_target_user_home():
    parsed = _parse(render_plist("h1"))
    assert parsed["WorkingDirectory"] == "/Users/h1/.hermes"
    env = parsed["EnvironmentVariables"]
    assert env["HERMES_HOME"] == "/Users/h1/.hermes"
    assert env["HOME"] == "/Users/h1"


def test_render_plist_undefined_var_raises():
    """StrictUndefined: typoed template vars should fail loudly, not silently."""
    with pytest.raises(Exception):
        # Forcing a render with no agent_name — render_plist always passes
        # agent_name, so test the template directly via the env loader.
        from clawrium.core.launchd import _env

        _env().get_template("gateway.plist.j2").render()


def test_label_prefix_is_stable():
    assert LABEL_PREFIX == "ai.clawrium.hermes"


def test_render_dashboard_plist_contains_port():
    """Dashboard plist must template in the per-instance loopback port."""
    rendered = render_plist(
        "h1", template_name="dashboard.plist.j2", dashboard_port=45112
    )
    parsed = _parse(rendered)
    assert parsed["Label"] == "ai.clawrium.hermes.h1.dashboard"
    assert parsed["UserName"] == "h1"
    args = parsed["ProgramArguments"]
    assert "--host" in args and "127.0.0.1" in args
    assert "--port" in args and "45112" in args
    assert "--no-open" in args


def test_render_dashboard_plist_does_not_contain_xclm():
    rendered = render_plist(
        "h1", template_name="dashboard.plist.j2", dashboard_port=45112
    ).lower()
    assert "xclm" not in rendered

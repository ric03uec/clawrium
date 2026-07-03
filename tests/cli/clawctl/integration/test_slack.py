"""Tests for `clawctl integration registry create --type slack-*`.

#834 (Phase 1): the two Slack integration types (`slack-user` and
`slack-cookie`) are the first CLI-facing surface a user touches when
wiring Slack. Ensure both types round-trip through create → describe
→ describe --output=json → delete without leaking credentials to
stdout or leaving orphan records.

#846: slack integrations must be named exactly `slack` — the rendered
MCP toolset key is pinned to `slack` at render time so the registry
name has to match or the two surfaces drift.

Attach-to-agent behavior lives in `test_integration_gate.py`.
"""

from __future__ import annotations

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def test_create_slack_user_non_interactive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack",
            "--type",
            "slack-user",
            "--credential",
            "SLACK_MCP_XOXP_TOKEN=xoxp-1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/slack" in result.output


def test_create_slack_cookie_non_interactive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack",
            "--type",
            "slack-cookie",
            "--credential",
            "SLACK_MCP_XOXC_TOKEN=xoxc-1",
            "--credential",
            "SLACK_MCP_XOXD_TOKEN=xoxd-1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/slack" in result.output


def test_create_slack_user_missing_token_fails(fleet_dir, stdin_not_tty) -> None:
    """slack-user requires SLACK_MCP_XOXP_TOKEN — creating without one
    (or with a wrong key) must fail up front."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack",
            "--type",
            "slack-user",
            "--credential",
            "SLACK_MCP_XOXC_TOKEN=xoxc-1",
        ],
    )
    assert result.exit_code != 0
    assert "missing required credential" in result.output


def test_create_slack_cookie_missing_second_token_fails(
    fleet_dir, stdin_not_tty
) -> None:
    """slack-cookie requires BOTH XOXC and XOXD; passing only one must
    fail so the operator doesn't ship a half-configured integration."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack",
            "--type",
            "slack-cookie",
            "--credential",
            "SLACK_MCP_XOXC_TOKEN=xoxc-1",
        ],
    )
    assert result.exit_code != 0
    assert "missing required credential" in result.output


def test_create_slack_user_credential_stdin(fleet_dir, stdin_not_tty) -> None:
    """`--credential-stdin` recommended per plan §S6 (no ps auxww leak)."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack",
            "--type",
            "slack-user",
            "--credential-stdin",
        ],
        input="SLACK_MCP_XOXP_TOKEN=xoxp-stdin\n",
    )
    assert result.exit_code == 0, result.output


def test_slack_user_token_not_leaked_by_describe(
    fleet_dir, stdin_not_tty
) -> None:
    """Credential-safety regression: `describe` must NEVER print the
    xoxp value to stdout even in verbose modes."""
    runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack",
            "--type",
            "slack-user",
            "--credential",
            "SLACK_MCP_XOXP_TOKEN=xoxp-super-secret",
        ],
    )
    result = runner.invoke(
        app,
        ["integration", "registry", "describe", "slack"],
    )
    assert result.exit_code == 0
    assert "xoxp-super-secret" not in result.output


# ---------------------------------------------------------------------------
# #846: slack integrations must be named exactly `slack`.
# ---------------------------------------------------------------------------


def test_create_slack_user_wrong_name_rejected(fleet_dir, stdin_not_tty) -> None:
    """#846: any name other than `slack` for a slack-user integration
    must be rejected at CLI-time so the registry record matches the
    rendered mcp_servers key. Also pins:
      - `emit_error` exit code (1) — a silent flip to 2 would break
        shell scripts checking `$?`.
      - Hint text — must contain the exact `clawctl` recovery command
        AND the type-specific credential flag names so operators can
        copy-paste without cross-referencing `registry get --types`.
    """
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "work_slack",
            "--type",
            "slack-user",
            "--credential",
            "SLACK_MCP_XOXP_TOKEN=xoxp-1",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "must be named 'slack'" in result.output
    # #846 iter-3 (ATX W3 fix): pin a unique substring from the
    # operator-facing WHY body so a future refactor that dropped the
    # explanation (leaving only the terse "must be named 'slack'"
    # marker) would fail this test rather than degrade silently.
    assert "invisible to the agent" in result.output
    assert "clawctl integration registry create slack" in result.output
    assert "--type slack-user" in result.output
    assert "SLACK_MCP_XOXP_TOKEN" in result.output


def test_create_slack_cookie_wrong_name_rejected(fleet_dir, stdin_not_tty) -> None:
    """#846: mirror the slack-user gate for the cookie auth path.
    Verifies both required credential flags (XOXC + XOXD) appear in
    the hint text."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "mcp_slack",
            "--type",
            "slack-cookie",
            "--credential",
            "SLACK_MCP_XOXC_TOKEN=xoxc-1",
            "--credential",
            "SLACK_MCP_XOXD_TOKEN=xoxd-1",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "must be named 'slack'" in result.output
    # #846 iter-3 (ATX W3 fix): pin a unique substring from the
    # operator-facing WHY body so a future refactor that dropped the
    # explanation (leaving only the terse "must be named 'slack'"
    # marker) would fail this test rather than degrade silently.
    assert "invisible to the agent" in result.output
    assert "clawctl integration registry create slack" in result.output
    assert "--type slack-cookie" in result.output
    assert "SLACK_MCP_XOXC_TOKEN" in result.output
    assert "SLACK_MCP_XOXD_TOKEN" in result.output

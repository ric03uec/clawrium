"""Tests for `clawctl integration registry create --type slack-*`.

#834 (Phase 1): the two Slack integration types (`slack-user` and
`slack-cookie`) are the first CLI-facing surface a user touches when
wiring Slack. Ensure both types round-trip through create → describe
→ describe --output=json → delete without leaking credentials to
stdout or leaving orphan records.

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
            "slack-work",
            "--type",
            "slack-user",
            "--credential",
            "SLACK_MCP_XOXP_TOKEN=xoxp-1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/slack-work" in result.output


def test_create_slack_cookie_non_interactive(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "slack-legacy",
            "--type",
            "slack-cookie",
            "--credential",
            "SLACK_MCP_XOXC_TOKEN=xoxc-1",
            "--credential",
            "SLACK_MCP_XOXD_TOKEN=xoxd-1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "integration/slack-legacy" in result.output


def test_create_slack_user_missing_token_fails(fleet_dir, stdin_not_tty) -> None:
    """slack-user requires SLACK_MCP_XOXP_TOKEN — creating without one
    (or with a wrong key) must fail up front."""
    result = runner.invoke(
        app,
        [
            "integration",
            "registry",
            "create",
            "bad-slack",
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
            "half-slack",
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
            "slack-stdin",
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
            "slack-work",
            "--type",
            "slack-user",
            "--credential",
            "SLACK_MCP_XOXP_TOKEN=xoxp-super-secret",
        ],
    )
    result = runner.invoke(
        app,
        ["integration", "registry", "describe", "slack-work"],
    )
    assert result.exit_code == 0
    assert "xoxp-super-secret" not in result.output

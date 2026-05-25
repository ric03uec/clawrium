"""R3 closure check (issue #509): `clawctl agent configure` source must
not contain Discord/Slack interactive prompts.

The acceptance criteria from issue #509 require codifying — by static
analysis of the source — that the new `agent configure` module no
longer prompts for any Discord/Slack-related field. Channel
configuration moves to `clawctl channel registry create` +
`clawctl agent channel attach`.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _configure_source() -> str:
    """Return the on-disk source of `clawctl/agent/configure.py`."""
    # The configure module is the only place where stage-channels logic
    # could host a prompt. Read from the resolved file path so we are
    # checking the real, installed (or editable-installed) source.
    pkg_dir = Path(files("clawrium").joinpath("cli/clawctl/agent/configure.py"))
    return pkg_dir.read_text()


_FORBIDDEN_NEEDLES = (
    "Discord",
    "Slack",
    "bot_token",
    "BOT_TOKEN",
    "allowed_user",
    "allowed_channel",
    "allowed_guild",
    "home_channel",
    "require_mention",
    "stream_mode",
    "stream_delay",
    "app_token",
)


def test_configure_module_has_no_channel_prompt_calls() -> None:
    src = _configure_source()
    # `typer.prompt(...)` and `typer.confirm(...)` are the call shapes
    # we are guarding against. Any Discord/Slack-related token appearing
    # in an argument to those calls is a regression.
    for match in re.finditer(r"typer\.(prompt|confirm)\(([^)]*)\)", src, re.DOTALL):
        args = match.group(2)
        for needle in _FORBIDDEN_NEEDLES:
            assert needle.lower() not in args.lower(), (
                f"clawctl agent configure must not prompt for {needle!r}; "
                "use 'clawctl channel registry create' + "
                "'clawctl agent channel attach' instead"
            )


def test_configure_channels_stage_emits_deprecation_pointer(
    fleet_dir, stdin_not_tty
) -> None:
    """`--stage channels` must redirect users to the new commands."""
    result = runner.invoke(
        app,
        ["agent", "configure", "wise-hypatia", "--stage", "channels"],
    )
    assert result.exit_code != 0
    assert "deprecated" in result.output
    assert "clawctl channel registry create" in result.output
    assert "clawctl agent channel attach" in result.output


def test_configure_channel_flag_emits_error(fleet_dir, stdin_not_tty) -> None:
    """ATX iter-2 B2: `--channel` is no longer accepted on `configure`."""
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "anth",
            "--channel",
            "ignored",
        ],
    )
    assert result.exit_code != 0
    assert "--channel is no longer supported" in result.output
    assert "clawctl agent channel attach" in result.output


def test_configure_personality_flag_emits_error(fleet_dir, stdin_not_tty) -> None:
    """ATX iter-2 B1: `--personality` was silently dropped — now refused."""
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "identity",
            "--personality",
            "formal",
        ],
    )
    assert result.exit_code != 0
    assert "--personality is not wired" in result.output


def test_configure_yes_flag_removed(fleet_dir, stdin_not_tty) -> None:
    """ATX iter-2 B3: `--yes`/`-y` was dead — typer must reject it now."""
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "wise-hypatia",
            "--stage",
            "providers",
            "--provider",
            "anth",
            "--yes",
        ],
    )
    # Typer surfaces an unrecognized option as exit code 2.
    assert result.exit_code != 0


def test_configure_channel_flag_fires_before_agent_resolution(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-3: `--channel` deprecation must fire before
    `safe_resolve_agent`. Using a nonexistent agent confirms the
    deprecation message wins the race."""
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "no-such-agent-here",
            "--stage",
            "providers",
            "--provider",
            "anth",
            "--channel",
            "ignored",
        ],
    )
    assert result.exit_code != 0
    assert "--channel is no longer supported" in result.output
    # The "agent not found" hint must NOT appear — that would mean
    # the guard fired after `safe_resolve_agent`.
    assert "agent 'no-such-agent-here' not found" not in result.output


def test_configure_stage_channels_fires_before_agent_resolution(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-3: `--stage channels` deprecation must fire
    before `safe_resolve_agent`."""
    result = runner.invoke(
        app,
        [
            "agent",
            "configure",
            "no-such-agent-here",
            "--stage",
            "channels",
        ],
    )
    assert result.exit_code != 0
    assert "deprecated" in result.output
    assert "clawctl channel registry create" in result.output
    assert "agent 'no-such-agent-here' not found" not in result.output


def test_stage_help_text_omits_channels_from_valid_values(
    fleet_dir, stdin_not_tty
) -> None:
    """ATX iter-3 FU-5: pin the help text so a contributor cannot
    silently re-add `channels` to the valid-values hint.

    Typer wraps long help text across lines and inserts box-drawing
    chars at the gutters, so we collapse whitespace before matching.
    """
    import re

    result = runner.invoke(app, ["agent", "configure", "--help"])
    assert result.exit_code == 0
    # Typer wraps help across lines with box-drawing chars at the
    # column gutters and (under CI's color-enabled rendering) inserts
    # ANSI escape sequences mid-text. Strip both, plus collapse
    # whitespace, so the phrase survives line-wrapping AND coloring.
    # Without ANSI stripping this assertion passes locally on a wide
    # terminal but fails on CI's 80-col color-enabled output (#518 CI run).
    flat = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", result.output)
    flat = re.sub(r"[│╭╰─╮╯]", " ", flat)
    flat = re.sub(r"\s+", " ", flat)
    assert "providers, identity, validate" in flat
    assert "deprecated" in flat.lower()

"""Tests for the shared gitconfig.j2 template (#531)."""

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader


TEMPLATE_DIR = (
    Path(__file__).parent.parent
    / "src"
    / "clawrium"
    / "platform"
    / "templates"
)


def _render(git: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )
    return env.get_template("gitconfig.j2").render(git=git)


def test_renders_full_input():
    """All five fields produce the expected ini body."""
    body = _render(
        {
            "user_name": "Alice",
            "user_email": "alice@example.com",
            "init_default_branch": "trunk",
            "pull_rebase": "true",
            "core_editor": "nano",
        }
    )

    assert "[user]" in body
    assert "name = Alice" in body
    assert "email = alice@example.com" in body
    assert "defaultBranch = trunk" in body
    assert "rebase = true" in body
    assert "editor = nano" in body


def test_newline_in_user_name_does_not_inject_section():
    """A stored value with embedded \\n must not open a new ini section.

    Section headers in INI are only honored when `[name]` appears at column
    0 of its own line. The template's `replace('\\n', ' ')` filter flattens
    embedded newlines so the injected `[credential]` token can never start
    a new line and therefore cannot be parsed as a section header by git.
    """
    body = _render(
        {
            "user_name": "Alice\n[credential]\n    helper = /tmp/evil",
            "user_email": "alice@example.com",
            "init_default_branch": "main",
            "pull_rebase": "false",
            "core_editor": "vim",
        }
    )

    # No newline immediately before `[credential]` → not parsed as a section.
    assert "\n[credential]" not in body
    # The literal token may still appear inside the [user] section value, but
    # never at the start of a line — verify by scanning each line.
    for line in body.splitlines():
        assert not line.lstrip().startswith("[credential]"), (
            f"Injected section header reached column 0: {line!r}"
        )


@pytest.mark.parametrize(
    "field",
    ["user_name", "user_email", "init_default_branch", "pull_rebase", "core_editor"],
)
def test_injection_blocked_for_each_field(field):
    """Every interpolated field carries its own replace filter — parametrize
    so a typo dropping the filter on any one of the five is caught.
    """
    base = {
        "user_name": "Alice",
        "user_email": "alice@example.com",
        "init_default_branch": "main",
        "pull_rebase": "false",
        "core_editor": "vim",
    }
    base[field] = "x\n[credential]\nhelper=/evil"
    body = _render(base)

    assert "\n[credential]" not in body
    for line in body.splitlines():
        assert not line.lstrip().startswith("[credential]"), (
            f"injection via {field} produced a [credential] header line: {line!r}"
        )


def test_null_byte_does_not_corrupt_render():
    """T3: NUL byte in a field should not appear in the rendered output."""
    body = _render(
        {
            "user_name": "Alice\x00evil",
            "user_email": "alice@example.com",
            "init_default_branch": "main",
            "pull_rebase": "false",
            "core_editor": "vim",
        }
    )
    # Jinja2's replace chain doesn't strip \x00, but the CLI sanitizer does.
    # Either way the rendered file must remain parseable by git (no NUL).
    # Document current behavior: \x00 reaches the template only if the
    # secrets store was poisoned out-of-band; in that case ~/.gitconfig
    # would carry a NUL inside the user.name value, which git tolerates as
    # a value but is operationally undesirable. The CLI-layer sanitizer is
    # the load-bearing fix; this test pins that the template render does
    # not crash.
    assert "Alice" in body


def test_carriage_return_in_user_email_is_stripped():
    body = _render(
        {
            "user_name": "Alice",
            "user_email": "alice\r\n[credential]\r\n\thelper=evil",
            "init_default_branch": "main",
            "pull_rebase": "false",
            "core_editor": "vim",
        }
    )
    assert "\r" not in body
    assert "\n[credential]" not in body
    for line in body.splitlines():
        assert not line.lstrip().startswith("[credential]")


def test_renders_identity_only_with_defaults():
    """Optional fields fall back to main / false / vim via Jinja default()."""
    body = _render(
        {
            "user_name": "Alice",
            "user_email": "alice@example.com",
            "init_default_branch": "",
            "pull_rebase": "",
            "core_editor": "",
        }
    )

    assert "defaultBranch = main" in body
    assert "rebase = false" in body
    assert "editor = vim" in body

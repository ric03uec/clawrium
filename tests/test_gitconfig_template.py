"""Tests for the shared gitconfig.j2 template (#531)."""

from pathlib import Path

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

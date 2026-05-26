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

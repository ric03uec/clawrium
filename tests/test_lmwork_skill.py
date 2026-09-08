"""Contracts for the mirrored clawctl-lmwork orchestration skill."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_lmwork_skill_mirrors_are_byte_identical() -> None:
    for name in ("SKILL.md", "judge.md"):
        claude = ROOT / ".claude" / "skills" / "clawctl-lmwork" / name
        opencode = ROOT / ".opencode" / "skills" / "clawctl-lmwork" / name
        assert claude.read_bytes() == opencode.read_bytes()


def test_lmwork_inline_sanitizer_preserves_structural_whitespace() -> None:
    skill = (
        ROOT / ".claude" / "skills" / "clawctl-lmwork" / "SKILL.md"
    ).read_text()
    bidi_only = (
        r"[\u061c\u200b-\u200f\u2028-\u202e\u2060\u2066-\u2069\ufeff]"
    )

    assert skill.count(bidi_only) == 2
    assert r"\u0000-\u001f" not in skill
    assert r"\u007f-\u009f" not in skill

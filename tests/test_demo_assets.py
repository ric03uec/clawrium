"""Regression test: VHS demo GIFs must stay within published size limits.

The `create-vhs` skill (`.claude/skills/create-vhs/SKILL.md`) sets these caps:
  - README GIFs:  < 500 KB
  - Docs GIFs:    < 3 MB

Without an automated gate, contributors can land oversized GIFs that bloat
clones and degrade README load times. This test enforces the limits the skill
documents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = REPO_ROOT / "docs" / "demos"

README_GIF_MAX_BYTES = 500_000
DOCS_GIF_MAX_BYTES = 3 * 1024 * 1024
README_GIF_NAME = "readme.gif"

pytestmark = pytest.mark.skipif(
    not DEMOS_DIR.is_dir(),
    reason="docs/demos directory missing — no demo assets to validate",
)


class TestDemoAssetSizes:
    def test_readme_gif_under_limit(self) -> None:
        readme_gif = DEMOS_DIR / README_GIF_NAME
        if not readme_gif.exists():
            pytest.skip(f"{README_GIF_NAME} not present")
        size = readme_gif.stat().st_size
        assert size < README_GIF_MAX_BYTES, (
            f"{README_GIF_NAME} is {size:,} bytes; "
            f"README GIFs must stay under {README_GIF_MAX_BYTES:,} bytes."
        )

    def test_docs_gifs_under_limit(self) -> None:
        checked = 0
        oversized: list[str] = []
        for gif in sorted(DEMOS_DIR.glob("*.gif")):
            if gif.name == README_GIF_NAME:
                continue
            checked += 1
            size = gif.stat().st_size
            if size >= DOCS_GIF_MAX_BYTES:
                oversized.append(f"{gif.name} ({size:,} bytes)")
        if checked == 0:
            pytest.skip("no non-readme GIFs present to validate")
        assert not oversized, (
            f"Docs GIFs over {DOCS_GIF_MAX_BYTES:,} bytes: {', '.join(oversized)}. "
            "Re-record with higher PlaybackSpeed or lower Framerate."
        )

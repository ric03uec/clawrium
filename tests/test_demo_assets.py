"""Regression tests for VHS demo assets in `docs/demos/`.

Two concerns are enforced:

1. **Size limits** — the `create-vhs` skill caps README GIFs at < 500 KiB and
   docs GIFs at < 3 MiB. Without an automated gate, contributors can land
   oversized GIFs that bloat clones and degrade README load times.

2. **Structural integrity** — every committed `.tape` must have a paired `.gif`
   (and vice versa), declare its `Output` path correctly, set `bash` as its
   shell, and include the portable `Hide`/`Show` venv activation block. Drift
   in any of these silently breaks re-recording.

Both the test file and the gated limits track
`.claude/skills/create-vhs/SKILL.md` and `CONTRIBUTING.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = REPO_ROOT / "docs" / "demos"

# Match SKILL.md & CONTRIBUTING.md: KiB / MiB (binary), not SI.
README_GIF_MAX_BYTES = 500 * 1024  # 512_000 bytes — "< 500 KiB"
DOCS_GIF_MAX_BYTES = 3 * 1024 * 1024  # 3_145_728 bytes — "< 3 MiB"
README_GIF_NAME = "readme.gif"
REQUIRED_COMMITTED_GIFS = (README_GIF_NAME,)

pytestmark = pytest.mark.skipif(
    not DEMOS_DIR.is_dir(),
    reason="docs/demos directory missing — no demo assets to validate",
)


class TestDemoAssetSizes:
    def test_readme_gif_present_and_under_limit(self) -> None:
        readme_gif = DEMOS_DIR / README_GIF_NAME
        assert readme_gif.exists(), (
            f"{README_GIF_NAME} is a committed asset and must be present in {DEMOS_DIR}."
        )
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


class TestTapeFileStructure:
    """Pure-text checks on committed `.tape` source files."""

    def _tape_files(self) -> list[Path]:
        return sorted(DEMOS_DIR.glob("*.tape"))

    def test_tape_files_present(self) -> None:
        tapes = self._tape_files()
        assert tapes, (
            f"At least one .tape file must be committed in {DEMOS_DIR}; "
            "tape files are the reproducible source for committed GIFs."
        )

    def test_tape_to_gif_pairing(self) -> None:
        """Every committed `.tape` must have a sibling `.gif` of the same stem."""
        missing: list[str] = []
        for tape in self._tape_files():
            paired_gif = tape.with_suffix(".gif")
            if not paired_gif.exists():
                missing.append(f"{tape.name} (expected {paired_gif.name})")
        assert not missing, (
            "Tape files without paired GIFs: " + "; ".join(missing) + ". "
            "Run vhs against the tape and commit the generated GIF."
        )

    def test_gif_to_tape_pairing(self) -> None:
        """Every committed `.gif` must have a sibling `.tape` of the same stem."""
        orphans: list[str] = []
        for gif in sorted(DEMOS_DIR.glob("*.gif")):
            paired_tape = gif.with_suffix(".tape")
            if not paired_tape.exists():
                orphans.append(f"{gif.name} (expected {paired_tape.name})")
        assert not orphans, (
            "GIF files without a source tape: " + "; ".join(orphans) + ". "
            "Commit the .tape used to generate the GIF (or remove the GIF)."
        )

    def test_tape_output_matches_filename(self) -> None:
        """The `Output ...` directive must point at `docs/demos/<same-stem>.gif`."""
        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        bad: list[str] = []
        for tape in self._tape_files():
            text = tape.read_text()
            match = output_re.search(text)
            if not match:
                bad.append(f"{tape.name}: missing Output directive")
                continue
            expected = f"docs/demos/{tape.stem}.gif"
            if match.group(1) != expected:
                bad.append(
                    f"{tape.name}: Output is '{match.group(1)}', expected '{expected}'"
                )
        assert not bad, "Tape Output directive issues:\n  - " + "\n  - ".join(bad)

    def test_tape_sets_bash_shell(self) -> None:
        """`Set Shell "bash"` must be present so commands behave consistently."""
        shell_re = re.compile(r'^\s*Set\s+Shell\s+"bash"\s*$', re.MULTILINE)
        bad = [tape.name for tape in self._tape_files() if not shell_re.search(tape.read_text())]
        assert not bad, (
            'Tapes missing `Set Shell "bash"`: '
            + ", ".join(bad)
            + ". VHS defaults to the user shell, which silently breaks portability."
        )

    def test_tape_has_portable_venv_activation(self) -> None:
        """The Hide/Show block must source the venv via repo-root resolution.

        Tapes that hardcode `/home/<user>/...` or `~/` only reproduce on the
        author's machine; the committed tape becomes unrunnable for everyone
        else.
        """
        repo_root_re = re.compile(
            r"git\s+rev-parse\s+--show-toplevel.*\.venv/bin/activate", re.DOTALL
        )
        bad_path_re = re.compile(r"(?:^|[^A-Za-z0-9_])(/home/|~/)")
        issues: list[str] = []
        for tape in self._tape_files():
            text = tape.read_text()
            if not repo_root_re.search(text):
                issues.append(
                    f"{tape.name}: missing portable "
                    '`source "$(git rev-parse --show-toplevel)/.venv/bin/activate"` '
                    "inside a Hide/Show block"
                )
            for lineno, line in enumerate(text.splitlines(), 1):
                if bad_path_re.search(line):
                    issues.append(f"{tape.name}:{lineno}: hardcoded home path: {line.strip()}")
        assert not issues, "Tape portability issues:\n  - " + "\n  - ".join(issues)

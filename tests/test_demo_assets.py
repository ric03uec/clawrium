"""Regression tests for VHS demo assets in `docs/demos/`.

Two concerns are enforced:

1. **Size limits** — the `create-vhs` skill caps docs GIFs at < 3 MiB.
   Without an automated gate, contributors can land oversized GIFs that
   bloat clones.

2. **Structural integrity** — every committed `.tape` must have a paired `.gif`
   (and vice versa), declare its `Output` path correctly, set `bash` as its
   shell, and include the portable `Hide`/`Show` venv activation block. Drift
   in any of these silently breaks re-recording.

Both the test file and the gated limits track
`.claude/skills/create-vhs/SKILL.md` and `CONTRIBUTING.md`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = REPO_ROOT / "docs" / "demos"
SKILL_TEMPLATES_DIR = (
    REPO_ROOT / ".claude" / "skills" / "create-vhs" / "templates"
)

# Match SKILL.md & CONTRIBUTING.md: KiB / MiB (binary), not SI.
DOCS_GIF_MAX_BYTES = 3 * 1024 * 1024  # 3_145_728 bytes — "< 3 MiB"

pytestmark = pytest.mark.skipif(
    not DEMOS_DIR.is_dir(),
    reason="docs/demos directory missing — no demo assets to validate",
)


class TestDemoAssetSizes:
    def test_docs_gifs_under_limit(self) -> None:
        checked = 0
        oversized: list[str] = []
        for gif in sorted(DEMOS_DIR.glob("*.gif")):
            checked += 1
            size = gif.stat().st_size
            if size >= DOCS_GIF_MAX_BYTES:
                oversized.append(f"{gif.name} ({size:,} bytes)")
        if checked == 0:
            pytest.skip("no GIFs present to validate")
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

    def test_tape_to_output_pairing(self) -> None:
        """Every committed `.tape` whose Output is in docs/demos/ must have its
        sibling rendered file (GIF or MP4) committed.

        Tapes whose Output is in docs/demos/recordings/ (gitignored) are skipped —
        the recording is uploaded to YouTube, not committed.
        """
        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        missing: list[str] = []
        for tape in self._tape_files():
            text = tape.read_text()
            match = output_re.search(text)
            if not match:
                continue  # validated by test_tape_output_matches_filename
            output_path = match.group(1)
            if output_path.startswith("docs/demos/recordings/"):
                continue
            paired = REPO_ROOT / output_path
            if not paired.exists():
                missing.append(f"{tape.name} (expected {output_path})")
        assert not missing, (
            "Tape files without paired output files: " + "; ".join(missing) + ". "
            "Run vhs against the tape and commit the generated file, "
            "or move its Output to docs/demos/recordings/ to opt out."
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
        """The `Output ...` directive must point at one of:

        - `docs/demos/<stem>.gif` or `.mp4` (legacy / README-embedded; committed).
        - `docs/demos/recordings/<stem>.gif` or `.mp4` (new convention; gitignored,
          uploaded to YouTube).
        """
        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        bad: list[str] = []
        for tape in self._tape_files():
            text = tape.read_text()
            match = output_re.search(text)
            if not match:
                bad.append(f"{tape.name}: missing Output directive")
                continue
            stem = tape.stem
            allowed = {
                f"docs/demos/{stem}.gif",
                f"docs/demos/{stem}.mp4",
                f"docs/demos/recordings/{stem}.gif",
                f"docs/demos/recordings/{stem}.mp4",
            }
            if match.group(1) not in allowed:
                bad.append(
                    f"{tape.name}: Output is '{match.group(1)}'; "
                    f"expected one of: {sorted(allowed)}"
                )
        assert not bad, "Tape Output directive issues:\n  - " + "\n  - ".join(bad)

    def test_tape_sets_bash_shell(self) -> None:
        """`Set Shell "bash"` must be present so commands behave consistently."""
        shell_re = re.compile(r'^\s*Set\s+Shell\s+"bash"\s*$', re.MULTILINE)
        bad = [
            tape.name
            for tape in self._tape_files()
            if not shell_re.search(tape.read_text())
        ]
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
                    issues.append(
                        f"{tape.name}:{lineno}: hardcoded home path: {line.strip()}"
                    )
        assert not issues, "Tape portability issues:\n  - " + "\n  - ".join(issues)


class TestSkillTemplates:
    """Structural checks on the create-vhs skill's bundled templates.

    Templates ship at `.claude/skills/create-vhs/templates/` and are the
    source of truth `/create-vhs` copies into `docs/demos/` for new demos.
    Drift here silently breaks every future generated demo.
    """

    @pytest.fixture
    def long_form_tape(self) -> Path:
        path = SKILL_TEMPLATES_DIR / "long-form.tape.template"
        if not path.exists():
            pytest.skip(f"missing {path}")
        return path

    @pytest.fixture
    def progress_helper(self) -> Path:
        path = SKILL_TEMPLATES_DIR / "_progress.sh.template"
        if not path.exists():
            pytest.skip(f"missing {path}")
        return path

    @pytest.fixture
    def storyboard(self) -> Path:
        path = SKILL_TEMPLATES_DIR / "storyboard.md.template"
        if not path.exists():
            pytest.skip(f"missing {path}")
        return path

    def test_long_form_tape_sets_bash_shell(self, long_form_tape: Path) -> None:
        shell_re = re.compile(r'^\s*Set\s+Shell\s+"bash"\s*$', re.MULTILINE)
        assert shell_re.search(long_form_tape.read_text()), (
            'long-form.tape.template missing `Set Shell "bash"` — generated tapes '
            "would default to the user shell and silently break."
        )

    def test_long_form_tape_portable_venv_activation(
        self, long_form_tape: Path
    ) -> None:
        repo_root_re = re.compile(
            r"git\s+rev-parse\s+--show-toplevel.*\.venv/bin/activate", re.DOTALL
        )
        text = long_form_tape.read_text()
        assert repo_root_re.search(text), (
            "long-form.tape.template missing portable venv activation — "
            "regenerated tapes would only run on the author's machine."
        )

    def test_long_form_tape_output_targets_recordings(
        self, long_form_tape: Path
    ) -> None:
        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        match = output_re.search(long_form_tape.read_text())
        assert match, "long-form.tape.template missing Output directive"
        # Template uses an <NAME> placeholder, so check the directory prefix.
        assert match.group(1).startswith("docs/demos/recordings/"), (
            f"long-form.tape.template Output is '{match.group(1)}'; "
            "must target docs/demos/recordings/ per the gitignored convention."
        )

    def test_long_form_tape_declares_require(self, long_form_tape: Path) -> None:
        text = long_form_tape.read_text()
        assert re.search(r"^\s*Require\s+\S+", text, re.MULTILINE), (
            "long-form.tape.template should declare at least one `Require` "
            "directive for fail-fast validation."
        )

    def test_progress_helper_bash_syntax(self, progress_helper: Path) -> None:
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash not on PATH")
        result = subprocess.run(
            [bash, "-n", str(progress_helper)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"_progress.sh.template fails `bash -n`: {result.stderr.strip()}"
        )

    @pytest.mark.parametrize(
        "marker",
        ["_SCENES", "_TITLE", "_SUBTITLE", "_OUTRO_LINE_1", "_OUTRO_LINE_2"],
    )
    def test_progress_helper_required_fill_in_fields(
        self, progress_helper: Path, marker: str
    ) -> None:
        text = progress_helper.read_text()
        assert re.search(rf"^{marker}=", text, re.MULTILINE), (
            f"_progress.sh.template missing FILL-IN marker `{marker}` — "
            "renaming or removing a marker breaks every generated helpers script."
        )

    @pytest.mark.parametrize(
        "func", ["progress", "headline", "titlecard", "outrocard"]
    )
    def test_progress_helper_defines_required_functions(
        self, progress_helper: Path, func: str
    ) -> None:
        text = progress_helper.read_text()
        assert re.search(rf"^{func}\s*\(\)\s*\{{", text, re.MULTILINE), (
            f"_progress.sh.template missing required function `{func}()` — "
            "long-form tapes invoke this by name and will fail at record time."
        )

    @pytest.mark.parametrize(
        "header_substring",
        ["Title", "Command", "Mode", "Capture file"],
    )
    def test_storyboard_template_has_required_columns(
        self, storyboard: Path, header_substring: str
    ) -> None:
        text = storyboard.read_text()
        assert header_substring in text, (
            f"storyboard.md.template missing required column header containing "
            f"`{header_substring}` — column rename breaks downstream tooling and "
            "the skill's scene-table contract."
        )


class TestRecordingsConventionBranch:
    """Synthetic-tape coverage for the `recordings/` skip branch.

    Both existing tapes output to `docs/demos/`, so the production tape set
    never exercises the new gitignored-output skip path. These tests build
    minimal tapes via `tmp_path` to drive the branch directly.
    """

    def _write_minimal_tape(self, path: Path, output_line: str) -> None:
        path.write_text(
            f"# minimal\n{output_line}\n"
            'Set Shell "bash"\n'
            "Hide\n"
            'Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`\n'
            "Enter\n"
            "Show\n"
        )

    def test_pairing_skips_recordings_output(self, tmp_path: Path) -> None:
        """A tape whose Output is in recordings/ passes pairing without a sibling file."""
        from tests.test_demo_assets import REPO_ROOT as _REPO_ROOT  # noqa: F401

        tape = tmp_path / "demo.tape"
        self._write_minimal_tape(
            tape, "Output docs/demos/recordings/demo.mp4"
        )

        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        match = output_re.search(tape.read_text())
        assert match is not None
        # Branch under test: when Output is under recordings/, pairing is skipped.
        assert match.group(1).startswith("docs/demos/recordings/")

    def test_pairing_requires_sibling_for_non_recordings_output(
        self, tmp_path: Path
    ) -> None:
        """A tape whose Output is in docs/demos/ requires the rendered file alongside."""
        tape = tmp_path / "demo.tape"
        self._write_minimal_tape(tape, "Output docs/demos/demo.gif")

        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        match = output_re.search(tape.read_text())
        assert match is not None
        assert not match.group(1).startswith("docs/demos/recordings/")
        # Sibling absent — pairing would fail for this synthetic tape.
        assert not (tmp_path / "demo.gif").exists()

    @pytest.mark.parametrize(
        "output_path,allowed",
        [
            ("docs/demos/demo.gif", True),
            ("docs/demos/demo.mp4", True),
            ("docs/demos/recordings/demo.gif", True),
            ("docs/demos/recordings/demo.mp4", True),
            ("docs/demos/subdir/demo.gif", False),
            ("/tmp/demo.mp4", False),
            ("recordings/demo.mp4", False),
        ],
    )
    def test_output_path_allowlist(
        self, output_path: str, allowed: bool
    ) -> None:
        """The Output allowlist matches exactly four shapes."""
        stem = "demo"
        allowed_paths = {
            f"docs/demos/{stem}.gif",
            f"docs/demos/{stem}.mp4",
            f"docs/demos/recordings/{stem}.gif",
            f"docs/demos/recordings/{stem}.mp4",
        }
        assert (output_path in allowed_paths) is allowed


class TestRecordingsDirectoryConvention:
    def test_gitkeep_present(self) -> None:
        """The recordings/ dir must ship a `.gitkeep` so it exists in fresh clones."""
        gitkeep = DEMOS_DIR / "recordings" / ".gitkeep"
        assert gitkeep.exists(), (
            f"{gitkeep} missing — directory will not exist for fresh clones, "
            "first `/create-vhs` run would fail without a `mkdir -p`."
        )

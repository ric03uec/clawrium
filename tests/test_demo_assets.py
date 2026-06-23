"""Regression tests for VHS demo assets in `docs/demos/`.

Enforces:

1. **Legacy size limits & tape structural integrity** — committed top-level
   `.tape` files (currently only `agent-reprovision.tape`) must declare valid
   `Output`, set bash shell, and use portable venv activation.

2. **Shared lib integrity** — `docs/demos/lib/` ships the four ANSI helpers
   (`titlecard`/`outrocard`/`headline`/`progress`) every generated demo
   sources, plus `compile.py` and `narrate.py` (replay-first pipeline).

3. **Replay-first pipeline** — `compile.py` must produce a valid tape, a
   `compiled.json` with absolute narration timestamps, and a per-demo
   helpers.sh from a `scenes.yaml` spec.

4. **Skill template** — `scenes.yaml.template` carries the fields the
   compile step reads at scaffold-time (title, scenes list with output_file,
   etc.).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = REPO_ROOT / "docs" / "demos"
DEMOS_LIB_DIR = DEMOS_DIR / "lib"
SKILL_TEMPLATES_DIR = (
    REPO_ROOT / ".claude" / "skills" / "create-vhs" / "templates"
)

# Match SKILL.md & CONTRIBUTING.md: KiB / MiB (binary), not SI.
DOCS_GIF_MAX_BYTES = 3 * 1024 * 1024  # "< 3 MiB"

pytestmark = pytest.mark.skipif(
    not DEMOS_DIR.is_dir(),
    reason="docs/demos directory missing — no demo assets to validate",
)


# --------------------------------------------------------------------------- #
# Legacy top-level demos                                                      #
# --------------------------------------------------------------------------- #
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
            f"Docs GIFs over {DOCS_GIF_MAX_BYTES:,} bytes: "
            f"{', '.join(oversized)}. Re-record with lower Framerate."
        )


class TestLegacyTapeFiles:
    """Pure-text checks on legacy top-level `.tape` files (pre-replay-first)."""

    def _tape_files(self) -> list[Path]:
        return sorted(DEMOS_DIR.glob("*.tape"))

    def test_tape_to_output_pairing(self) -> None:
        output_re = re.compile(r"^\s*Output\s+(\S+)\s*$", re.MULTILINE)
        missing: list[str] = []
        for tape in self._tape_files():
            match = output_re.search(tape.read_text())
            if not match:
                continue
            output_path = match.group(1)
            if output_path.startswith("docs/demos/recordings/"):
                continue
            paired = REPO_ROOT / output_path
            if not paired.exists():
                missing.append(f"{tape.name} (expected {output_path})")
        assert not missing, "Legacy tapes without paired outputs: " + "; ".join(missing)

    def test_gif_to_tape_pairing(self) -> None:
        orphans: list[str] = []
        for gif in sorted(DEMOS_DIR.glob("*.gif")):
            paired_tape = gif.with_suffix(".tape")
            if not paired_tape.exists():
                orphans.append(f"{gif.name} (expected {paired_tape.name})")
        assert not orphans, "Orphan GIFs: " + "; ".join(orphans)

    def test_tape_sets_bash_shell(self) -> None:
        shell_re = re.compile(r'^\s*Set\s+Shell\s+"bash"\s*$', re.MULTILINE)
        bad = [t.name for t in self._tape_files() if not shell_re.search(t.read_text())]
        assert not bad, f'Legacy tapes missing `Set Shell "bash"`: {", ".join(bad)}'

    def test_tape_has_portable_venv_activation(self) -> None:
        repo_root_re = re.compile(
            r"git\s+rev-parse\s+--show-toplevel.*\.venv/bin/activate", re.DOTALL
        )
        bad_path_re = re.compile(r"(?:^|[^A-Za-z0-9_])(/home/|~/)")
        issues: list[str] = []
        for tape in self._tape_files():
            text = tape.read_text()
            if not repo_root_re.search(text):
                issues.append(f"{tape.name}: missing portable venv activation")
            for lineno, line in enumerate(text.splitlines(), 1):
                if bad_path_re.search(line):
                    issues.append(f"{tape.name}:{lineno}: hardcoded home path: {line.strip()}")
        assert not issues, "Legacy tape portability issues: " + "; ".join(issues)


# --------------------------------------------------------------------------- #
# Shared lib                                                                  #
# --------------------------------------------------------------------------- #
class TestSharedLib:
    @pytest.mark.parametrize("func", ["progress", "headline", "titlecard", "outrocard"])
    def test_cards_lib_defines_required_functions(self, func: str) -> None:
        cards_lib = DEMOS_LIB_DIR / "cards.sh"
        if not cards_lib.exists():
            pytest.skip(f"missing {cards_lib}")
        text = cards_lib.read_text()
        assert re.search(rf"^{func}\s*\(\)\s*\{{", text, re.MULTILINE), (
            f"docs/demos/lib/cards.sh missing required function `{func}()`."
        )

    def test_cards_lib_bash_syntax(self) -> None:
        bash = shutil.which("bash")
        if bash is None:
            pytest.skip("bash not on PATH")
        cards_lib = DEMOS_LIB_DIR / "cards.sh"
        if not cards_lib.exists():
            pytest.skip(f"missing {cards_lib}")
        result = subprocess.run(
            [bash, "-n", str(cards_lib)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, f"cards.sh fails bash -n: {result.stderr.strip()}"

    def test_env_example_template_has_required_keys(self) -> None:
        env_example = DEMOS_LIB_DIR / ".env.example"
        if not env_example.exists():
            pytest.skip(f"missing {env_example}")
        text = env_example.read_text()
        for key in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"):
            assert re.search(rf"^{key}=", text, re.MULTILINE), (
                f".env.example missing required key `{key}`."
            )


# --------------------------------------------------------------------------- #
# Replay-first pipeline (compile.py + narrate.py)                             #
# --------------------------------------------------------------------------- #
def _load_module(path: Path, name: str):
    """Import a script-style module (PEP 723) cleanly, even on Python 3.14."""
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception:
        # Re-raise so the calling test reports the real failure.
        raise


def _committed_vhs_demos() -> list[Path]:
    # Playwright demos (tape.base_url set) are compiled by pw_compile.py and
    # do not share compile.py's `command:` per-scene contract.
    import yaml as _yaml
    demos: list[Path] = []
    for p in sorted(DEMOS_DIR.glob("*/")):
        scenes = p / "scenes.yaml"
        if not scenes.exists():
            continue
        try:
            spec = _yaml.safe_load(scenes.read_text()) or {}
        except Exception:
            continue
        if (spec.get("tape") or {}).get("base_url"):
            continue
        demos.append(p)
    return demos


class TestCompilePipeline:
    @pytest.fixture
    def compile_mod(self):
        mod = _load_module(DEMOS_LIB_DIR / "compile.py", "_compile_under_test")
        if mod is None:
            pytest.skip("compile.py missing")
        try:
            yield mod
        finally:
            sys.modules.pop("_compile_under_test", None)

    def test_compile_module_imports(self, compile_mod) -> None:
        assert hasattr(compile_mod, "compile_demo")
        assert hasattr(compile_mod, "main")

    def test_compile_minimal_yaml(self, compile_mod, tmp_path: Path) -> None:
        """Compile a minimal yaml spec — verify tape + helpers + compiled.json shape."""
        demo = tmp_path / "20260101-mini"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01-version.txt").write_text("clawctl 99.99.99\n")
        (demo / "scenes.yaml").write_text(
            "title: Mini\n"
            "subtitle: test\n"
            "outro:\n"
            "  line_1: x\n"
            "  line_2: y\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: version\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01-version.txt\n"
            "    screen_seconds: 3\n"
            "    narration:\n"
            "      - text: hello\n"
        )
        tape, manifest, _warnings, _used_actuals = compile_mod.compile_demo(demo)
        assert tape.exists() and manifest.exists()
        assert (demo / "helpers.sh").exists()
        tape_text = tape.read_text()
        # Required structural elements
        assert "Require vhs" in tape_text
        assert "Output " in tape_text
        assert "GENERATED FROM scenes.yaml" in tape_text
        assert 'headline 1 "version"' in tape_text
        # Tape types the REAL command (not a cat of the cached output).
        assert 'Type "clawctl --version"' in tape_text
        # No `Type "cat ..."` line — anchored regex avoids false positives
        # from comments or narration containing the word "cat".
        cat_type_re = re.compile(r'^\s*Type\s+"cat\s', re.MULTILINE)
        assert not cat_type_re.search(tape_text), (
            "tape.tape must never emit `Type \"cat ...\"` — replay goes through "
            "the clawctl() override in helpers.sh, not a visible cat command."
        )
        # Setup installs the replay override AFTER live setup steps.
        assert 'Type "_replay_install"' in tape_text
        # Helpers.sh wires the clawctl() override to dispatch by command line.
        helpers = (demo / "helpers.sh").read_text()
        assert "_replay_install()" in helpers
        assert "clawctl()" in helpers
        assert '"--version") cat docs/demos/' in helpers
        data = json.loads(manifest.read_text())
        assert data["title"] == "Mini"
        assert len(data["narration"]) == 1
        assert data["narration"][0]["text"] == "hello"
        assert data["narration"][0]["absolute_seconds"] > 0
        assert data["recording_duration_seconds"] > 0

    @pytest.mark.parametrize(
        "fmt,expected_filename",
        [
            (None, "recording.mp4"),  # absent → default to mp4
            ("mp4", "recording.mp4"),
            ("gif", "recording.gif"),
            ("MP4", "recording.mp4"),  # case-insensitive
            ("GIF", "recording.gif"),
        ],
        ids=["default", "mp4", "gif", "mp4-upper", "gif-upper"],
    )
    def test_compile_output_format(
        self, compile_mod, tmp_path: Path, fmt: str | None, expected_filename: str
    ) -> None:
        """`tape.output_format` drives the tape's Output line (mp4 default; gif valid)."""
        demo = tmp_path / "20260101-fmt"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01-version.txt").write_text("clawctl 99.99.99\n")
        tape_block = "tape:\n  framerate: 30\n"
        if fmt is not None:
            tape_block += f"  output_format: {fmt}\n"
        (demo / "scenes.yaml").write_text(
            "title: Fmt\n"
            "subtitle: test\n"
            f"{tape_block}"
            "outro:\n"
            "  line_1: x\n"
            "  line_2: y\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: version\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01-version.txt\n"
            "    screen_seconds: 3\n"
            "    narration:\n"
            "      - text: hello\n"
        )
        tape, _manifest, _w, _u = compile_mod.compile_demo(demo)
        tape_text = tape.read_text()
        assert f"/{expected_filename}" in tape_text, (
            f"expected Output line to reference {expected_filename}, "
            f"got tape:\n{tape_text[:600]}"
        )

    def test_compile_output_format_rejects_unknown(
        self, compile_mod, tmp_path: Path
    ) -> None:
        """An invalid `tape.output_format` must fail loudly, not silently default."""
        demo = tmp_path / "20260101-badfmt"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01-version.txt").write_text("x\n")
        (demo / "scenes.yaml").write_text(
            "title: Bad\n"
            "subtitle: t\n"
            "tape:\n"
            "  output_format: webm\n"
            "outro:\n"
            "  line_1: x\n"
            "  line_2: y\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: v\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01-version.txt\n"
            "    screen_seconds: 3\n"
            "    narration:\n"
            "      - text: hi\n"
        )
        with pytest.raises(ValueError, match="output_format"):
            compile_mod.compile_demo(demo)

    # --- W3: every (head, tail) combination for replay dispatch ------------- #
    @pytest.mark.parametrize(
        "head,tail,expect_in_dispatch,not_expect_in_dispatch",
        [
            (None, None, ["cat "], ["head -n", "tail -n", "…"]),
            (10,   None, ["head -n 10"], ["tail -n", "…"]),
            (None, 5,    ["tail -n 5"], ["head -n", "…"]),
            (10,   5,    ["head -n 10", "tail -n 5", "…"], []),
        ],
        ids=["full-cat", "head-only", "tail-only", "head-and-tail"],
    )
    def test_replay_dispatch_combinations(
        self, compile_mod, head, tail, expect_in_dispatch, not_expect_in_dispatch
    ) -> None:
        """`_build_replay_dispatch` must emit the exact shape per (head, tail)."""
        dispatch = compile_mod._build_replay_dispatch("OUT.txt", head, tail)
        for needle in expect_in_dispatch:
            assert needle in dispatch, (
                f"expected `{needle}` in dispatch for head={head}, tail={tail}; got: {dispatch}"
            )
        for needle in not_expect_in_dispatch:
            assert needle not in dispatch, (
                f"unexpected `{needle}` in dispatch for head={head}, tail={tail}; got: {dispatch}"
            )

    # --- W4: LIVE-mode scene escape hatch ----------------------------------- #
    def test_compile_live_mode_scene_omitted_from_replay_case(
        self, compile_mod, tmp_path: Path
    ) -> None:
        """`mode: LIVE` scenes execute the real command and must NOT appear
        as a case-arm in the helpers.sh clawctl() override.
        """
        demo = tmp_path / "20260101-live"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01.txt").write_text("v\n")
        (demo / "scenes.yaml").write_text(
            "title: L\nsubtitle: t\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: v\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01.txt\n"
            "    screen_seconds: 3\n"
            "  - n: 2\n"
            "    title: chat\n"
            "    command: clawctl agent chat live-demo\n"
            "    mode: LIVE\n"
            "    screen_seconds: 5\n"
        )
        compile_mod.compile_demo(demo)
        helpers = (demo / "helpers.sh").read_text()
        # Scene 1 replay arm is present.
        assert '"--version") cat docs/demos/' in helpers
        # Scene 2 LIVE arm is NOT present — clawctl call would fall through
        # to the real CLI, not the replay override.
        assert "agent chat live-demo" not in helpers, (
            "LIVE scene leaked into the replay case statement — clawctl() "
            "would intercept it instead of executing the real command."
        )

    def test_compile_head_tail_elision_in_helpers(self, compile_mod, tmp_path: Path) -> None:
        """`head:` + `tail:` is dispatched from helpers.sh, not the tape.

        The tape stays clean (just types the real command); the cached-output
        replay including the head/tail elision lives in the clawctl() override
        installed by helpers.sh.
        """
        demo = tmp_path / "20260101-elision"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01-version.txt").write_text("v\n")
        (demo / "outputs" / "04-install.txt").write_text("\n".join(str(i) for i in range(200)))
        (demo / "scenes.yaml").write_text(
            "title: Elision\nsubtitle: t\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: v\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01-version.txt\n"
            "    screen_seconds: 3\n"
            "  - n: 4\n"
            "    title: install\n"
            "    command: clawctl agent create demo --type hermes --host h\n"
            f"    output_file: docs/demos/{demo.name}/outputs/04-install.txt\n"
            "    head: 10\n"
            "    tail: 5\n"
            "    screen_seconds: 6\n"
        )
        tape, _manifest, _w, _u = compile_mod.compile_demo(demo)
        helpers = (demo / "helpers.sh").read_text()
        assert "head -n 10" in helpers
        assert "tail -n 5" in helpers
        # The visible tape types the real command, not any cat/head/tail.
        tape_text = tape.read_text()
        assert 'Type "clawctl agent create demo --type hermes --host h"' in tape_text

    # --- W2: Stage 2 — actual ffprobed durations override the estimator ----- #
    def test_stage2_uses_actual_durations_over_estimate(
        self, compile_mod, tmp_path: Path
    ) -> None:
        """voice/_durations.json must short-circuit the char-rate estimate.

        Seed the cache with a duration MUCH larger than the char estimate
        would yield. compile must extend screen_seconds to fit, and
        `used_actuals` must return True. Also seeds one malformed entry to
        prove the silent-skip branch doesn't break loading.
        """
        demo = tmp_path / "20260101-stage2"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01-version.txt").write_text("v\n")
        (demo / "scenes.yaml").write_text(
            "title: S2\nsubtitle: t\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: v\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01-version.txt\n"
            "    screen_seconds: 3\n"
            "    narration:\n"
            '      - text: "x"\n'  # 1 char ≈ 0.07s estimate
        )
        # Actual ffprobed duration is 30s — should drive the auto-extension.
        (demo / "voice").mkdir()
        (demo / "voice" / "_durations.json").write_text(json.dumps({
            "1.1": 30.0,
            "bogus_key": "not-a-number",  # tests the silent-skip branch
        }))

        _, manifest, warnings, used_actuals = compile_mod.compile_demo(demo)
        assert used_actuals is True

        # Expect screen_seconds extended to at least 30s + 1.5s buffer.
        assert any("scene 1" in w and "screen_seconds extended" in w for w in warnings), (
            f"expected scene 1 extension warning citing the 30s actual; got {warnings}"
        )

        data = json.loads(manifest.read_text())
        # Recording must be long enough to contain a 30s narration starting
        # at scene 1's command-output time.
        beat_t = data["narration"][0]["absolute_seconds"]
        assert data["recording_duration_seconds"] >= beat_t + 30.0

    # --- W5: warnings list is populated for known overlap cases -------------- #
    def test_intra_scene_overlap_emits_warning(
        self, compile_mod, tmp_path: Path
    ) -> None:
        demo = tmp_path / "20260101-overlap"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01.txt").write_text("v\n")
        (demo / "scenes.yaml").write_text(
            "title: O\nsubtitle: t\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: v\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01.txt\n"
            "    screen_seconds: 60\n"
            "    narration:\n"
            "      - offset_seconds: 0\n"
            # Long narration that won't finish before beat 2 starts.
            '      - text: ' + json.dumps("a" * 280) + "\n"
            "      - offset_seconds: 1\n"  # well before beat 1 ends (~20s)
            '        text: "second beat"\n'
        )
        # YAML above is malformed (offset_seconds out of order); rebuild cleanly.
        (demo / "scenes.yaml").write_text(
            "title: O\nsubtitle: t\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: v\n"
            "    command: clawctl --version\n"
            f"    output_file: docs/demos/{demo.name}/outputs/01.txt\n"
            "    screen_seconds: 60\n"
            "    narration:\n"
            '      - text: ' + json.dumps("a" * 280) + "\n"
            "      - offset_seconds: 1\n"
            '        text: "second beat"\n'
        )
        _, _, warnings, _ = compile_mod.compile_demo(demo)
        assert any(
            re.search(r"scene 1 beat 2.*intra-scene overlap", w) for w in warnings
        ), f"expected intra-scene overlap warning; got {warnings}"

    def test_compile_rejects_non_clawctl_replay(self, compile_mod, tmp_path: Path) -> None:
        """Non-clawctl commands must be marked LIVE — the override only patches clawctl."""
        demo = tmp_path / "20260101-noncc"
        (demo / "outputs").mkdir(parents=True)
        (demo / "outputs" / "01.txt").write_text("x")
        (demo / "scenes.yaml").write_text(
            "title: t\nsubtitle: s\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes:\n"
            "  - n: 1\n"
            "    title: t\n"
            '    command: "echo hello"\n'  # non-clawctl
            f"    output_file: docs/demos/{demo.name}/outputs/01.txt\n"
            "    screen_seconds: 3\n"
        )
        with pytest.raises(ValueError, match="must start with `clawctl `"):
            compile_mod.compile_demo(demo)

    # --- W9 edge cases ------------------------------------------------------- #
    def test_compile_missing_yaml(self, compile_mod, tmp_path: Path) -> None:
        demo = tmp_path / "20260101-no-yaml"
        demo.mkdir()
        with pytest.raises(FileNotFoundError, match="scenes.yaml"):
            compile_mod.compile_demo(demo)

    def test_compile_malformed_yaml(self, compile_mod, tmp_path: Path) -> None:
        import yaml as _yaml
        demo = tmp_path / "20260101-bad-yaml"
        demo.mkdir()
        (demo / "scenes.yaml").write_text("title: ok\n  bogus: : :\n")
        with pytest.raises(_yaml.YAMLError):
            compile_mod.compile_demo(demo)

    def test_compile_empty_scenes(self, compile_mod, tmp_path: Path) -> None:
        """Empty scenes list compiles to a tape with only the structural beats.

        It's a degenerate but valid spec — useful for testing title/checklist/
        outro rendering in isolation. Must not raise.
        """
        demo = tmp_path / "20260101-empty"
        demo.mkdir()
        (demo / "scenes.yaml").write_text(
            "title: Empty\nsubtitle: s\n"
            "outro: {line_1: x, line_2: y}\n"
            "scenes: []\n"
        )
        tape, manifest, _warnings, _used_actuals = compile_mod.compile_demo(demo)
        text = tape.read_text()
        assert 'Type "titlecard"' in text
        assert 'Type "outrocard"' in text
        data = json.loads(manifest.read_text())
        assert data["recording_duration_seconds"] > 0  # title + outro still cost time
        assert data["narration"] == []  # no narration without scenes

    # --- timing safety: no narration audio bleeds across boundaries ---------- #
    @pytest.mark.parametrize(
        "demo_dir",
        [pytest.param(p, id=p.name) for p in _committed_vhs_demos()],
    )
    def test_no_narration_overlap_committed(
        self, compile_mod, demo_dir: Path, tmp_path: Path
    ) -> None:
        """Every committed demo's narration beats must not audio-overlap.

        For each consecutive pair of beats, assert that:
            beat[i].absolute_seconds + est_audio_duration(beat[i].text)
              <= beat[i+1].absolute_seconds + 0.5s slack

        The 0.5s slack absorbs char-rate estimator noise; with the
        DEFAULT_NARRATION_BUFFER=1.5s enforced by compile.py, real overlap
        means a regression in the timing model.
        """
        scratch = tmp_path / demo_dir.name
        shutil.copytree(demo_dir, scratch)
        for derived in ("tape.tape", "helpers.sh", "compiled.json"):
            (scratch / derived).unlink(missing_ok=True)
        # Force Stage 1 (no ffprobed actuals) so the test is hermetic.
        voice_dir = scratch / "voice"
        if voice_dir.exists():
            shutil.rmtree(voice_dir)
        _, manifest, _w, _u = compile_mod.compile_demo(scratch)
        data = json.loads(manifest.read_text())
        beats = data["narration"]
        assert beats, f"{demo_dir.name}: no narration beats"

        cps = float(compile_mod.DEFAULT_AUDIO_CPS)
        overlaps: list[str] = []
        for cur, nxt in zip(beats, beats[1:]):
            audio_end = cur["absolute_seconds"] + compile_mod._estimate_audio_seconds(cur["text"], cps)
            next_start = nxt["absolute_seconds"]
            slack = 0.5
            if audio_end > next_start + slack:
                overlaps.append(
                    f"  beat {cur['scene_n']}.{cur['beat_n']} ends at {audio_end:.2f}s "
                    f"(>{next_start + slack:.2f}s start of beat "
                    f"{nxt['scene_n']}.{nxt['beat_n']})"
                )
        assert not overlaps, (
            f"{demo_dir.name}: narration overlap detected — "
            "compile.py auto-extension failed to size sleeps correctly:\n"
            + "\n".join(overlaps)
        )

    # --- W6: every committed scenes.yaml's output_file must exist on disk --- #
    @pytest.mark.parametrize(
        "demo_dir",
        [pytest.param(p, id=p.name) for p in _committed_vhs_demos()],
    )
    def test_committed_demo_output_files_exist(self, demo_dir: Path) -> None:
        """Every `output_file:` referenced in a committed scenes.yaml must
        exist on disk and be non-empty.

        Without this check, a typo in the YAML path compiles cleanly
        (compile.py only reads the path string) and then fails at record
        time when the clawctl() override tries to `cat` a missing file —
        producing a broken recording that took ~3 minutes to make.
        """
        import yaml as _yaml
        spec = _yaml.safe_load((demo_dir / "scenes.yaml").read_text())
        missing: list[str] = []
        empty: list[str] = []
        for scene in spec.get("scenes", []):
            if scene.get("mode", "replay") == "LIVE":
                continue  # LIVE scenes don't need a cached output
            path_str = scene.get("output_file")
            if not path_str:
                missing.append(f"scene {scene['n']}: no output_file declared")
                continue
            full = REPO_ROOT / path_str
            if not full.exists():
                missing.append(f"scene {scene['n']}: {path_str}")
            elif full.stat().st_size == 0:
                empty.append(f"scene {scene['n']}: {path_str}")
        assert not missing, (
            f"{demo_dir.name} references missing output files:\n  "
            + "\n  ".join(missing)
        )
        assert not empty, (
            f"{demo_dir.name} references empty output files (would render "
            f"as blank cat in recording):\n  " + "\n  ".join(empty)
        )

    # --- W4 round-trip over the real committed demo --------------------------- #
    @pytest.mark.parametrize(
        "demo_dir",
        [pytest.param(p, id=p.name) for p in _committed_vhs_demos()],
    )
    def test_committed_demos_compile_cleanly(
        self, compile_mod, demo_dir: Path, tmp_path: Path
    ) -> None:
        """Every committed demo's scenes.yaml must compile to a valid tape.

        Runs the compile against a tmp_path copy so we never overwrite
        committed artifacts. Validates structural invariants:
          - tape declares Output + Require vhs
          - helpers.sh defines _replay_install
          - every narration beat's absolute_seconds is within the predicted
            recording duration
        """
        # Copy the demo into a scratch dir so we don't mutate committed files.
        scratch = tmp_path / demo_dir.name
        shutil.copytree(demo_dir, scratch)
        # Wipe derived artifacts to prove compile.py re-generates them.
        for derived in ("tape.tape", "helpers.sh", "compiled.json"):
            (scratch / derived).unlink(missing_ok=True)

        tape, manifest, _warnings, _used_actuals = compile_mod.compile_demo(scratch)
        assert tape.exists()
        assert (scratch / "helpers.sh").exists()
        tape_text = tape.read_text()
        assert "Require vhs" in tape_text
        assert "Output " in tape_text
        helpers_text = (scratch / "helpers.sh").read_text()
        assert "_replay_install" in helpers_text

        data = json.loads(manifest.read_text())
        duration = float(data["recording_duration_seconds"])
        assert duration > 0
        for beat in data["narration"]:
            t = float(beat["absolute_seconds"])
            assert 0 <= t <= duration, (
                f"{demo_dir.name}: narration beat at {t}s exceeds predicted "
                f"recording duration {duration}s — narration text would be cut off."
            )


class TestNarratePipeline:
    @pytest.fixture
    def narrate_mod(self):
        mod = _load_module(DEMOS_LIB_DIR / "narrate.py", "_narrate_under_test")
        if mod is None:
            pytest.skip("narrate.py missing")
        try:
            yield mod
        finally:
            sys.modules.pop("_narrate_under_test", None)

    def test_narrate_module_imports(self, narrate_mod) -> None:
        assert hasattr(narrate_mod, "load_beats")
        assert hasattr(narrate_mod, "Beat")
        assert hasattr(narrate_mod, "main")

    def test_load_beats_reads_compiled_json(self, narrate_mod, tmp_path: Path) -> None:
        demo = tmp_path / "demo"
        demo.mkdir()
        (demo / "compiled.json").write_text(json.dumps({
            "title": "T", "subtitle": "S",
            "recording_duration_seconds": 100,
            "narration": [
                {"scene_n": 1, "beat_n": 1, "absolute_seconds": 10.5, "text": "hello"},
                {"scene_n": 2, "beat_n": 1, "absolute_seconds": 5.0,  "text": "first"},
            ],
        }))
        beats = narrate_mod.load_beats(demo / "compiled.json")
        assert len(beats) == 2
        # Sorted by absolute_seconds.
        assert beats[0].text == "first" and beats[0].absolute_seconds == 5.0
        assert beats[1].text == "hello"

    def test_load_beats_rejects_empty(self, narrate_mod, tmp_path: Path) -> None:
        demo = tmp_path / "demo"
        demo.mkdir()
        (demo / "compiled.json").write_text(json.dumps({"narration": []}))
        with pytest.raises(ValueError, match="no narration beats"):
            narrate_mod.load_beats(demo / "compiled.json")

    def test_beat_clip_filename_is_content_addressed(self, narrate_mod) -> None:
        b1 = narrate_mod.Beat(scene_n=1, beat_n=1, absolute_seconds=0, text="hello")
        b2 = narrate_mod.Beat(scene_n=1, beat_n=1, absolute_seconds=0, text="HELLO")
        b3 = narrate_mod.Beat(scene_n=1, beat_n=1, absolute_seconds=0, text="hello")
        # Same text -> same filename (cache hit). Different text -> different.
        assert b1.clip_filename("voice") == b3.clip_filename("voice")
        assert b1.clip_filename("voice") != b2.clip_filename("voice")
        # Different voice -> different filename.
        assert b1.clip_filename("voiceA") != b1.clip_filename("voiceB")

    # --- W1: narrate.py coverage --------------------------------------------- #
    def test_load_beats_missing_file_raises_with_hint(
        self, narrate_mod, tmp_path: Path
    ) -> None:
        """Missing compiled.json must error with a message pointing at compile.py."""
        with pytest.raises(FileNotFoundError, match="compile.py"):
            narrate_mod.load_beats(tmp_path / "no-such-file.json")

    def test_mux_builds_expected_filter_complex(
        self, narrate_mod, tmp_path: Path, monkeypatch
    ) -> None:
        """ffmpeg invocation must emit one `adelay=Xms|Xms` per beat + amix."""
        captured: dict = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(narrate_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(narrate_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")

        beats = [
            narrate_mod.Beat(scene_n=1, beat_n=1, absolute_seconds=5.0, text="a"),
            narrate_mod.Beat(scene_n=2, beat_n=1, absolute_seconds=10.5, text="b"),
        ]
        clips = [tmp_path / f"c{i}.mp3" for i in range(2)]
        for c in clips:
            c.touch()
        in_v = tmp_path / "in.mp4"
        in_v.touch()
        out_v = tmp_path / "out.mp4"

        narrate_mod.mux(input_video=in_v, output_video=out_v, beats=beats, clip_paths=clips)

        cmd = captured["cmd"]
        idx = cmd.index("-filter_complex")
        fc = cmd[idx + 1]
        assert "[1:a]adelay=5000|5000[a1]" in fc, (
            f"missing scene-1 adelay (delay=5000ms): {fc}"
        )
        assert "[2:a]adelay=10500|10500[a2]" in fc, (
            f"missing scene-2 adelay (delay=10500ms): {fc}"
        )
        assert "amix=inputs=2" in fc
        # We deliberately do NOT pass -shortest so video stays full length.
        assert "-shortest" not in cmd

    def test_write_durations_round_trip_keys(
        self, narrate_mod, tmp_path: Path, monkeypatch
    ) -> None:
        """`voice/_durations.json` must be keyed `<scene_n>.<beat_n>` so the
        compile-side `_load_actual_durations` parser round-trips. Critical
        contract — drift here silently disables Stage 2 refinement.
        """
        # Mock ffprobe to return canned durations per call.
        durations_iter = iter([4.20, 6.13])

        def fake_run(cmd, **kw):
            d = next(durations_iter)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=f"{d}\n", stderr=""
            )

        monkeypatch.setattr(narrate_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(narrate_mod.shutil, "which", lambda _: "/usr/bin/ffprobe")

        beats = [
            narrate_mod.Beat(scene_n=4, beat_n=2, absolute_seconds=0, text="x"),
            narrate_mod.Beat(scene_n=999, beat_n=1, absolute_seconds=0, text="y"),
        ]
        clips = [tmp_path / "x.mp3", tmp_path / "y.mp3"]
        for c in clips:
            c.touch()

        narrate_mod.write_durations(tmp_path, beats, clips)

        out = json.loads((tmp_path / "voice" / "_durations.json").read_text())
        assert out == {"4.2": 4.20, "999.1": 6.13}

    def test_generate_clips_cache_hit_no_api_call(
        self, narrate_mod, tmp_path: Path, monkeypatch
    ) -> None:
        """When the cached clip exists and force=False, no ElevenLabs call fires.

        Mocks the SDK import so the test runs without the `elevenlabs` package
        installed and proves the SDK is never instantiated on a cache hit.
        """
        constructed: list = []

        class FakeClient:
            def __init__(self, *_, **__):
                constructed.append(True)
                raise AssertionError("ElevenLabs client constructed on cache hit")

        # narrate.py does `from elevenlabs.client import ElevenLabs` inside
        # generate_clips. Inject a fake module so that import resolves to
        # FakeClient without needing elevenlabs installed at test time.
        fake_module = type(sys)("elevenlabs")
        fake_client_module = type(sys)("elevenlabs.client")
        fake_client_module.ElevenLabs = FakeClient
        monkeypatch.setitem(sys.modules, "elevenlabs", fake_module)
        monkeypatch.setitem(sys.modules, "elevenlabs.client", fake_client_module)

        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        beat = narrate_mod.Beat(scene_n=1, beat_n=1, absolute_seconds=0, text="hello")
        voice_id = "fakevoice"
        # Pre-create the cached clip with the expected sha-hashed filename.
        (voice_dir / beat.clip_filename(voice_id)).write_bytes(b"cached")

        paths = narrate_mod.generate_clips(
            [beat], voice_dir,
            api_key="x", voice_id=voice_id,
            model_id="m", output_format="mp3_44100_128",
            force=False,
        )
        assert len(paths) == 1
        assert paths[0].read_bytes() == b"cached"
        assert constructed == [], "no SDK client should be constructed on cache hit"


# --------------------------------------------------------------------------- #
# Skill template                                                              #
# --------------------------------------------------------------------------- #
class TestScenesYamlTemplate:
    @pytest.fixture
    def template(self) -> Path:
        path = SKILL_TEMPLATES_DIR / "scenes.yaml.template"
        if not path.exists():
            pytest.skip(f"missing {path}")
        return path

    @pytest.mark.parametrize("key", ["title", "subtitle", "outro", "tape", "scenes"])
    def test_template_has_top_level_key(self, template: Path, key: str) -> None:
        text = template.read_text()
        assert re.search(rf"^{key}\s*:", text, re.MULTILINE), (
            f"scenes.yaml.template missing required top-level `{key}:` key — "
            "compile.py would fail at scaffold time for demos using this template."
        )

    def test_template_seeds_scene_1_as_clawctl_version(self, template: Path) -> None:
        """Parse the YAML and assert the first scene's actual `command:` field.

        Substring checks would pass on any comment containing `clawctl --version`
        — load the doc and inspect the structure directly.
        """
        import yaml as _yaml
        spec = _yaml.safe_load(template.read_text())
        first = spec["scenes"][0]
        assert first["n"] == 1, "Scene 1 must be numbered 1"
        assert first["command"] == "clawctl --version", (
            f"scenes.yaml.template Scene 1 command must be the fixed "
            f"`clawctl --version` opener; got {first['command']!r}."
        )

    def test_template_documents_long_output_elision(self, template: Path) -> None:
        """At least one example scene must declare both `head:` and `tail:`.

        Substring checks would pass on comments — load the YAML and walk
        the scene dicts to assert the actual keys.
        """
        import yaml as _yaml
        spec = _yaml.safe_load(template.read_text())
        scenes_with_both = [
            s for s in spec["scenes"]
            if "head" in s and "tail" in s
        ]
        assert scenes_with_both, (
            "scenes.yaml.template must include at least one scene declaring "
            "both `head:` and `tail:` keys so authors learn how to elide long "
            "captures (Ansible installs etc.)."
        )

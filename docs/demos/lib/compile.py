#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///
"""Compile a demo's `scenes.yaml` into a VHS tape + narration manifest.

Reads:  docs/demos/<demo-folder>/scenes.yaml + outputs/*.txt (captured stdouts)
Writes: docs/demos/<demo-folder>/tape.tape          (regenerated; do not hand-edit)
        docs/demos/<demo-folder>/compiled.json      (absolute narration timestamps)

The render pipeline is replay-first: every scene `cat`s a pre-captured output
file, with a designed `screen_seconds` Sleep. No live command execution at
record time, so recording duration is deterministic and narration timestamps
computed here are exact.

For long captures (Ansible installs, etc.) use `head:` and `tail:` to
elide the middle on screen — narration covers the gap.

Usage (deps auto-resolved via uv):
    uv run docs/demos/lib/compile.py docs/demos/<demo-folder>
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit(
        "missing dependency `pyyaml` — invoke via `uv run docs/demos/lib/compile.py ...` "
        "so uv resolves the PEP 723 dependencies declared at the top of the file."
    )

# --- timing model (must mirror what VHS records) -----------------------------
#
# Hide blocks: invisible in the recording AND skipped on the visible-time
# clock (verified empirically on the v1 quickstart demo: tape Hide block was
# ~74s of wall clock, recording's visible content started at t=0).
#
# Typing time: TypingSpeed * len(text).
#
# Sleep: exact wall-clock seconds added to the timeline.
#
# Enter / Hide / Show / Ctrl+D: instantaneous.
#
# Title card / Outro card / Headline / Progress: rendered as `Type "..."` +
# `Enter` + an explicit Sleep — accounted for via the same model.

DEFAULT_TYPING_MS = 50
DEFAULT_FRAMERATE = 30
DEFAULT_WIDTH = 1400
DEFAULT_HEIGHT = 900
DEFAULT_THEME = "Catppuccin Mocha"

# Designed beat durations (seconds).
HEADLINE_HOLD = 2.5
PROGRESS_HOLD = 2.5
TITLECARD_HOLD = 4.0
CHECKLIST_HOLD = 5.0
OUTROCARD_HOLD = 5.0
PRE_ROLL = 1.0
# 1s pause between Type-finished and Enter so the viewer has time to read the
# command before its output floods in.
COMMAND_TYPE_LAG = 1.0

# Audio timing model -------------------------------------------------------- #
# ElevenLabs at default speed renders English narration at roughly 14 chars
# per second (≈ 150 wpm). Slight under-estimate is intentional — better to
# leave a longer hold than to clip the tail of a clip mid-word.
#
# These are floors used by the "Stage 1" char-rate estimator. After
# `narrate.py` runs, it writes the real ffprobed durations to
# `<demo>/voice/_durations.json`; the next `compile.py` invocation reads
# that file and uses the actuals instead (Stage 2 refinement).
DEFAULT_AUDIO_CPS = 14.0
# Silence buffer guaranteed BETWEEN a beat's audio end and the next
# visual change (e.g. scene transition, progress check). Smaller = tighter
# demo but more risk of late voice tail bleeding into the next moment.
DEFAULT_NARRATION_BUFFER = 1.5


def _estimate_audio_seconds(text: str, cps: float) -> float:
    """Conservative estimate of TTS audio duration for `text` at `cps`."""
    return len(text) / cps if cps > 0 else 0.0


def _load_actual_durations(demo_dir: Path) -> dict[tuple[int, int], float]:
    """Read narrate.py's voice/_durations.json if present.

    Returns {(scene_n, beat_n): seconds}. Falls back to empty when the file
    is missing (first compile / before any narrate run).
    """
    f = demo_dir / "voice" / "_durations.json"
    if not f.exists():
        return {}
    raw = json.loads(f.read_text())
    out: dict[tuple[int, int], float] = {}
    for k, v in raw.items():
        try:
            s_str, b_str = k.split(".")
            out[(int(s_str), int(b_str))] = float(v)
        except (ValueError, TypeError):
            # Skip malformed entries silently — Stage 2 is best-effort polish.
            continue
    return out


@dataclass
class NarrationBeat:
    scene_n: int
    beat_n: int
    absolute_seconds: float
    text: str


@dataclass
class Compiled:
    title: str
    subtitle: str
    recording_duration_seconds: float
    narration: list[NarrationBeat] = field(default_factory=list)


def _typing_seconds(text: str, typing_ms: int) -> float:
    return len(text) * typing_ms / 1000


def _build_replay_dispatch(output_file: str, head: int | None, tail: int | None) -> str:
    """Return the shell expression the replay clawctl() wrapper runs for this scene."""
    if head and tail:
        return f"head -n {head} {output_file}; echo '   …'; tail -n {tail} {output_file}"
    if head:
        return f"head -n {head} {output_file}"
    if tail:
        return f"tail -n {tail} {output_file}"
    return f"cat {output_file}"


def _scene_block(
    scene_n: int,
    title: str,
    mode: str,
    command: str,
    screen_seconds: float,
    typing_ms: int,
) -> tuple[list[str], float, float]:
    """Return (tape_lines, scene_duration_seconds, command_output_t_offset)."""
    headline_text = f'headline {scene_n} "{title}"'
    progress_text = f"progress {scene_n}"

    lines: list[str] = [
        "",
        "# " + "=" * 60,
        f"# SCENE {scene_n} — {title}",
        f"# Mode: {mode}",
        "# " + "=" * 60,
        f"Type `{headline_text}`",
        "Enter",
        f"Sleep {HEADLINE_HOLD}s",
        "Hide",
        'Type "clear"',
        "Enter",
        "Show",
        f'Type "{command}"',
        f"Sleep {COMMAND_TYPE_LAG}s",
        "Enter",
        f"Sleep {screen_seconds}s",
        f'Type "{progress_text}"',
        "Enter",
        f"Sleep {PROGRESS_HOLD}s",
    ]

    # Time within scene at which command output begins to render:
    headline_typing = _typing_seconds(headline_text, typing_ms)
    command_typing = _typing_seconds(command, typing_ms)
    cmd_output_offset = (
        headline_typing
        + HEADLINE_HOLD
        + command_typing
        + COMMAND_TYPE_LAG
    )
    progress_typing = _typing_seconds(progress_text, typing_ms)
    scene_duration = (
        cmd_output_offset
        + screen_seconds
        + progress_typing
        + PROGRESS_HOLD
    )
    return lines, scene_duration, cmd_output_offset


def compile_demo(demo_dir: Path) -> tuple[Path, Path]:
    spec_path = demo_dir / "scenes.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"{spec_path} not found")
    spec: dict[str, Any] = yaml.safe_load(spec_path.read_text())

    title: str = spec["title"]
    subtitle: str = spec.get("subtitle", "")
    outro: dict[str, str] = spec.get("outro", {})
    outro_l1 = outro.get("line_1", "Thanks for watching!")
    outro_l2 = outro.get("line_2", "")

    tape_cfg: dict[str, Any] = spec.get("tape", {})
    typing_ms = int(tape_cfg.get("typing_speed_ms", DEFAULT_TYPING_MS))
    framerate = int(tape_cfg.get("framerate", DEFAULT_FRAMERATE))
    width = int(tape_cfg.get("width", DEFAULT_WIDTH))
    height = int(tape_cfg.get("height", DEFAULT_HEIGHT))
    theme = tape_cfg.get("theme", DEFAULT_THEME)
    audio_cps = float(tape_cfg.get("audio_cps", DEFAULT_AUDIO_CPS))
    narration_buffer = float(tape_cfg.get("narration_buffer_seconds", DEFAULT_NARRATION_BUFFER))
    output_format = str(tape_cfg.get("output_format", "mp4")).lower()
    if output_format not in ("mp4", "gif"):
        raise ValueError(
            f"tape.output_format must be 'mp4' or 'gif', got {output_format!r}"
        )
    recording_filename = f"recording.{output_format}"

    # Stage 2 refinement: real durations from prior narrate.py run, if any.
    actual_durations = _load_actual_durations(demo_dir)
    extension_warnings: list[str] = []

    def audio_seconds(scene_n: int, beat_n: int, text: str) -> float:
        """Actual ffprobed duration if available, else conservative estimate."""
        actual = actual_durations.get((scene_n, beat_n))
        return actual if actual is not None else _estimate_audio_seconds(text, audio_cps)

    def fit_hold(label: str, declared: float, narration_text: str, scene_n: int, beat_n: int) -> float:
        """Return max(declared, audio_duration + buffer); warn when extended."""
        if not narration_text:
            return declared
        audio = audio_seconds(scene_n, beat_n, narration_text)
        required = audio + narration_buffer
        if required > declared:
            extension_warnings.append(
                f"{label}: hold extended {declared:.1f}s → {required:.2f}s "
                f"(narration ≈ {audio:.2f}s + {narration_buffer:.1f}s buffer)"
            )
            return required
        return declared

    setup_steps: list[dict[str, Any]] = spec.get("setup", [])
    intro: dict[str, Any] = spec.get("intro", {})
    title_card_cfg = intro.get("title_card", {})
    checklist_cfg = intro.get("checklist", {})
    scenes: list[dict[str, Any]] = spec["scenes"]
    outro_cfg: dict[str, Any] = spec.get("outro_card", {"hold_seconds": OUTROCARD_HOLD})

    folder = demo_dir.name
    # Tape uses repo-root-relative paths so `vhs` runs from the repo root.
    # demo_dir is the absolute, resolved path for filesystem ops; build a
    # short repo-relative form for what we write INTO the tape.
    rel_demo = f"docs/demos/{folder}"
    helpers_path = f"{rel_demo}/helpers.sh"

    lines: list[str] = [
        f"# {title} — Long-Form Storyboarded Demo",
        f"# GENERATED FROM scenes.yaml — DO NOT EDIT BY HAND.",
        f"#   Edit scenes.yaml then re-run: uv run docs/demos/lib/compile.py {rel_demo}",
        "#",
        "# Records: title card -> checklist -> N scenes (replay) -> outro card.",
        f"# Output : {recording_filename} alongside this tape (gitignored).",
        "",
        "Require vhs",
        "",
        f"Output {rel_demo}/{recording_filename}",
        "",
        'Set Shell "bash"',
        "Set FontSize 18",
        f"Set Width {width}",
        f"Set Height {height}",
        f'Set Theme "{theme}"',
        "Set WindowBar Colorful",
        "Set Padding 20",
        "Set Margin 20",
        'Set MarginFill "#1e1e2e"',
        "Set BorderRadius 8",
        f"Set TypingSpeed {typing_ms}ms",
        f"Set Framerate {framerate}",
        "",
        "# --- Setup (hidden — NOT in recording timeline) ---",
        "Hide",
        'Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`',
        "Enter",
        "Sleep 500ms",
        f'Type `source "$(git rev-parse --show-toplevel)/{helpers_path}"`',
        "Enter",
        "Sleep 500ms",
    ]
    for step in setup_steps:
        cmd = step["run"]
        wait = float(step.get("wait_seconds", 1))
        lines.append(f'Type "{cmd}"')
        lines.append("Enter")
        lines.append(f"Sleep {wait}s")
    # AFTER live setup runs, install the replay override so scenes' typed
    # clawctl commands dispatch to cached outputs instead of executing.
    lines.extend([
        'Type "_replay_install"',
        "Enter",
        "Sleep 200ms",
        'Type "clear"',
        "Enter",
        "Sleep 300ms",
        "Show",
        "",
        "# Pre-roll so the first visible frame is not mid-action",
        f"Sleep {PRE_ROLL}s",
    ])

    # --- timing model: walk visible-time clock ---
    t = PRE_ROLL  # visible time elapsed after Show + pre-roll
    narration: list[NarrationBeat] = []

    # === TITLE CARD ===
    tc_hold_declared = float(title_card_cfg.get("hold_seconds", TITLECARD_HOLD))
    tc_narration_text = (title_card_cfg.get("narration") or "").strip()
    tc_hold = fit_hold("title_card", tc_hold_declared, tc_narration_text, 0, 1)
    lines.extend([
        "",
        "# === TITLE CARD ===",
        'Type "titlecard"',
        "Enter",
        f"Sleep {tc_hold}s",
    ])
    tc_typing = _typing_seconds("titlecard", typing_ms)
    titlecard_visible_t = t + tc_typing  # when card actually displays
    t += tc_typing + tc_hold
    if title_card_cfg.get("narration"):
        narration.append(NarrationBeat(
            scene_n=0, beat_n=1,
            absolute_seconds=round(titlecard_visible_t, 3),
            text=title_card_cfg["narration"].strip(),
        ))

    # === CHECKLIST ===
    cl_hold_declared = float(checklist_cfg.get("hold_seconds", CHECKLIST_HOLD))
    cl_narration_text = (checklist_cfg.get("narration") or "").strip()
    cl_hold = fit_hold("checklist", cl_hold_declared, cl_narration_text, 0, 2)
    lines.extend([
        "",
        "# === SCENARIO CHECKLIST (all pending) ===",
        'Type "progress 0"',
        "Enter",
        f"Sleep {cl_hold}s",
    ])
    cl_typing = _typing_seconds("progress 0", typing_ms)
    checklist_visible_t = t + cl_typing
    t += cl_typing + cl_hold
    if checklist_cfg.get("narration"):
        narration.append(NarrationBeat(
            scene_n=0, beat_n=2,
            absolute_seconds=round(checklist_visible_t, 3),
            text=checklist_cfg["narration"].strip(),
        ))

    # === SCENES ===
    # Every scene types its REAL command (so viewers see exactly what was run).
    # In replay mode (default), a shell function override installed by
    # `_replay_install` intercepts the command and prints the cached output.
    # In LIVE mode the command runs for real.
    for scene in scenes:
        scene_n = int(scene["n"])
        s_title = scene["title"]
        s_mode = scene.get("mode", "replay")
        screen_declared = float(scene.get("screen_seconds", 4))
        command = scene["command"]  # ALWAYS the visible real command

        # Fit screen_seconds so every narration beat for this scene has time
        # to finish playing before the scene transitions to `progress N`.
        # Per-beat: latest_audio_end = max(offset_seconds + audio_duration).
        scene_beats = scene.get("narration", []) or []
        latest_beat_end = 0.0
        for i, beat in enumerate(scene_beats, start=1):
            offset = float(beat.get("offset_seconds", 0))
            audio = audio_seconds(scene_n, i, beat["text"].strip())
            latest_beat_end = max(latest_beat_end, offset + audio)
            # Intra-scene overlap warning (compile doesn't auto-fix this —
            # offsets are author-driven; fixing them silently would change
            # the user's intended pacing).
            if i > 1:
                prev_beat = scene_beats[i - 2]
                prev_offset = float(prev_beat.get("offset_seconds", 0))
                prev_audio = audio_seconds(scene_n, i - 1, prev_beat["text"].strip())
                prev_end = prev_offset + prev_audio
                if offset < prev_end:
                    extension_warnings.append(
                        f"scene {scene_n} beat {i}: offset_seconds={offset:.1f}s "
                        f"starts BEFORE beat {i-1} ends at {prev_end:.2f}s "
                        f"(intra-scene overlap — increase this beat's offset_seconds)"
                    )

        required_screen = latest_beat_end + narration_buffer if latest_beat_end > 0 else screen_declared
        if required_screen > screen_declared:
            extension_warnings.append(
                f"scene {scene_n} ({s_title}): screen_seconds extended "
                f"{screen_declared:.1f}s → {required_screen:.2f}s "
                f"(narration runs to {latest_beat_end:.2f}s + {narration_buffer:.1f}s buffer)"
            )
            screen = required_screen
        else:
            screen = screen_declared

        scene_lines, scene_duration, cmd_output_offset = _scene_block(
            scene_n, s_title, s_mode, command, screen, typing_ms,
        )
        lines.extend(scene_lines)
        cmd_output_t = t + cmd_output_offset
        for i, beat in enumerate(scene_beats, start=1):
            offset = float(beat.get("offset_seconds", 0))
            narration.append(NarrationBeat(
                scene_n=scene_n, beat_n=i,
                absolute_seconds=round(cmd_output_t + offset, 3),
                text=beat["text"].strip(),
            ))
        t += scene_duration

    # === OUTRO CARD ===
    oc_hold_declared = float(outro_cfg.get("hold_seconds", OUTROCARD_HOLD))
    oc_narration_text = (outro_cfg.get("narration") or "").strip()
    oc_hold = fit_hold("outro_card", oc_hold_declared, oc_narration_text, 999, 1)
    lines.extend([
        "",
        "# === OUTRO CARD ===",
        'Type "outrocard"',
        "Enter",
        f"Sleep {oc_hold}s",
    ])
    oc_typing = _typing_seconds("outrocard", typing_ms)
    outrocard_visible_t = t + oc_typing
    t += oc_typing + oc_hold
    if outro_cfg.get("narration"):
        narration.append(NarrationBeat(
            scene_n=999, beat_n=1,
            absolute_seconds=round(outrocard_visible_t, 3),
            text=outro_cfg["narration"].strip(),
        ))

    # --- write outputs ---
    tape_path = demo_dir / "tape.tape"
    tape_path.write_text("\n".join(lines) + "\n")

    compiled = Compiled(
        title=title,
        subtitle=subtitle,
        recording_duration_seconds=round(t, 3),
        narration=sorted(narration, key=lambda b: b.absolute_seconds),
    )
    compiled_path = demo_dir / "compiled.json"
    compiled_path.write_text(
        json.dumps(
            {
                "title": compiled.title,
                "subtitle": compiled.subtitle,
                "recording_duration_seconds": compiled.recording_duration_seconds,
                "narration": [asdict(b) for b in compiled.narration],
            },
            indent=2,
        ) + "\n"
    )

    # Generate the per-demo helpers.sh too so the tape's `source` works.
    helpers_text = _build_helpers_sh(spec)
    helpers_file = demo_dir / "helpers.sh"
    helpers_file.write_text(helpers_text)

    return tape_path, compiled_path, extension_warnings, bool(actual_durations)


def _build_helpers_sh(spec: dict[str, Any]) -> str:
    """Emit the per-demo helpers.sh.

    Two parts:
    1. _SCENES/_TITLE/... assignments + source of lib/cards.sh (provides
       titlecard/headline/progress/outrocard functions).
    2. A `_replay_install` function the tape calls in its Hide block AFTER
       any live setup commands run. Once called, it overrides clawctl() to
       dispatch by exact command-line match against the YAML's `command:`
       fields and print the cached `output_file` (with optional head/tail
       elision). Calls to clawctl that don't match any scene print a clear
       error so misalignment fails loud at record time.
    """
    title = spec["title"]
    subtitle = spec.get("subtitle", "")
    outro = spec.get("outro", {})
    line1 = outro.get("line_1", "Thanks for watching!")
    line2 = outro.get("line_2", "")
    scenes = spec["scenes"]
    titles = [s["title"] for s in scenes]
    scenes_arr = "\n".join(f'  "{t}"' for t in titles)

    # Build the case statement body.
    case_arms: list[str] = []
    for s in scenes:
        if s.get("mode", "replay") == "LIVE":
            continue  # LIVE scenes run the real command — no override needed
        cmd = s["command"]
        if not cmd.startswith("clawctl "):
            # v1 only intercepts `clawctl`. Non-clawctl scenes must be LIVE.
            raise ValueError(
                f"Scene {s['n']}: replay-mode commands must start with `clawctl `; "
                f"got {cmd!r}. Mark this scene `mode: LIVE` or rewrite as clawctl."
            )
        args = cmd[len("clawctl "):]  # what we pattern-match on inside clawctl()
        out_file = s["output_file"]
        dispatch = _build_replay_dispatch(out_file, s.get("head"), s.get("tail"))
        case_arms.append(f'    "{args}") {dispatch} ;;')
    case_block = "\n".join(case_arms) if case_arms else "    # no replay scenes"

    return f"""# GENERATED FROM scenes.yaml — DO NOT EDIT BY HAND.
#   Edit scenes.yaml then re-run docs/demos/lib/compile.py.

_SCENES=(
{scenes_arr}
)

_TITLE="{title}"
_SUBTITLE="{subtitle}"
_OUTRO_LINE_1="{line1}"
_OUTRO_LINE_2="{line2}"

source "$(git rev-parse --show-toplevel)/docs/demos/lib/cards.sh"

# Install a clawctl() shell-function override that intercepts each scene's
# real command and prints its cached output. Call this AFTER any live setup
# clawctl invocations (e.g. `agent delete`) so those still hit the real CLI.
_replay_install() {{
  clawctl() {{
    local args="$*"
    case "$args" in
{case_block}
      *) echo "[replay] no match for: clawctl $args" >&2; return 1 ;;
    esac
  }}
}}
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("demo_folder", type=Path, help="docs/demos/YYYYMMDD-<slug>/")
    args = p.parse_args()

    demo = args.demo_folder.resolve()
    if not demo.is_dir():
        sys.exit(f"error: {demo} is not a directory")

    tape, manifest, warnings, used_actuals = compile_demo(demo)
    data = json.loads(manifest.read_text())

    print(f"compiled  → {tape}")
    print(f"compiled  → {manifest}")
    print(f"compiled  → {demo / 'helpers.sh'}")
    stage = "Stage 2 (ffprobed actuals)" if used_actuals else "Stage 1 (char-rate estimate)"
    print(f"audio sizing source: {stage}")
    if warnings:
        print()
        print(f"⚠ {len(warnings)} timing adjustment(s) to fit narration:")
        for w in warnings:
            print(f"  - {w}")
    print()
    print(f"recording duration: {data['recording_duration_seconds']}s")
    print(f"narration beats:    {len(data['narration'])}")
    print()
    print(f"{'scene':>5}  {'beat':>4}  {'t(s)':>7}  text")
    for b in data["narration"]:
        text = b["text"]
        if len(text) > 60:
            text = text[:57] + "..."
        print(f"{b['scene_n']:>5}  {b['beat_n']:>4}  {b['absolute_seconds']:>7.1f}  {text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

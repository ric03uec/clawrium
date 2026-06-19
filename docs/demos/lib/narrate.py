#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "elevenlabs>=1.0.0",
#   "python-dotenv>=1.0.0",
# ]
# ///
"""Layer ElevenLabs narration onto a VHS demo recording.

Reads narration text and per-scene start timecodes from the demo's
`storyboard.md`, generates one TTS clip per scene via the ElevenLabs API,
then muxes them into the recording at their declared start times with
ffmpeg.

Usage (uv resolves deps from the PEP 723 block at the top of this file):
    uv run docs/demos/lib/narrate.py docs/demos/<demo-folder>
        [--force]              # regenerate all scene mp3s even if cached
        [--regen 4,5]          # regenerate only listed scenes
        [--skip-mux]           # generate audio only; skip ffmpeg mux
        [--input recording.mp4 --output recording-narrated.mp4]

If the file is executable and uv is on PATH, it can also be invoked directly:
    docs/demos/lib/narrate.py docs/demos/<demo-folder>

Storyboard narration format (one line per scene under ## Narration):
    - Scene 1 (start=14s): "Running clawctl version 26.6.4..."
    - Scene 2 (start=36s): "First, initialize the clawrium service..."

Lines missing `(start=Xs)` or with an empty text payload (e.g. the literal
`…` placeholder shipped by the storyboard template) are skipped — useful
while drafting a demo before timecodes are known.

Config (docs/demos/lib/.env, gitignored):
    ELEVENLABS_API_KEY        required
    ELEVENLABS_VOICE_ID       required
    ELEVENLABS_MODEL_ID       optional — defaults to eleven_multilingual_v2
    ELEVENLABS_OUTPUT_FORMAT  optional — defaults to mp3_44100_128
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NARRATION_HEADING_RE = re.compile(r"^##\s+Narration\b", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)
NARRATION_LINE_RE = re.compile(
    r"""^\s*-\s+Scene\s+(\d+)\s*\(start\s*=\s*(\d+(?:\.\d+)?)\s*s\s*\)\s*:\s*(.+?)\s*$""",
    re.IGNORECASE,
)

LIB_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = LIB_DIR / ".env"
PLACEHOLDER_TEXT = {"", "…", "..."}


@dataclass(frozen=True)
class Scene:
    n: int
    start_seconds: float
    text: str

    @property
    def audio_name(self) -> str:
        return f"scene-{self.n:02d}.mp3"


def _load_env(env_file: Path) -> None:
    """Load .env values into os.environ unless already set in the shell."""
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        sys.exit(
            "missing dependency `python-dotenv` — invoke this script via "
            "`uv run docs/demos/lib/narrate.py ...` so uv resolves the "
            "PEP 723 dependencies declared at the top of the file."
        )
    load_dotenv(env_file, override=False)


def parse_narration(storyboard: Path) -> list[Scene]:
    """Return scenes ordered by scene number from `## Narration` in storyboard.md."""
    text = storyboard.read_text()
    start = NARRATION_HEADING_RE.search(text)
    if not start:
        raise ValueError(
            f"{storyboard} has no `## Narration` section — "
            "see docs/demos/lib/narrate.py docstring for the expected format."
        )
    after = text[start.end():]
    next_section = NEXT_HEADING_RE.search(after)
    body = after[: next_section.start()] if next_section else after

    scenes: dict[int, Scene] = {}
    for raw in body.splitlines():
        m = NARRATION_LINE_RE.match(raw)
        if not m:
            continue
        n = int(m.group(1))
        start_s = float(m.group(2))
        # Strip surrounding quotes (smart or straight) so authors can write
        # either `- Scene 1 (start=14s): "text"` or unquoted.
        spoken = m.group(3).strip().strip('"').strip("“”").strip("'")
        if spoken in PLACEHOLDER_TEXT:
            continue  # drafting; nothing to record yet
        if n in scenes:
            raise ValueError(
                f"{storyboard}: scene {n} declared twice in `## Narration` — "
                "deduplicate before re-running."
            )
        scenes[n] = Scene(n=n, start_seconds=start_s, text=spoken)
    if not scenes:
        raise ValueError(
            f"{storyboard}: `## Narration` section contains no scenes with "
            "both `(start=Xs)` and non-placeholder text yet. Fill in at least "
            "one scene before running."
        )
    return sorted(scenes.values(), key=lambda s: s.n)


def _parse_regen(spec: str | None) -> set[int]:
    if not spec:
        return set()
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.add(int(chunk))
        except ValueError as exc:
            raise SystemExit(f"--regen: invalid scene number `{chunk}`") from exc
    return out


def generate_clips(
    scenes: list[Scene],
    voice_dir: Path,
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    force: bool,
    regen: set[int],
) -> list[Path]:
    """Generate (or skip) per-scene mp3 files and return their paths in scene order."""
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        sys.exit(
            "missing dependency `elevenlabs` — invoke this script via "
            "`uv run docs/demos/lib/narrate.py ...` so uv resolves the "
            "PEP 723 dependencies declared at the top of the file."
        )
    client = ElevenLabs(api_key=api_key)
    voice_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    for scene in scenes:
        clip = voice_dir / scene.audio_name
        needs_gen = force or scene.n in regen or not clip.exists()
        if needs_gen:
            print(f"[narrate] scene {scene.n}: TTS ({len(scene.text)} chars)")
            audio = client.text_to_speech.convert(
                voice_id=voice_id,
                model_id=model_id,
                text=scene.text,
                output_format=output_format,
            )
            clip.write_bytes(b"".join(audio))
        else:
            print(f"[narrate] scene {scene.n}: cached")
        clip_paths.append(clip)
    return clip_paths


def mux(
    *,
    input_video: Path,
    output_video: Path,
    scenes: list[Scene],
    clip_paths: list[Path],
) -> None:
    """Mux scene clips onto input_video using ffmpeg adelay + amix."""
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH — install with: brew install ffmpeg | apt install ffmpeg")
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(input_video)]
    for clip in clip_paths:
        cmd.extend(["-i", str(clip)])

    # Build filter_complex: each input audio padded by adelay; all amixed.
    filter_parts: list[str] = []
    labels: list[str] = []
    for idx, scene in enumerate(scenes, start=1):
        delay_ms = int(round(scene.start_seconds * 1000))
        label = f"a{scene.n}"
        filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        labels.append(f"[{label}]")
    amix = f"{''.join(labels)}amix=inputs={len(scenes)}:duration=longest:normalize=0[aout]"
    filter_complex = ";".join(filter_parts + [amix])

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(output_video),
    ])
    print(f"[narrate] ffmpeg: muxing {len(scenes)} clips -> {output_video.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(f"ffmpeg failed (exit {result.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("demo_folder", type=Path, help="docs/demos/YYYYMMDD-<slug>/")
    parser.add_argument("--force", action="store_true", help="regenerate all scene mp3s")
    parser.add_argument("--regen", help="comma-separated scene numbers to regenerate, e.g. 4,5")
    parser.add_argument("--skip-mux", action="store_true", help="generate audio only; skip ffmpeg")
    parser.add_argument("--input", default="recording.mp4", help="input video filename inside demo folder")
    parser.add_argument("--output", default="recording-narrated.mp4", help="output filename inside demo folder")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_FILE, help="path to .env file")
    args = parser.parse_args()

    demo = args.demo_folder.resolve()
    if not demo.is_dir():
        return _fail(f"{demo} is not a directory")

    storyboard = demo / "storyboard.md"
    if not storyboard.exists():
        return _fail(f"{storyboard} not found")

    _load_env(args.env)

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
    output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128").strip()

    if not api_key:
        return _fail("ELEVENLABS_API_KEY is empty — fill in docs/demos/lib/.env")
    if not voice_id:
        return _fail("ELEVENLABS_VOICE_ID is empty — fill in docs/demos/lib/.env")

    scenes = parse_narration(storyboard)
    print(f"[narrate] storyboard: {len(scenes)} narrated scene(s)")

    voice_dir = demo / "voice"
    clip_paths = generate_clips(
        scenes,
        voice_dir,
        api_key=api_key,
        voice_id=voice_id,
        model_id=model_id,
        output_format=output_format,
        force=args.force,
        regen=_parse_regen(args.regen),
    )

    if args.skip_mux:
        print("[narrate] --skip-mux set; not running ffmpeg")
        _summary(scenes, clip_paths)
        return 0

    input_video = demo / args.input
    if not input_video.exists():
        return _fail(f"{input_video} not found — record the demo before narrating")
    output_video = demo / args.output

    mux(input_video=input_video, output_video=output_video, scenes=scenes, clip_paths=clip_paths)
    _summary(scenes, clip_paths, output_video=output_video)
    return 0


def _fail(msg: str) -> int:
    sys.stderr.write(f"error: {msg}\n")
    return 1


def _summary(scenes: list[Scene], clip_paths: list[Path], *, output_video: Path | None = None) -> None:
    print()
    print(f"{'scene':>5}  {'start':>7}  {'chars':>5}  {'size':>8}  file")
    for scene, clip in zip(scenes, clip_paths):
        size = clip.stat().st_size if clip.exists() else 0
        print(f"{scene.n:>5}  {scene.start_seconds:>6.1f}s  {len(scene.text):>5}  {size:>7,}B  {clip.name}")
    if output_video is not None and output_video.exists():
        print(f"\noutput: {output_video} ({output_video.stat().st_size:,} bytes)")


if __name__ == "__main__":
    raise SystemExit(main())

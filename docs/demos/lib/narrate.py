#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "elevenlabs>=1.0.0",
#   "python-dotenv>=1.0.0",
# ]
# ///
"""Layer ElevenLabs narration onto a VHS demo recording.

Reads `<demo-folder>/compiled.json` (produced by `compile.py` from
`scenes.yaml`). Each narration beat carries an absolute timestamp in the
rendered recording — no estimation, no skew.

For each beat: TTS-synthesize the text, cache the mp3 under `voice/`
(content-addressed by sha-1 of voice_id+text so editing text auto-
invalidates), then mux all clips into `recording.mp4` at their absolute
timestamps via ffmpeg adelay + amix.

Usage:
    uv run docs/demos/lib/narrate.py docs/demos/<demo-folder>
        [--force]              # regenerate all clips even if cached
        [--skip-mux]           # generate audio only; skip ffmpeg mux
        [--input recording.mp4 --output recording-narrated.mp4]

Config (docs/demos/lib/.env, gitignored):
    ELEVENLABS_API_KEY        required
    ELEVENLABS_VOICE_ID       required
    ELEVENLABS_MODEL_ID       optional — defaults to eleven_multilingual_v2
    ELEVENLABS_OUTPUT_FORMAT  optional — defaults to mp3_44100_128
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = LIB_DIR / ".env"


@dataclass(frozen=True)
class Beat:
    scene_n: int
    beat_n: int
    absolute_seconds: float
    text: str

    def clip_filename(self, voice_id: str) -> str:
        h = hashlib.sha1(f"{voice_id}|{self.text}".encode("utf-8")).hexdigest()[:12]
        return f"scene-{self.scene_n:02d}-beat-{self.beat_n:02d}-{h}.mp3"


def _load_env(env_file: Path) -> None:
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        sys.exit(
            "missing dependency `python-dotenv` — invoke via "
            "`uv run docs/demos/lib/narrate.py ...` so uv resolves the "
            "PEP 723 dependencies declared at the top of the file."
        )
    load_dotenv(env_file, override=False)


def load_beats(compiled_json: Path) -> list[Beat]:
    if not compiled_json.exists():
        raise FileNotFoundError(
            f"{compiled_json} not found — run `uv run docs/demos/lib/compile.py "
            f"{compiled_json.parent}` first."
        )
    data = json.loads(compiled_json.read_text())
    beats = [
        Beat(
            scene_n=int(b["scene_n"]),
            beat_n=int(b["beat_n"]),
            absolute_seconds=float(b["absolute_seconds"]),
            text=str(b["text"]).strip(),
        )
        for b in data.get("narration", [])
    ]
    if not beats:
        raise ValueError(f"{compiled_json}: no narration beats")
    return sorted(beats, key=lambda b: b.absolute_seconds)


def generate_clips(
    beats: list[Beat],
    voice_dir: Path,
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    force: bool,
) -> list[Path]:
    voice_dir.mkdir(parents=True, exist_ok=True)
    client = None  # lazy — only constructed when an actual TTS call is needed

    clip_paths: list[Path] = []
    for beat in beats:
        clip = voice_dir / beat.clip_filename(voice_id)
        if force or not clip.exists():
            if client is None:
                try:
                    from elevenlabs.client import ElevenLabs
                except ImportError:
                    sys.exit(
                        "missing dependency `elevenlabs` — invoke via "
                        "`uv run docs/demos/lib/narrate.py ...` so uv resolves the "
                        "PEP 723 dependencies declared at the top of the file."
                    )
                client = ElevenLabs(api_key=api_key)
            print(f"[narrate] scene {beat.scene_n} beat {beat.beat_n}: TTS ({len(beat.text)} chars)")
            audio = client.text_to_speech.convert(
                voice_id=voice_id,
                model_id=model_id,
                text=beat.text,
                output_format=output_format,
            )
            clip.write_bytes(b"".join(audio))
        else:
            print(f"[narrate] scene {beat.scene_n} beat {beat.beat_n}: cached")
        clip_paths.append(clip)
    return clip_paths


def write_durations(demo_dir: Path, beats: list[Beat], clip_paths: list[Path]) -> None:
    """Probe each generated clip with ffprobe and write voice/_durations.json.

    Consumed by compile.py's Stage 2 refinement: on the next compile, the
    char-rate estimate is replaced with these actual per-clip durations
    so sleeps are tightened or extended to the real audio length.
    Keyed by `<scene_n>.<beat_n>` so the lookup is voice-agnostic.
    """
    if shutil.which("ffprobe") is None:
        # ffprobe ships with ffmpeg; if missing, narrate.py wouldn't reach mux either.
        return
    out: dict[str, float] = {}
    for beat, clip in zip(beats, clip_paths):
        if not clip.exists():
            continue
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(clip)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            continue
        try:
            dur = float(result.stdout.strip())
        except ValueError:
            continue
        out[f"{beat.scene_n}.{beat.beat_n}"] = round(dur, 3)
    target = demo_dir / "voice" / "_durations.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")


def mux(
    *,
    input_video: Path,
    output_video: Path,
    beats: list[Beat],
    clip_paths: list[Path],
) -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH")
    cmd: list[str] = ["ffmpeg", "-y", "-i", str(input_video)]
    for clip in clip_paths:
        cmd.extend(["-i", str(clip)])

    filter_parts: list[str] = []
    labels: list[str] = []
    for idx, beat in enumerate(beats, start=1):
        delay_ms = int(round(beat.absolute_seconds * 1000))
        label = f"a{idx}"
        filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        labels.append(f"[{label}]")
    amix = f"{''.join(labels)}amix=inputs={len(beats)}:duration=longest:normalize=0[aout]"
    filter_complex = ";".join(filter_parts + [amix])

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        # No -shortest: keep video at full length so the outro card survives.
        str(output_video),
    ])
    print(f"[narrate] ffmpeg: muxing {len(beats)} beat(s) -> {output_video.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(f"ffmpeg failed (exit {result.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("demo_folder", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-mux", action="store_true")
    parser.add_argument("--input", default="recording.mp4")
    parser.add_argument("--output", default="recording-narrated.mp4")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_FILE)
    args = parser.parse_args()

    demo = args.demo_folder.resolve()
    if not demo.is_dir():
        return _fail(f"{demo} is not a directory")

    compiled_json = demo / "compiled.json"
    _load_env(args.env)

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2").strip()
    output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128").strip()

    if not api_key:
        return _fail("ELEVENLABS_API_KEY is empty — fill in docs/demos/lib/.env")
    if not voice_id:
        return _fail("ELEVENLABS_VOICE_ID is empty — fill in docs/demos/lib/.env")

    beats = load_beats(compiled_json)
    print(f"[narrate] compiled.json: {len(beats)} narration beat(s)")

    voice_dir = demo / "voice"
    clip_paths = generate_clips(
        beats, voice_dir,
        api_key=api_key, voice_id=voice_id,
        model_id=model_id, output_format=output_format,
        force=args.force,
    )

    # Always probe + write _durations.json so the next compile.py picks up
    # actual ffprobed durations (Stage 2 refinement).
    write_durations(demo, beats, clip_paths)

    if args.skip_mux:
        print("[narrate] --skip-mux set; not running ffmpeg")
        _summary(beats, clip_paths)
        return 0

    input_video = demo / args.input
    if not input_video.exists():
        return _fail(f"{input_video} not found — `vhs tape.tape` first")
    output_video = demo / args.output

    mux(input_video=input_video, output_video=output_video, beats=beats, clip_paths=clip_paths)
    _summary(beats, clip_paths, output_video=output_video)
    return 0


def _fail(msg: str) -> int:
    sys.stderr.write(f"error: {msg}\n")
    return 1


def _summary(beats: list[Beat], clip_paths: list[Path], *, output_video: Path | None = None) -> None:
    print()
    print(f"{'scene':>5}  {'beat':>4}  {'t(s)':>7}  {'chars':>5}  {'size':>8}  clip")
    for beat, clip in zip(beats, clip_paths):
        size = clip.stat().st_size if clip.exists() else 0
        print(f"{beat.scene_n:>5}  {beat.beat_n:>4}  {beat.absolute_seconds:>7.1f}  {len(beat.text):>5}  {size:>7,}B  {clip.name}")
    if output_video is not None and output_video.exists():
        print(f"\noutput: {output_video} ({output_video.stat().st_size:,} bytes)")


if __name__ == "__main__":
    raise SystemExit(main())

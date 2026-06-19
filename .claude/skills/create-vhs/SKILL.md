---
name: create-vhs
description: Record a CLI demo (GIF or MP4) using VHS via a replay-first compile pipeline. Outputs are captured once on a live host, then a YAML spec drives both the tape and the ElevenLabs voiceover.
argument-hint: "<scenario-name> [--description 'what to demo']"
---

# Demo Recording with VHS — replay-first pipeline

Record CLI demos using [charmbracelet/vhs](https://github.com/charmbracelet/vhs). Each demo lives in its own dated-slug folder `docs/demos/YYYYMMDD-<slug>/`. The pipeline is **replay-first**: captured stdouts are saved once on a live host, then a YAML spec drives tape generation, recording, and narration. Iteration is fast and timing is deterministic.

## Pipeline

```
              (one-time, slow)
   scenes.yaml + live host  -->  outputs/*.txt       [capture phase]
                                          |
              (instant)                   v
   scenes.yaml  +  outputs/*.txt  -->  compile.py  -->  tape.tape + helpers.sh + compiled.json
                                          |
              (~2 min)                    v
                                       vhs tape.tape  -->  recording.mp4
                                          |
              (~30s, cached per text)     v
                                       narrate.py compiled.json  -->  voice/*.mp3 + recording-narrated.mp4
                                          |
              (manual)                    v
                                       upload to YouTube
```

`compile.py`, `vhs`, and `narrate.py` are all idempotent and fast. The slow step is the initial capture; everything downstream re-runs in seconds.

## Output Layout

| Path | Committed? | Purpose |
|---|---|---|
| `docs/demos/lib/cards.sh` | yes | Shared titlecard/outrocard/headline/progress ANSI functions |
| `docs/demos/lib/compile.py` | yes | `scenes.yaml → tape.tape + helpers.sh + compiled.json` |
| `docs/demos/lib/narrate.py` | yes | `compiled.json + .env → voice/*.mp3 + recording-narrated.mp4` |
| `docs/demos/lib/.env.example` | yes | Template for ElevenLabs credentials |
| `docs/demos/lib/.env` | **no** (gitignored) | Real API key + voice/model IDs |
| `docs/demos/YYYYMMDD-<slug>/scenes.yaml` | yes | **Single source of truth** — scene structure, commands, narration |
| `docs/demos/YYYYMMDD-<slug>/outputs/NN-<slug>.txt` | yes | Per-scene captured stdouts (replayed by the tape) |
| `docs/demos/YYYYMMDD-<slug>/tape.tape` | yes | **Generated** by compile.py; do not hand-edit |
| `docs/demos/YYYYMMDD-<slug>/helpers.sh` | yes | **Generated** by compile.py; sources `lib/cards.sh` |
| `docs/demos/YYYYMMDD-<slug>/compiled.json` | yes | **Generated** by compile.py; absolute narration timestamps |
| `docs/demos/YYYYMMDD-<slug>/voice/*.mp3` | **no** (gitignored) | Per-beat TTS clips, cached by sha1(voice_id + text) |
| `docs/demos/YYYYMMDD-<slug>/recording.mp4` | **no** (gitignored) | Output of `vhs tape.tape` |
| `docs/demos/YYYYMMDD-<slug>/recording-narrated.mp4` | **no** (gitignored) | Final video with voiceover muxed in |

All `.mp4` files under `docs/demos/` are gitignored; `voice/` directories under any demo are gitignored.

## Arguments

- `<scenario-name>`: Slug for the demo (e.g. `agent-lifecycle`). Must match `^[a-zA-Z0-9_-]+$`. The skill prefixes today's date in `YYYYMMDD` form to produce `docs/demos/YYYYMMDD-<scenario-name>/`.
- `--description`: Optional one-liner of what the demo should show.

## Required Up-Front Questions

**MANDATORY**: Before scaffolding any file, ask the user the following via `AskUserQuestion`. Do **not** assume defaults.

1. **Output format**
   - **MP4** (`.mp4`) — recommended; YouTube uploads, social, video containers.
   - **GIF** (`.gif`) — README/docs embeds. Smaller, no audio.

2. **Scene plan** — ordered list of scene titles + commands. Scene 1 is fixed as `clawctl --version`; ask only for Scene 2 onward.

3. **Long-output handling per scene** — for any scene whose command produces tens or hundreds of lines (Ansible installs, etc.), confirm whether to `head N` + `tail M` elide the middle. The narration covers the gap.

4. **Any other unclear input** — never invent prerequisites.

## Universal Flow

### Step 1 — Run the prereq validator

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/create-vhs/scripts/check-prereqs.sh"
```

Checks `vhs`, `ttyd`, `ffmpeg`, `clawctl`. Stop immediately if any are missing.

### Step 2 — Author `scenes.yaml`

Copy `.claude/skills/create-vhs/templates/scenes.yaml.template` to `docs/demos/YYYYMMDD-<scenario-name>/scenes.yaml` and fill in title, subtitle, intro/outro narration, and the scene list.

**Fixed Scene 1**: `clawctl --version`. Leave it in place. It anchors the recording to a known release.

For long scenes use `head:` and `tail:` to elide the middle on screen — narration covers the elision.

**Get explicit user approval on `scenes.yaml`** before capturing outputs.

### Step 3 — Capture stdouts (one-time, on a live host)

For each scene with `mode: replay` (default), run the real command once and save its stdout into the demo's `outputs/` folder:

```bash
NAME=YYYYMMDD-<scenario-name>
mkdir -p docs/demos/$NAME/outputs

clawctl --version                 | tee docs/demos/$NAME/outputs/01-version.txt
clawctl service init              | tee docs/demos/$NAME/outputs/02-service-init.txt
# ... one per scene ...
```

Mask non-deterministic values (timestamps, UUIDs, IPs, private hostnames) before committing the capture files. A scripted sed pass is fine:

```bash
sed -i -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+/2026-01-01T00:00:00Z/g' docs/demos/$NAME/outputs/*.txt
```

**Re-capture cadence**: per release tag, after Rich table changes, or whenever the CLI's output shape shifts.

### Step 4 — Compile

```bash
uv run docs/demos/lib/compile.py docs/demos/YYYYMMDD-<scenario-name>
```

uv resolves the PEP 723 deps (`pyyaml`) on first run. Outputs:
- `tape.tape` — replay-first VHS source. Header banner says "GENERATED — DO NOT EDIT".
- `helpers.sh` — per-demo `_SCENES`/`_TITLE`/... + sources `lib/cards.sh`.
- `compiled.json` — flat list of every narration beat with its absolute timestamp in the rendered recording.

The script prints the recording duration estimate and a per-beat timeline. Verify these match what you expect before recording.

### Step 5 — Record

```bash
export PATH="${GOPATH:-$HOME/go}/bin:$PATH"
vhs docs/demos/YYYYMMDD-<scenario-name>/tape.tape
```

Output lands at `docs/demos/YYYYMMDD-<scenario-name>/recording.mp4`. Replay-first tapes run in roughly their on-screen duration (no live waits), so recording time ≈ recording duration.

### Step 6 — Layer narration (ElevenLabs)

**One-time setup per machine:**

```bash
cp docs/demos/lib/.env.example docs/demos/lib/.env
# Edit and fill in ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID.
```

`narrate.py` declares its Python deps via PEP 723. uv resolves on first invocation; no `pip` step.

**Run:**

```bash
uv run docs/demos/lib/narrate.py docs/demos/YYYYMMDD-<scenario-name>
  [--force]              # regenerate ALL clips even if cached
  [--skip-mux]           # generate audio only; skip ffmpeg
  [--input recording.mp4 --output recording-narrated.mp4]
```

- Reads `compiled.json` (not `scenes.yaml` — narrate.py only consumes derived artifacts).
- TTS-synthesizes each beat; clips are cached at `voice/<scene>-<beat>-<sha1>.mp3`. Editing a beat's text changes the sha and auto-invalidates the cache — no `--regen` flag needed.
- Muxes onto `recording.mp4` via ffmpeg `adelay + amix`. Video is `-c:v copy` (no re-encode).

### Step 7 — Iterate

| Change | Re-run |
|---|---|
| Narration text only | `compile.py` + `narrate.py` (~30s; vhs not needed) |
| Scene order / scene structure / new scene | `compile.py` + `vhs` + `narrate.py` |
| Captured output diverged from CLI | re-do Step 3 capture + Step 4+ |
| New scene with a new command | add to scenes.yaml + capture + compile + vhs + narrate |

### Step 8 — Upload (out of skill scope)

You upload `recording-narrated.mp4` (or `recording.mp4` if going voiceless) to YouTube. The skill does not push.

## Configuration

`narrate.py` honors these env vars from `docs/demos/lib/.env`:

| Var | Required | Default |
|---|---|---|
| `ELEVENLABS_API_KEY` | yes | — |
| `ELEVENLABS_VOICE_ID` | yes | — |
| `ELEVENLABS_MODEL_ID` | no | `eleven_multilingual_v2` |
| `ELEVENLABS_OUTPUT_FORMAT` | no | `mp3_44100_128` |

Shell env vars override `.env` values.

## VHS Commands Reference (for generated tapes)

The compile.py output is hand-readable. Commands you'll see in generated tapes:

| Command | Notes |
|---|---|
| `Output` | First line; absolute path under `docs/demos/<demo>/recording.mp4` |
| `Require vhs` | Fail-fast validation |
| `Set` | Tape-level config — must be at the top, not mid-tape (VHS ignores mid-tape `Set` with a warning) |
| `Type "text"` | Types text |
| `Enter` | Presses Enter |
| `Sleep Ns` | Pauses N seconds. Compound durations like `4m30s` are NOT supported — use `270s` |
| `Hide` / `Show` | Bracket invisible commands. **Hide blocks DO NOT advance the recording timeline.** |

> ⚠️ **Never use `Env` with real credentials.** VHS bakes the literal value into the committed tape.

## Production Quality (research-backed)

- **Pre-roll & post-roll**: `Sleep 1s` (pre-roll) is auto-emitted by compile.py. Outro card has a 5s hold.
- **Vary typing speed**: default `Set TypingSpeed 50ms` is in the YAML `tape.typing_speed_ms`.
- **Mask non-deterministic output** in captured replay files. Done at capture time (Step 3).
- **Long Ansible logs**: use `head:` + `tail:` in scenes.yaml. Narration covers the elision.
- **One demo = one fleet state.** Don't combine `create` and `remove` in one tape — second half would need a different captured starting state.

## Troubleshooting

| Problem | Solution |
|---|---|
| `clawctl` not found inside the tape | Hidden setup sources the venv — confirm `docs/demos/lib/cards.sh` is being sourced |
| Helper functions not found | Confirm `source ... helpers.sh` is inside the Hide block (auto-emitted by compile.py) |
| GIF too large | Lower `tape.framerate` in scenes.yaml, trim long `screen_seconds`, or add `head:`/`tail:` to long scenes |
| Output truncated | Increase `tape.height` for long-form (default 900) |
| Tables misaligned | `tape.width` ≥ 1400 |
| Capture file missing | Re-do Step 3 capture for that scene |
| ElevenLabs sync drift | All narration beats use absolute timestamps from compile.py. If drift is real, edit `screen_seconds` or `offset_seconds` in scenes.yaml + recompile |

## File Organization

```
docs/demos/
├── lib/                              # committed — shared, all demos
│   ├── cards.sh                      # titlecard / outrocard / headline / progress
│   ├── compile.py                    # scenes.yaml -> tape.tape + helpers.sh + compiled.json (PEP 723; run via `uv run`)
│   ├── narrate.py                    # compiled.json -> voice/*.mp3 + recording-narrated.mp4 (PEP 723; run via `uv run`)
│   ├── .env.example                  # ElevenLabs credentials template
│   └── .env                          # GITIGNORED — real ELEVENLABS_API_KEY etc.
└── YYYYMMDD-<slug>/                  # one folder per demo
    ├── scenes.yaml                   # committed — SOURCE OF TRUTH
    ├── outputs/                      # committed — per-scene captures
    │   ├── 01-version.txt
    │   └── 02-….txt
    ├── tape.tape                     # committed (generated) — VHS source
    ├── helpers.sh                    # committed (generated) — per-demo vars + source lib/cards.sh
    ├── compiled.json                 # committed (generated) — narration timeline
    ├── voice/                        # GITIGNORED — per-beat TTS clips
    │   └── scene-NN-beat-MM-<sha8>.mp3
    ├── recording.mp4                 # GITIGNORED — output of `vhs tape.tape`
    └── recording-narrated.mp4        # GITIGNORED — recording with voiceover
```

## References

External best-practice sources consulted for this skill:

- [charmbracelet/vhs README](https://github.com/charmbracelet/vhs)
- [VHS canonical demo.tape](https://github.com/charmbracelet/vhs/blob/main/examples/demo.tape)
- [Tips and tricks from VHS tapes (gist)](https://gist.github.com/andyfeller/3104a42bc367831e2d5f3910bde6cf2e)
- [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python)
- [Automated YouTube dubbing with ElevenLabs + ffmpeg](https://uhiyama-lab.com/en/blog/video-edit/elevenlabs-youtube-dubbing-workflow/)
- [PEP 723 — inline script metadata](https://peps.python.org/pep-0723/)

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/03_DEMO.md` if recording as part of an issue.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

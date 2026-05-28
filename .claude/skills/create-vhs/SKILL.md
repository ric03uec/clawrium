---
name: create-vhs
description: Record a CLI demo (GIF or MP4) using VHS, with storyboard support for long-form / YouTube demos
argument-hint: "<scenario-name> [--description 'what to demo']"
---

# Demo Recording with VHS

Record CLI demos using [charmbracelet/vhs](https://github.com/charmbracelet/vhs). Tape sources, storyboards, helper scripts, and captured outputs are committed under `docs/demos/`. The final rendered recording (GIF/MP4) lands in `docs/demos/recordings/`, which is **gitignored** — users upload MP4s to YouTube; the binary itself does not live in the repo.

## Output Layout

| Path                                       | Committed? | Purpose                                              |
|--------------------------------------------|------------|------------------------------------------------------|
| `docs/demos/<name>.tape`                   | yes        | Reproducible source for the recording                |
| `docs/demos/<name>.storyboard.md`          | yes (long-form) | Scene list, narration, capture index            |
| `docs/demos/_<name>_helpers.sh`            | yes (long-form) | `titlecard` / `outrocard` / `headline` / `progress` |
| `docs/demos/<name>/outputs/NN-<slug>.txt`  | yes (replay scenes) | Pre-captured command output replayed via `cat` |
| `docs/demos/recordings/<name>.{mp4,gif}`   | **no** (gitignored) | Rendered recording — uploaded to YouTube       |

## Arguments

- `<scenario-name>`: Slug used for the tape, helper, storyboard, and output (e.g. `agent-lifecycle`, `host-setup`). Must match `^[a-zA-Z0-9_-]+$`.
- `--description`: Optional one-liner of what the demo should show.

## Required Up-Front Questions

**MANDATORY**: Before writing any file, ask the user the following via `AskUserQuestion`. Do **not** assume defaults — wait for explicit answers.

1. **Output format**
   - **MP4** (`.mp4`) — default for YouTube uploads, social, anywhere a video container is required. Better compression. Recommended.
   - **GIF** (`.gif`) — for embedding in README/docs on GitHub. Smaller, autoplay-in-markdown, no audio.

2. **Demo style** — count the scenes the user wants to show:
   - **Short** (≤3 scenes) — minimal flow, no storyboard, no helper script. README hero pattern.
   - **Long-form** (≥4 scenes) — storyboarded with scene list, progress checklist, title/outro cards, helper script. YouTube tutorial pattern.

3. **Execution model** (long-form only):
   - **Replay-first** (default, recommended) — capture command output to text files once, replay via `cat` during recording. Deterministic; recording doesn't need live infra; collapses minute-long ops into instant frames. Document `# LIVE` exceptions per-scene in the storyboard.
   - **All live** — every scene runs the real command at record time. Slower; requires the target fleet to be in the right state.

4. **Scene plan** (long-form only) — ask the user for an ordered list of scene titles, the command shown in each, and which scenes are `LIVE` (interactive TUIs like `agent chat` cannot be replayed). Stop after scaffolding the storyboard and get explicit user approval before generating the helper script and tape.

5. **Any other unclear input** — if the user's scenario name, scope, or prerequisites are ambiguous, ask before scaffolding. Never invent prerequisites.

## Prerequisites

Verify dependencies once per invocation:

```bash
VHS_BIN="${VHS_BIN:-$(command -v vhs || true)}"
TTYD_BIN="${TTYD_BIN:-$(command -v ttyd || true)}"
FFMPEG_BIN="${FFMPEG_BIN:-$(command -v ffmpeg || true)}"

for bin in "$VHS_BIN" "$TTYD_BIN" "$FFMPEG_BIN"; do
  if [ -z "$bin" ] || [ ! -x "$bin" ]; then
    echo "MISSING dependency. Install:"
    echo "  VHS:    go install github.com/charmbracelet/vhs@latest"
    echo "  ttyd:   brew install ttyd | apt install ttyd | https://github.com/tsl0922/ttyd/releases"
    echo "  ffmpeg: brew install ffmpeg | apt install ffmpeg"
    exit 1
  fi
done
```

> `ttyd` is upstream `tsl0922/ttyd` (a C project). No `go install` path — use a package manager or the official binary release.

In addition, every tape **MUST** declare its own runtime prerequisites with `Require` directives at the top — VHS validates these before recording (`Require vhs`, `Require clawctl`, etc.).

## Configuration

```bash
ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
if [ -f "$ITX_CONFIG" ]; then
  VENV_PATH=$(jq -r '.demo.venv_path // ".venv/bin/activate"' "$ITX_CONFIG")
  VHS_PATH=$(jq -r '.demo.vhs_path // "vhs"' "$ITX_CONFIG")
else
  VENV_PATH=".venv/bin/activate"
  VHS_PATH="vhs"
fi
```

Customize in `.claude/itx-config.json`:

```json
{
  "demo": {
    "venv_path": ".venv/bin/activate",
    "vhs_path": "vhs"
  }
}
```

---

## Flow A — Short Demo (≤3 scenes)

For README hero GIFs and quick captures. No storyboard, no helper script.

### 1. Plan

- 2–3 commands max.
- Run each command manually first to confirm it works and to size `Sleep` durations.
- Decide whether the demo needs live infra or can stand alone.

### 2. Write the tape

Create `docs/demos/<scenario-name>.tape`:

```tape
# <Title>
# Records: <what commands are shown>
# Requires: <prerequisites, e.g., "a configured fleet">

Require vhs
Require clawctl

Output docs/demos/recordings/<scenario-name>.<ext>   # <ext> = mp4 (YouTube) or gif (README)

Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 600
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set Padding 20
Set Margin 20
Set MarginFill "#1e1e2e"
Set BorderRadius 8
Set TypingSpeed 50ms
Set Framerate 30

# Activate project environment (hidden from recording).
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 1s
Show

# Pre-roll so the first frame is not mid-action
Sleep 1s

# <Comment describing first command>
Type "<command>"
Sleep 300ms
Enter
Sleep 3s

# <Comment describing second command>
Type "<command>"
Sleep 300ms
Enter
Sleep 3s
```

### 3. Record

```bash
SCENARIO="<scenario-name>"
[[ "$SCENARIO" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid scenario name: $SCENARIO"; exit 1; }
export PATH="${GOPATH:-$HOME/go}/bin:$PATH"
"$VHS_PATH" "docs/demos/${SCENARIO}.tape"
```

### 4. Validate

```bash
ls -lh docs/demos/recordings/<scenario-name>.*
```

- GIF for README: target **< 500 KiB**.
- GIF for docs: target **< 3 MiB**.
- MP4: no size cap (uploaded externally); still verify it plays and the output is legible.
- Open in a viewer to confirm output is readable end-to-end.

### 5. Reference (GIF only)

For README embed:
```markdown
<p align="center">
  <img src="docs/demos/recordings/<scenario-name>.gif" alt="<description>" width="100%">
</p>
```

> ⚠️ Since `docs/demos/recordings/` is gitignored, GIFs referenced from README are **not committed**. Either (a) record locally and host the GIF on a CDN / GitHub release asset, or (b) explicitly opt out of the gitignore for that one file: `!docs/demos/recordings/readme.gif` in `.gitignore`. The skill does NOT auto-decide; ask the user.

---

## Flow B — Long-Form Storyboarded Demo (≥4 scenes)

For YouTube tutorials and product walkthroughs. Replay-first by default.

### 1. Write the storyboard first

Copy `.claude/skills/create-vhs/templates/storyboard.md.template` to `docs/demos/<name>.storyboard.md`, fill in the scene table, and **get the user's explicit approval** before generating anything else.

The storyboard must list, per scene: title, command, mode (`replay` / `LIVE`), capture filename, narration line (optional).

### 2. Capture command outputs (replay scenes)

For every scene marked `replay`, run the real command once and save its stdout to a file:

```bash
NAME="<scenario-name>"
mkdir -p docs/demos/$NAME/outputs

# One line per scene; number = scene index, slug = scene title kebab-cased.
clawctl agent get                                  | tee docs/demos/$NAME/outputs/01-fleet.txt
clawctl provider registry get                      | tee docs/demos/$NAME/outputs/02-providers.txt
clawctl provider registry describe clawrium-glm51  | tee docs/demos/$NAME/outputs/03-describe.txt
# ... etc, one per replay scene ...
```

**Mask non-deterministic values** before committing — timestamps, UUIDs, IPs, real hostnames. A scripted pass is fine:

```bash
sed -i -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+/2026-01-01T00:00:00Z/g' docs/demos/$NAME/outputs/*.txt
```

Replay-first trade-off (call out explicitly to the user):

- ✅ Recording is deterministic and re-runs without infra.
- ✅ A 3-minute `agent create` becomes an instant `cat` — Sleep is now purely for visual pacing.
- ⚠️ Captured output drifts when CLI output format changes. Re-capture per release tag, or after any change to Rich table layout / column order / status strings.
- ❌ Interactive scenes (TUIs, `agent chat`, anything keystroke-driven) **cannot** be replayed. Mark them `LIVE` in the storyboard.

### 3. Generate the helper script

Copy `.claude/skills/create-vhs/templates/_progress.sh.template` to `docs/demos/_<name>_helpers.sh`. Fill in:

- `_SCENES=(...)` — must match the storyboard scene list, in order.
- `_TITLE`, `_SUBTITLE`, `_OUTRO_LINE_1`, `_OUTRO_LINE_2`.

Syntax-check it:

```bash
bash -n docs/demos/_<name>_helpers.sh
```

### 4. Generate the tape

Copy `.claude/skills/create-vhs/templates/long-form.tape.template` to `docs/demos/<name>.tape`. For every scene block, fill in:

- Scene number and title (must match storyboard).
- Either `Type "cat docs/demos/<name>/outputs/NN-<slug>.txt"` (replay) **or** the real command (LIVE).
- `Sleep` duration — size it to the captured output's natural read time (~1.5–3s for short tables, 5–8s for longer output).

Standard settings (built into the template — deviate only with a reason commented in the tape header):

| Setting       | Value              | Rationale                                              |
|---------------|--------------------|--------------------------------------------------------|
| FontSize      | 18                 | Readable on 1080p YouTube                              |
| Width         | 1400               | Fits `clm` tables at COLUMNS≥160                       |
| Height        | 900 (long-form)    | Storyboard checklist needs vertical room               |
| Height        | 600 (short)        | Compact for README                                     |
| Theme         | Catppuccin Mocha   | Dark, high contrast                                    |
| WindowBar     | Colorful           | Branded chrome                                         |
| TypingSpeed   | 50ms               | Natural but not slow                                   |
| Framerate     | 30                 | Smooth; reasonable file size                           |
| Pre-roll      | 1s                 | First frame is not mid-action                          |
| Scene Sleep   | 6–8s               | Time to read; resize per scene                         |

### 5. Record

```bash
NAME="<scenario-name>"
[[ "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid scenario name: $NAME"; exit 1; }
export PATH="${GOPATH:-$HOME/go}/bin:$PATH"
"$VHS_PATH" "docs/demos/${NAME}.tape"
```

### 6. Validate

```bash
ls -lh docs/demos/recordings/<name>.*
```

- Play the recording end-to-end. Check title card, every scene headline, progress checklist updates, outro card.
- Confirm no captured-file path leaks (sometimes `cat` errors hint a capture file is missing).
- For LIVE scenes, confirm the recorded run reflects the intended fleet state.

### 7. Upload (out of skill scope)

User uploads `docs/demos/recordings/<name>.mp4` to YouTube. The skill does not push.

---

## VHS Commands Reference

| Command         | Usage                       | Notes                                              |
|-----------------|-----------------------------|----------------------------------------------------|
| `Output`        | `Output path.mp4`           | First line; sets output path                       |
| `Require`       | `Require clawctl`           | Fail-fast validation of needed binaries            |
| `Set`           | `Set Key Value`             | Configuration (see table above)                    |
| `Type`          | `Type "text"`               | Types text into terminal                           |
| `Enter`         | `Enter`                     | Presses Enter                                      |
| `Sleep`         | `Sleep 3s`                  | Pauses recording                                   |
| `Hide`/`Show`   | Bracket invisible commands  | venv activation, sourcing helpers, `clear`         |
| `Ctrl+C` / `Ctrl+D` | `Ctrl+D`                | Interrupt / EOF                                    |
| `Env`           | `Env KEY VALUE`             | Set env var (NEVER use for secrets — see warning)  |
| `PlaybackSpeed` | `Set PlaybackSpeed 2`       | Speeds up final playback                           |
| `Screenshot`    | `Screenshot path.png`       | Capture a still — useful for blog hero images      |

> ⚠️ **Never use `Env` with real credentials.** VHS bakes the literal value into the tape, which is committed. Inject secrets via a gitignored `.env` sourced inside a `Hide`/`Show` block instead.

---

## Production Quality (research-backed)

Apply to long-form demos; pick-and-choose for short demos.

- **Pre-roll & post-roll** `Sleep 1s` at the start and end so the first/last frame is not mid-action.
- **Vary typing speed**: 50ms default; slow to 100–150ms for the hero command of each scene so the viewer registers it before output appears.
- **Mask non-deterministic output** in captured replay files (timestamps, UUIDs, IPs, private hostnames). This also avoids leaking real fleet info to a public YouTube video.
- **Use `Require`** at the top of every tape for fail-fast validation — saves a 10-minute record that errors at scene 7.
- **Conversational `#` comments** typed into the shell narrate the demo without voiceover. Requires `Set Shell "bash"` (zsh treats `#` differently).
- **`Up` / `Tab`** keys feel realistic — show command history navigation and tab-completion instead of retyping.
- **`Screenshot`** the hero frame of each long demo for blog thumbnails and social.
- **Consistent length and typing speed across a demo series** — builds brand recognition.
- **`PlaybackSpeed` 1.5–2x** for stretches of unavoidably slow output. Note it in the tape header.
- **One demo = one fleet state.** Don't try to demo `create` and `remove` in the same tape; the second half is a different starting state.

## Troubleshooting

| Problem                    | Solution                                                                |
|----------------------------|-------------------------------------------------------------------------|
| `clm` not found             | Source the venv inside the `Hide`/`Show` setup block.                  |
| Helper functions not found  | Confirm `source ... _<name>_helpers.sh` is inside the Hide block.       |
| GIF too large               | Lower `Framerate` to 24, raise `PlaybackSpeed`, trim `Sleep` durations. |
| Output truncated            | Increase `Height` (900 for long-form), increase per-scene `Sleep`.      |
| Tables misaligned           | Ensure `Width` ≥ 1400 for `clm` table output.                           |
| Recording hangs             | Check command isn't waiting on interactive input; consider `Ctrl+C`.    |
| Capture file missing        | Re-run the capture script in step 2 of Flow B for that one scene.       |
| LIVE scene desyncs          | Add a hidden `until ... do sleep 3; done` after the visible `Sleep`.    |

## File Organization

```
docs/demos/
├── <name>.tape                       # committed
├── <name>.storyboard.md              # committed (long-form)
├── _<name>_helpers.sh                # committed (long-form)
├── <name>/outputs/                   # committed (replay scenes)
│   ├── 01-fleet.txt
│   └── 02-….txt
└── recordings/                       # gitignored
    ├── .gitkeep
    └── <name>.mp4
```

## References

External best-practice sources consulted for this skill:

- [charmbracelet/vhs README](https://github.com/charmbracelet/vhs)
- [VHS canonical demo.tape](https://github.com/charmbracelet/vhs/blob/main/examples/demo.tape)
- [Tips and tricks from VHS tapes (gist)](https://gist.github.com/andyfeller/3104a42bc367831e2d5f3910bde6cf2e)
- [Creating Terminal-Based Screencast Movies with VHS](https://blog.ouseful.info/2022/11/09/creating-terminal-based-screenshot-movies-with-vhs/)
- [Beyond Screenshots: Capture CLI Magic with VHS](https://tywer.dev/beyond-screenshots-capture-cli-magic-with-charmbracelet-vhs)
- [Terminal Recorders: A Comprehensive Guide (Intoli)](https://intoli.com/blog/terminal-recorders/)
- [3 tips for perfect VS Code video & GIFs recordings](https://dev.to/sinedied/3-tips-for-perfect-vs-code-video-gifs-recordings-dbn)

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/03_DEMO.md` if recording as part of an issue.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

---
name: create-vhs
description: Record a CLI demo (GIF or MP4) using VHS, with storyboard support for long-form / YouTube demos
argument-hint: "<scenario-name> [--description 'what to demo']"
---

# Demo Recording with VHS

Record CLI demos using [charmbracelet/vhs](https://github.com/charmbracelet/vhs). Each demo lives in its own dated-slug folder `docs/demos/YYYYMMDD-<slug>/` containing tape, storyboard, helpers, captures, stitched transcript, and the rendered recording. All `.mp4` files under `docs/demos/` are gitignored — users upload MP4s to YouTube; the binary itself does not live in the repo. Shared scripts and ANSI helpers live in `docs/demos/lib/`.

## Output Layout

Every demo lives in its own dated-slug folder under `docs/demos/`. The folder name is `YYYYMMDD-<slug>` where `YYYYMMDD` is the date the demo was first scaffolded. All artifacts for that demo are committed inside that folder; the rendered recording sits beside them but is gitignored.

Shared scripts and ANSI card/progress helpers live in `docs/demos/lib/` so each per-demo folder only contains per-demo content.

| Path                                                  | Committed? | Purpose                                              |
|-------------------------------------------------------|------------|------------------------------------------------------|
| `docs/demos/lib/cards.sh`                             | yes        | Shared titlecard/outrocard/headline/progress functions (sourced by every per-demo `helpers.sh`) |
| `docs/demos/lib/stitch.sh`                            | yes        | `bash docs/demos/lib/stitch.sh <demo-folder>` — concatenates `outputs/*.txt` into `stitched.txt` |
| `docs/demos/YYYYMMDD-<slug>/tape.tape`                | yes        | Reproducible VHS source for the recording            |
| `docs/demos/YYYYMMDD-<slug>/storyboard.md`            | yes        | Scene list, narration, capture index (mandatory for all demos) |
| `docs/demos/YYYYMMDD-<slug>/helpers.sh`               | yes (long-form) | Per-demo variables (`_SCENES`, `_TITLE`, etc.) + `source ../lib/cards.sh` |
| `docs/demos/YYYYMMDD-<slug>/outputs/NN-<slug>.txt`    | yes        | Per-scene captured stdout (used for replay scenes; reference for live scenes) |
| `docs/demos/YYYYMMDD-<slug>/stitched.txt`             | yes        | Stitched timeline produced by `lib/stitch.sh` (Step 4 of the universal flow) |
| `docs/demos/YYYYMMDD-<slug>/recording.{mp4,gif}`      | **no** (gitignored) | Rendered recording — uploaded to YouTube. All `.mp4` files under `docs/demos/` are gitignored. |

## Arguments

- `<scenario-name>`: Slug for the demo (e.g. `agent-lifecycle`, `host-setup`). Must match `^[a-zA-Z0-9_-]+$`. The skill prefixes today's date in `YYYYMMDD` form to produce the folder name `docs/demos/YYYYMMDD-<scenario-name>/`.
- `--description`: Optional one-liner of what the demo should show.

## Required Up-Front Questions

**MANDATORY**: Before writing any file, ask the user the following via `AskUserQuestion`. Do **not** assume defaults — wait for explicit answers.

1. **Output format**
   - **MP4** (`.mp4`) — default for YouTube uploads, social, anywhere a video container is required. Better compression. Recommended.
   - **GIF** (`.gif`) — for embedding in README/docs on GitHub. Smaller, autoplay-in-markdown, no audio.

2. **Demo style** — count the scenes the user wants to show. A storyboard is committed in either case (see Step 2 of the universal flow); the difference is whether a helper script and progress checklist are also generated.
   - **Short** (≤3 scenes) — trimmed storyboard, no helper script. README hero pattern.
   - **Long-form** (≥4 scenes) — full storyboard with scene list, progress checklist, title/outro cards, helper script. YouTube tutorial pattern.

3. **Execution model** (long-form only):
   - **Replay-first** (default, recommended) — capture command output to text files once, replay via `cat` during recording. Deterministic; recording doesn't need live infra; collapses minute-long ops into instant frames. Document `# LIVE` exceptions per-scene in the storyboard.
   - **All live** — every scene runs the real command at record time. Slower; requires the target fleet to be in the right state.

4. **Scene plan** (all demos — the storyboard is mandatory) — ask the user for an ordered list of scene titles, the command shown in each, and which scenes are `LIVE` (interactive TUIs like `agent chat` cannot be replayed). Scene 1 is fixed: `clawctl --version`. Ask only for Scene 2 onward. Stop after scaffolding the storyboard and get explicit user approval before layering in commands and generating the tape.

5. **Any other unclear input** — if the user's scenario name, scope, or prerequisites are ambiguous, ask before scaffolding. Never invent prerequisites.

## Universal Flow (every demo, short or long)

Every invocation of this skill follows the same four opening steps before branching into Flow A (short) or Flow B (long-form). **Do not skip any of them.**

### Step 1 — Run the prereq validator

The first action of every invocation is to run the bundled prereq script:

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/create-vhs/scripts/check-prereqs.sh"
```

The script checks for `vhs`, `ttyd`, `ffmpeg`, and `clawctl`. It exits non-zero on the first missing binary with an install hint. **If this exits non-zero, stop immediately and surface the missing binary to the user — do not attempt to scaffold a storyboard or tape.**

> `ttyd` is upstream `tsl0922/ttyd` (a C project). No `go install` path — use a package manager or the official binary release.

In addition, every tape **MUST** declare its own runtime prerequisites with `Require` directives at the top — VHS validates these before recording (`Require vhs`, `Require clawctl`, etc.).

### Step 2 — Write the storyboard (mandatory for ALL demos)

Resolve today's date as `YYYYMMDD` and create the per-demo folder `docs/demos/YYYYMMDD-<scenario-name>/`. Copy `.claude/skills/create-vhs/templates/storyboard.md.template` to `docs/demos/YYYYMMDD-<scenario-name>/storyboard.md` and fill in the scene table.

**Fixed opening convention**: Scene 1 of every clawrium demo is `clawctl --version`. The storyboard template pre-fills this row — leave it in place. It anchors the recording to a specific release so viewers can correlate behavior to a version.

The storyboard must list, per scene: title, command, mode (`replay` / `LIVE`), capture filename, and (optional) narration. **Get the user's explicit approval on the storyboard before moving to Step 3.**

For short demos (≤3 scenes), trim the scene table to the rows you need and skip the helper script — the storyboard itself still gets committed.

### Step 3 — Layer in the commands per storyboard checkpoint

With the storyboard approved, walk through it scene by scene and decide the exact command line for each:

- For `replay` scenes: run the real command once on a real host and save stdout to `docs/demos/YYYYMMDD-<scenario-name>/outputs/NN-<slug>.txt`. Mask non-deterministic values (timestamps, UUIDs, IPs, private hostnames) before committing.
- For `LIVE` scenes: still capture a reference output (with `script -q -c '<cmd>' /tmp/...` or `tee`) so Step 4 below has something to stitch. Confirm the command runs end-to-end on the target host in the time budget you allocated.
- Update the storyboard's `Command` column with the final, copy-paste-ready string. If a command changed during this step, re-confirm with the user.

### Step 4 — Stitch outputs and estimate runtime

After every scene's output has been captured under `docs/demos/YYYYMMDD-<scenario-name>/outputs/`, produce a single stitched transcript and a runtime estimate so the user can decide where to truncate before recording.

**Stitch** uses the shared script in `docs/demos/lib/`:

```bash
bash docs/demos/lib/stitch.sh docs/demos/YYYYMMDD-<scenario-name>
```

The script writes `docs/demos/YYYYMMDD-<scenario-name>/stitched.txt` and prints per-scene and total line counts.

**Estimate runtime** per scene and total, using the rule of thumb baked into the tape templates:

- Typing of a single command line: ~`Set TypingSpeed` × command length (default 50ms × N chars).
- `Sleep` after `Enter`: 6s for replay scenes with short tables, up to 8s for long output. LIVE scenes use real wall-clock + a 2s read buffer.
- Title card: 4s. Outro card: 5s. Per-scene `headline` + `progress`: ~5s combined.

Produce a markdown table for the user:

| Scene | Title | Mode | Captured lines | Est. seconds |
|------:|-------|------|---------------:|-------------:|
| 1     | clawctl version | replay | 5  | 8  |
| 2     | …               | replay | 32 | 12 |
| …     | …               | …      | …  | …  |
| **Total** | | | | **NN s** |

Present the stitched transcript + table to the user. They can then say "truncate scene N output to first M lines" or "cut scene K entirely" before the tape is generated. **Do not auto-truncate.**

Only after the user signs off on the stitched timeline should you proceed to the format-specific flow (A or B) below.

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

For README hero GIFs and quick captures. Storyboard is committed (per Step 2 above) but no helper script is generated.

### 1. Write the tape

Create `docs/demos/YYYYMMDD-<scenario-name>/tape.tape`. Scene 1 is always `clawctl --version` — the fixed opener.

```tape
# <Title>
# Records: <what commands are shown>
# Requires: <prerequisites, e.g., "a configured fleet">

Require vhs
Require clawctl

Output docs/demos/YYYYMMDD-<scenario-name>/recording.<ext>   # <ext> = mp4 (YouTube) or gif (README)

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

# Scene 1 (fixed opener) — show clawctl version
Type "clawctl --version"
Sleep 300ms
Enter
Sleep 2s

# Scene 2 — <Comment describing second command>
Type "<command>"
Sleep 300ms
Enter
Sleep 3s

# Scene 3 — <Comment describing third command>
Type "<command>"
Sleep 300ms
Enter
Sleep 3s
```

### 2. Record

```bash
SCENARIO="<scenario-name>"
DATE="$(date -u +%Y%m%d)"
[[ "$SCENARIO" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid scenario name: $SCENARIO"; exit 1; }
export PATH="${GOPATH:-$HOME/go}/bin:$PATH"
"$VHS_PATH" "docs/demos/${DATE}-${SCENARIO}/tape.tape"
```

### 3. Validate

```bash
ls -lh docs/demos/YYYYMMDD-<scenario-name>/recording.*
```

- GIF for README: target **< 500 KiB**.
- GIF for docs: target **< 3 MiB**.
- MP4: no size cap (uploaded externally); still verify it plays and the output is legible.
- Open in a viewer to confirm output is readable end-to-end.

### 4. Reference (GIF only)

For README embed:
```markdown
<p align="center">
  <img src="docs/demos/YYYYMMDD-<scenario-name>/recording.gif" alt="<description>" width="100%">
</p>
```

> ⚠️ `.mp4` files under `docs/demos/` are gitignored globally; `.gif` files are not unless an explicit rule is added. If a GIF needs to embed in the committed README, host it externally (GitHub release asset / CDN) or add an explicit `!docs/demos/YYYYMMDD-<scenario-name>/recording.gif` allowlist line to `.gitignore`. The skill does NOT auto-decide; ask the user.

---

## Flow B — Long-Form Storyboarded Demo (≥4 scenes)

For YouTube tutorials and product walkthroughs. Replay-first by default. The storyboard already exists and outputs already captured (per universal Steps 2 & 3 above) — this flow only covers helper + tape generation, recording, and validation.

Replay-first trade-off (call out explicitly to the user):

- ✅ Recording is deterministic and re-runs without infra.
- ✅ A 3-minute `agent create` becomes an instant `cat` — Sleep is now purely for visual pacing.
- ⚠️ Captured output drifts when CLI output format changes. Re-capture per release tag, or after any change to Rich table layout / column order / status strings.
- ❌ Interactive scenes (TUIs, `agent chat`, anything keystroke-driven) **cannot** be replayed. Mark them `LIVE` in the storyboard.

Quick reference for the masking pass (run during Step 3 of the universal flow):

```bash
sed -i -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+/2026-01-01T00:00:00Z/g' docs/demos/YYYYMMDD-<scenario-name>/outputs/*.txt
```

### 1. Generate the helper script

Copy `.claude/skills/create-vhs/templates/_progress.sh.template` to `docs/demos/YYYYMMDD-<scenario-name>/helpers.sh`. Fill in:

- `_SCENES=(...)` — must match the storyboard scene list, in order.
- `_TITLE`, `_SUBTITLE`, `_OUTRO_LINE_1`, `_OUTRO_LINE_2`.

The template ends with `source "$(git rev-parse --show-toplevel)/docs/demos/lib/cards.sh"` — leave that line in place. The shared functions `titlecard`, `outrocard`, `headline`, `progress` come from `docs/demos/lib/cards.sh`; per-demo `helpers.sh` only sets variables.

Syntax-check it:

```bash
bash -n docs/demos/YYYYMMDD-<scenario-name>/helpers.sh
```

### 2. Generate the tape

Copy `.claude/skills/create-vhs/templates/long-form.tape.template` to `docs/demos/YYYYMMDD-<scenario-name>/tape.tape`. For every scene block, fill in:

- Scene number and title (must match storyboard).
- Either `Type "cat docs/demos/YYYYMMDD-<scenario-name>/outputs/NN-<slug>.txt"` (replay) **or** the real command (LIVE).
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

### 3. Record

```bash
NAME="<scenario-name>"
DATE="$(date -u +%Y%m%d)"
[[ "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid scenario name: $NAME"; exit 1; }
export PATH="${GOPATH:-$HOME/go}/bin:$PATH"
"$VHS_PATH" "docs/demos/${DATE}-${NAME}/tape.tape"
```

### 4. Validate

```bash
ls -lh docs/demos/YYYYMMDD-<scenario-name>/recording.*
```

- Play the recording end-to-end. Check title card, every scene headline, progress checklist updates, outro card.
- Confirm no captured-file path leaks (sometimes `cat` errors hint a capture file is missing).
- For LIVE scenes, confirm the recorded run reflects the intended fleet state.

### 5. Upload (out of skill scope)

User uploads `docs/demos/YYYYMMDD-<scenario-name>/recording.mp4` to YouTube. The skill does not push.

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
├── lib/                              # committed — shared, all demos
│   ├── cards.sh                      # titlecard / outrocard / headline / progress functions
│   └── stitch.sh                     # concatenate outputs/*.txt -> stitched.txt
└── YYYYMMDD-<slug>/                  # one folder per demo
    ├── tape.tape                     # committed — VHS source
    ├── storyboard.md                 # committed — scene list, narration
    ├── helpers.sh                    # committed (long-form) — per-demo _SCENES/_TITLE/… + source lib/cards.sh
    ├── outputs/                      # committed — per-scene captures
    │   ├── 01-version.txt
    │   └── 02-….txt
    ├── stitched.txt                  # committed — full timeline transcript
    └── recording.mp4                 # gitignored — output of `vhs tape.tape`
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

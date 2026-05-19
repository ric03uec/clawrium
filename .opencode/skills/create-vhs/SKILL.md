---
name: create-vhs
description: Record a CLI demo GIF using VHS (charmbracelet/vhs)
argument-hint: "<scenario-name> [--description 'what to demo']"
---

# Demo Recording with VHS

Record CLI demo GIFs using [charmbracelet/vhs](https://github.com/charmbracelet/vhs). Tape source files are committed alongside generated GIFs in `docs/demos/`.

## Arguments

- `<scenario-name>`: Name for the tape/GIF (e.g., `readme`, `agent-lifecycle`, `host-setup`)
- `--description`: Optional description of what the demo should show

## Prerequisites

Verify all dependencies are available before recording:

```bash
# Required binaries (resolved via PATH; override with env vars if needed)
VHS_BIN="${VHS_BIN:-$(command -v vhs || true)}"
TTYD_BIN="${TTYD_BIN:-$(command -v ttyd || true)}"
FFMPEG_BIN="${FFMPEG_BIN:-$(command -v ffmpeg || true)}"

# Validate
for bin in "$VHS_BIN" "$TTYD_BIN" "$FFMPEG_BIN"; do
  if [ -z "$bin" ] || [ ! -x "$bin" ]; then
    echo "MISSING dependency. Install instructions:"
    echo "  VHS:    go install github.com/charmbracelet/vhs@latest"
    echo "  ttyd:   brew install ttyd | apt install ttyd | https://github.com/tsl0922/ttyd/releases"
    echo "  ffmpeg: brew install ffmpeg | apt install ffmpeg"
    exit 1
  fi
done
```

> `ttyd` is upstream `tsl0922/ttyd` (a C project). There is no `go install` path for it — use a package manager or the official binary release.

## Instructions

### 1. Resolve Tooling Paths

```bash
VENV_PATH="${VENV_PATH:-.venv/bin/activate}"
VHS_PATH="${VHS_PATH:-$(command -v vhs)}"
```

### 2. Plan the Demo

Before writing the tape, determine:
- What commands to show (keep it to 2-3 max for README demos)
- Expected output (run commands manually first to confirm they work)
- Whether the demo needs live infrastructure (hosts, agents) or can work standalone

### 3. Write the Tape File

Create `docs/demos/<scenario-name>.tape`:

```tape
# <Title>
# Records: <what commands are shown>
# Requires: <prerequisites, e.g., "a configured fleet">

Output docs/demos/<scenario-name>.gif

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
# Resolve from repo root so any contributor can re-record from any checkout.
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 1s
Show

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

**Standard Settings** (use these defaults unless there's a reason to deviate):

| Setting | Value | Rationale |
|---------|-------|-----------|
| FontSize | 18 | Readable on GitHub |
| Width | 1400 | Fits tables at COLUMNS=160+ |
| Height | 600 | Compact; increase for multi-command demos |
| Theme | Catppuccin Mocha | Dark, high-contrast |
| WindowBar | Colorful | Professional appearance |
| TypingSpeed | 50ms | Natural but not slow |
| Framerate | 30 | Smooth, reasonable file size |
| Sleep after Enter | 3s | Enough for command output to render |

If you deviate from defaults, add a comment in the tape header explaining why (e.g. `# Framerate 10 + PlaybackSpeed 3 compresses the 25s install output`).

**VHS Commands Reference**:

| Command | Usage | Notes |
|---------|-------|-------|
| `Output` | `Output path.gif` | First line; sets output path |
| `Set` | `Set Key Value` | Configuration (see table above) |
| `Type` | `Type "text"` | Types text into terminal |
| `Enter` | `Enter` | Presses Enter key |
| `Sleep` | `Sleep 3s` | Pauses recording |
| `Hide`/`Show` | Block invisible commands | Use for venv activation, env setup |
| `Ctrl+C` | `Ctrl+C` | Send interrupt |
| `Env` | `Env KEY VALUE` | Set environment variable |
| `PlaybackSpeed` | `Set PlaybackSpeed 2` | Speeds up final playback (multiplier) |

> ⚠️ **Never use `Env` with real credentials.** VHS bakes the literal value into the tape file, which is committed to version control. To inject secrets at recording time, put them in a gitignored `.env` file and source it inside a `Hide`/`Show` block instead.

### 4. Generate the GIF

```bash
# Validate the scenario name to prevent shell metacharacters and path traversal
SCENARIO="<scenario-name>"
[[ "$SCENARIO" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid scenario name: $SCENARIO"; exit 1; }

# Ensure Go-installed binaries are on PATH (skip if vhs is already on PATH)
export PATH="${GOPATH:-$HOME/go}/bin:$PATH"
"$VHS_PATH" "docs/demos/${SCENARIO}.tape"
```

### 5. Validate Output

- Check file size: target **< 500 KiB (512,000 bytes) for README GIFs**, **< 3 MiB (3,145,728 bytes) for docs**
- Verify the GIF renders correctly (open in browser/viewer)
- Confirm all command output is visible and readable

```bash
ls -lh docs/demos/<scenario-name>.gif
```

Size limits are enforced by `tests/test_demo_assets.py` — re-record or trim before committing if oversized.

### 6. Embed in Documentation

For README embedding:
```markdown
<p align="center">
  <img src="docs/demos/<scenario-name>.gif" alt="<description>" width="100%">
</p>
```

For other docs:
```markdown
![<description>](../demos/<scenario-name>.gif)
```

## Configuration

Override the defaults with environment variables before invoking the skill:

| Variable | Default | Purpose |
|----------|---------|---------|
| `VENV_PATH` | `.venv/bin/activate` | Path (relative to repo root) of the venv used when activating `clm` inside the tape's `Hide`/`Show` block |
| `VHS_PATH` | `$(command -v vhs)` | Absolute path or PATH-resolvable command name for the VHS binary |
| `GOPATH` | `$HOME/go` | Used to extend `PATH` so Go-installed binaries (vhs) are discoverable |

The `.claude` variant of this skill reads the equivalent keys from `.claude/itx-config.json` (`demo.venv_path`, `demo.vhs_path`). Opencode users export the env vars instead — there is no opencode-side config file.

## File Organization

```
docs/demos/
├── readme.tape          # README hero GIF source
├── readme.gif           # README hero GIF (generated)
├── <scenario>.tape      # Additional demo sources
└── <scenario>.gif       # Additional demo GIFs (generated)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `clm` not found | Use `Hide`/`Show` block to activate venv |
| GIF too large | Reduce `Sleep` times, lower `Framerate` to 24, raise `PlaybackSpeed` |
| Output truncated | Increase `Height`, increase `Sleep` after command |
| Tables misaligned | Ensure `Width` >= 1400 for `clm` table output |
| Recording hangs | Check command doesn't require interactive input |

## Notes

- Tape files are committed to version control (they ARE the source)
- GIF files are also committed; target < 500 KiB for README, < 3 MiB for docs. Validate with `ls -lh` before committing.
- Use `$(git rev-parse --show-toplevel)/.venv/bin/activate` inside the `Hide` block so tapes are portable across machines
- Re-record by re-running `vhs <tape-file>`
- Preview before committing: `xdg-open docs/demos/<name>.gif`

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/03_DEMO.md` if recording as part of an issue.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

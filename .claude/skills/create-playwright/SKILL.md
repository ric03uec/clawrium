---
name: create-playwright
description: Record a browser-session demo (MP4) using Playwright via a replay-first compile pipeline. A YAML spec drives the driver script, the recording, and the ElevenLabs voiceover — mirrors create-vhs for browser flows.
argument-hint: "<scenario-name> [--description 'what to demo']"
---

# Browser Demo Recording with Playwright — replay-first pipeline

Record browser demos using [Playwright Python](https://playwright.dev/python/). Each demo lives in its own dated-slug folder `docs/demos/YYYYMMDD-<slug>/` — the same parent as CLI demos produced by `/create-vhs`. The pipeline is **replay-first**: network responses are captured once via HAR on a live app, then a YAML spec drives driver generation, recording, and narration. Iteration is fast and timing is deterministic.

## Pipeline

```
              (one-time, slow)
   scenes.yaml + live app  -->  outputs/*.har       [HAR capture phase]
                                        |
              (instant)                 v
   scenes.yaml  +  outputs/*.har  -->  pw_compile.py  -->  driver.py + cards/*.html + compiled.json
                                        |
              (~recording length)       v
                                     uv run driver.py  -->  recording.webm
                                        |
              (~5s, codec swap)         v
                                     ffmpeg -c:v libx264 ...  -->  recording.mp4
                                        |
              (~30s, cached per text)   v
                                     narrate.py compiled.json  -->  voice/*.mp3 + recording-narrated.mp4
                                        |
              (manual)                  v
                                     upload to YouTube
```

`pw_compile.py`, the driver, and `narrate.py` are all idempotent. The slow step is the initial HAR capture; everything downstream re-runs in seconds.

## Output Layout

| Path | Committed? | Purpose |
|---|---|---|
| `docs/demos/lib/pw_compile.py` | yes | `scenes.yaml → driver.py + cards/*.html + compiled.json` |
| `docs/demos/lib/pw_driver.py.j2` | yes | Jinja template for the generated driver |
| `docs/demos/lib/cards/title.html.j2` | yes | Title-card HTML template |
| `docs/demos/lib/cards/outro.html.j2` | yes | Outro-card HTML template |
| `docs/demos/lib/narrate.py` | yes | **Reused unchanged** from `/create-vhs` |
| `docs/demos/lib/.env.example` | yes | **Reused unchanged** — ElevenLabs credentials template |
| `docs/demos/lib/.env` | **no** (gitignored) | **Reused unchanged** — real API key + voice/model IDs |
| `docs/demos/YYYYMMDD-<slug>/scenes.yaml` | yes | **Single source of truth** — scene structure, actions, narration |
| `docs/demos/YYYYMMDD-<slug>/outputs/NN-<slug>.har` | yes | Per-scene captured network responses (replayed by the driver) |
| `docs/demos/YYYYMMDD-<slug>/outputs/storage_state.json` | **no** (gitignored) | Auth/cookie state captured via `playwright codegen`; contains tokens |
| `docs/demos/YYYYMMDD-<slug>/driver.py` | yes | **Generated** by pw_compile.py; do not hand-edit |
| `docs/demos/YYYYMMDD-<slug>/cards/title.html` | yes | **Generated** by pw_compile.py |
| `docs/demos/YYYYMMDD-<slug>/cards/outro.html` | yes | **Generated** by pw_compile.py |
| `docs/demos/YYYYMMDD-<slug>/compiled.json` | yes | **Generated** by pw_compile.py; absolute narration timestamps |
| `docs/demos/YYYYMMDD-<slug>/voice/*.mp3` | **no** (gitignored) | Per-beat TTS clips, cached by `sha1(voice_id + text)` |
| `docs/demos/YYYYMMDD-<slug>/recording.webm` | **no** (gitignored) | Direct Playwright video output |
| `docs/demos/YYYYMMDD-<slug>/recording.mp4` | **no** (gitignored) | `ffmpeg`-transcoded H.264 |
| `docs/demos/YYYYMMDD-<slug>/recording-narrated.mp4` | **no** (gitignored) | Final video with voiceover muxed in |

`storage_state.json` MUST be gitignored — it can contain bearer tokens.

## Arguments

- `<scenario-name>`: Slug for the demo (e.g. `gui-agent-create`). Must match `^[a-zA-Z0-9_-]+$`. The skill prefixes today's date as `YYYYMMDD` → `docs/demos/YYYYMMDD-<scenario-name>/`.
- `--description`: Optional one-liner of what the demo should show.

## Required Up-Front Questions

**MANDATORY**: Before scaffolding any file, ask the user via `AskUserQuestion`. Do **not** assume defaults.

1. **Target app & base URL** — the URL the demo opens against (`base_url`).
2. **Auth model**
   - **Anonymous** — no login needed (most landing/marketing demos).
   - **Pre-authenticated session** — operator runs `playwright codegen --save-storage outputs/storage_state.json <base_url>` once; the driver loads it before scenes.
   - **Live login flow** — login is itself a scene (avoid for committed demos; secrets leak into HAR).
3. **Scene plan** — ordered list of scene titles + actions. There is no fixed Scene 1 (unlike `/create-vhs` which anchors on `clawctl --version`); choose what anchors the recording.
4. **HAR strategy per scene** — for each scene whose network responses you want frozen, confirm a HAR file path. Scenes without `har:` execute live.
5. **Long-flow handling** — for any scene whose interaction takes more than ~15 seconds on screen, confirm whether to split into sub-scenes or use the `speed_up:` multiplier (post-record ffmpeg pass).
6. **Any other unclear input** — never invent prerequisites.

## Universal Flow

### Step 1 — Run the prereq validator

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/create-playwright/scripts/check-prereqs.sh"
```

Checks `python3`, `uv`, system `ffmpeg`, `jq`, a system Chrome binary (`google-chrome` / `chromium`), and that Playwright (`>=1.40`) can resolve **plus** its bundled ffmpeg is present at `~/.cache/ms-playwright/ffmpeg-*/`. Stop immediately if any are missing.

**Installation hints surfaced by the check:**
- `playwright install ffmpeg` downloads the bundled video-encoder ffmpeg (separate from system ffmpeg — Playwright needs its own for `record_video_dir`).
- **Ubuntu 26.04** isn't on Playwright's supported-OS matrix yet. Prepend `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64` to the install command; the 24.04 binaries run fine on 26.04. The prereq check detects this OS and emits the override automatically.
- The driver intentionally launches **system Chrome** via `chromium.launch(channel="chrome")` rather than Playwright's bundled Chromium. This sidesteps the OS-matrix problem for the browser binary itself and produces identical recordings. The only Playwright-bundled binary you still need is `ffmpeg`.

### Step 2 — Author `scenes.yaml`

Copy `.claude/skills/create-playwright/templates/scenes.yaml.template` to `docs/demos/YYYYMMDD-<scenario-name>/scenes.yaml` and fill in title, subtitle, `base_url`, intro/outro narration, and the scene list.

Action verbs supported by the driver (mapped 1:1 to Playwright `Page` methods):

| Action | YAML form | Playwright call |
|---|---|---|
| Navigate | `goto: /path` (relative to `base_url`) or full URL | `page.goto()` |
| Click | `click: "<selector>"` | `page.locator(sel).click()` |
| Fill | `fill: { selector: "#x", text: "hello" }` | `page.locator(sel).fill(text)` |
| Press a key | `press: { selector: "#x", key: "Enter" }` | `page.locator(sel).press(key)` |
| Hover | `hover: "<selector>"` | `page.locator(sel).hover()` |
| Wait for selector | `wait_for: "<selector>"` | `page.locator(sel).wait_for()` |
| Wait for URL | `wait_for_url: "<glob>"` | `page.wait_for_url(pattern)` |
| Sleep (last resort) | `wait: <seconds>` | `page.wait_for_timeout(ms)` |
| Highlight a region | `highlight: "<selector>"` | injects a CSS ring overlay |
| Scroll | `scroll: { selector: "<sel>" }` or `scroll: { y: 400 }` | `scroll_into_view_if_needed()` or `mouse.wheel()` |
| Escape hatch | `eval: "page.locator(...).click()"` | raw Python evaluated in driver scope |

Avoid `wait:` (raw sleeps) — Playwright's auto-wait via `wait_for:` is deterministic and faster.

**Get explicit user approval on `scenes.yaml`** before capturing HARs.

### Step 3 — Capture HARs (one-time, on a live app)

For each scene that declares `har:`, run the capture pass. `pw_compile.py --capture` generates a stripped-down capture-only driver that emits HARs without recording video:

```bash
NAME=YYYYMMDD-<scenario-name>
mkdir -p docs/demos/$NAME/outputs

uv run docs/demos/lib/pw_compile.py docs/demos/$NAME --capture
uv run docs/demos/$NAME/driver_capture.py
```

The capture pass opens a real Chromium window (headed by default), executes every scene's actions, and writes one HAR per scene to `outputs/NN-<slug>.har`.

**Scrub secrets from HARs before committing**:
- Bearer tokens in `Authorization` headers
- Session cookies
- PII in request/response bodies

A scripted `jq` pass works:

```bash
jq '(.log.entries[].request.headers[] | select(.name | ascii_downcase == "authorization")).value = "Bearer REDACTED"' \
  docs/demos/$NAME/outputs/02-foo.har > /tmp/scrubbed.har && mv /tmp/scrubbed.har docs/demos/$NAME/outputs/02-foo.har
```

**Re-capture cadence**: when the app's API shape or UI structure changes, when selectors used in `scenes.yaml` no longer resolve, or per release tag.

### Step 4 — Compile

```bash
uv run docs/demos/lib/pw_compile.py docs/demos/YYYYMMDD-<scenario-name>
```

uv resolves PEP 723 deps (`pyyaml`, `jinja2`) on first run. Outputs:

- `driver.py` — self-contained Playwright Python script. Header banner says "GENERATED — DO NOT EDIT".
- `cards/title.html`, `cards/outro.html` — rendered from the YAML title/subtitle/outro.
- `compiled.json` — flat list of every narration beat with its absolute timestamp in the rendered recording.

The script prints the recording duration estimate and a per-beat timeline. Verify these match what you expect before recording.

### Step 5 — Record

```bash
uv run docs/demos/YYYYMMDD-<scenario-name>/driver.py
```

The driver:
1. Opens Chromium at the configured viewport (`tape.width × tape.height`).
2. Optionally loads `outputs/storage_state.json` for auth.
3. Plays the title card HTML for `intro.title_card.hold_seconds`.
4. For each scene: applies `route_from_har` (if `har:` set), executes actions, holds for `screen_seconds`.
5. Plays the outro card.
6. Closes the context; Playwright finalizes `recording.webm`.

Then transcode to MP4:

```bash
ffmpeg -y -i docs/demos/YYYYMMDD-<scenario-name>/recording.webm \
       -c:v libx264 -pix_fmt yuv420p -crf 20 -preset slow \
       docs/demos/YYYYMMDD-<scenario-name>/recording.mp4
```

The driver runs this transcode automatically at the end of its run; the standalone command above is for manual re-runs.

### Step 6 — Layer narration (ElevenLabs)

**Identical to `/create-vhs`** — `narrate.py` is reused unchanged:

```bash
uv run docs/demos/lib/narrate.py docs/demos/YYYYMMDD-<scenario-name>
  [--force]              # regenerate ALL clips even if cached
  [--skip-mux]           # generate audio only; skip ffmpeg
  [--input recording.mp4 --output recording-narrated.mp4]
```

The cache key (`sha1(voice_id + text)`) and timeline contract (`compiled.json`) are unchanged.

### Step 7 — Iterate

| Change | Re-run |
|---|---|
| Narration text only | `pw_compile.py` + `narrate.py` (~30s; driver not needed) |
| Scene order / new scene / new action | `pw_compile.py` + driver + `narrate.py` |
| App API shape changed | re-do Step 3 HAR capture + Step 4+ |
| Visual / card text | `pw_compile.py` + driver + `narrate.py` |

### Step 8 — Upload (out of skill scope)

You upload `recording-narrated.mp4` to YouTube. The skill does not push.

## Configuration

`narrate.py` configuration is unchanged from `/create-vhs` (`.env`-based, ElevenLabs).

`scenes.yaml` `tape:` block:

| Key | Default | Notes |
|---|---|---|
| `framerate` | 30 | Driver does not enforce — informational; ffmpeg transcode uses source fps |
| `width` | 1400 | Viewport width; Playwright records WebM at this width |
| `height` | 900 | Viewport height |
| `device_scale` | 1 | 2 for HiDPI — doubles output dimensions |
| `base_url` | — | Required when scenes use relative `goto:` paths |
| `color_scheme` | `light` | `light` / `dark` / `no-preference` |
| `reduced_motion` | `reduce` | Recommend `reduce` for deterministic UI animations |

## Cards as HTML

Title and outro cards are full-screen HTML rendered in the same Playwright context. The Jinja templates at `docs/demos/lib/cards/{title,outro}.html.j2` receive:

- `title` (string)
- `subtitle` (string)
- `outro.line_1`, `outro.line_2` (strings, outro only)
- `theme` — currently fixed to "dark"; matches Catppuccin Mocha palette used in CLI demos for brand parity.

You can hand-edit the rendered `cards/*.html` for one-off visual tweaks, but a recompile overwrites them. Prefer editing the `.j2` template or YAML fields.

## Production Quality

- **`reduced_motion: reduce`** kills CSS transitions/animations the browser would render non-deterministically.
- **HAR replay catches 99% of HTTP traffic but does NOT capture WebSocket frames** (Playwright limitation as of writing). Apps with WS-heavy UI (live dashboards, chat) should record live or mock WS via `page.route` + custom handler — call this out at scene authoring time.
- **Custom webfonts** may fall back to default fonts in headless mode. Run headed if pixel-perfect type matters, or pre-load fonts via `page.add_style_tag()`.
- **Cookie/auth secrets**: NEVER commit `storage_state.json`. NEVER let live-login HAR ship — the Authorization header will be in the captured response chain.
- **One demo = one app state.** Don't try to demo "create then delete" in one HAR — the HAR captured at create-time doesn't have the delete responses. Split into two scenes with separate HARs, or run that scene live.
- **Viewport ≥ 1400×900** for desktop apps; smaller viewports require scenes designed for them (`tape.width: 1024` etc.).

## Troubleshooting

| Problem | Solution |
|---|---|
| `playwright: command not found` or "Chromium not installed" | The driver uses system Chrome (`channel="chrome"`); install Google Chrome via your OS, not via `playwright install chromium` |
| `Executable doesn't exist at ...ffmpeg-linux` | `uv run --with 'playwright>=1.40' -- playwright install ffmpeg` — prepend `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64` on Ubuntu 26.04 |
| `ERROR: Playwright does not support ... on ubuntu26.04-x64` | OS too new for Playwright's matrix. Use `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64` for the install command. Binaries are forward-compatible |
| HAR replay returns 404 for an asset | HAR was captured against a different URL; re-do Step 3. Or set `route_from_har(not_found="fallback")` (default) and live-fetch missing assets |
| Locator timeout in a scene | The selector changed; update `scenes.yaml`. Use `playwright codegen` to find a stable selector |
| Recording is too long | Lower `screen_seconds` per scene; remove `wait:` calls in favor of `wait_for:` |
| Narration drifts from on-screen action | All beats are absolute timestamps from `pw_compile.py`. If drift is real, edit `screen_seconds` / `offset_seconds` in scenes.yaml + recompile |
| WebM → MP4 transcode artifacts | Increase CRF quality (`-crf 18`) or change preset (`-preset veryslow`) |
| Auth fails in record run | `storage_state.json` expired; re-capture via `playwright codegen --save-storage` |
| WS-driven UI updates missing on replay | WebSocket isn't in HAR; record that scene live, or mock via `page.route` |

## File Organization

```
docs/demos/
├── lib/                              # committed — shared, all demos
│   ├── cards.sh                      # used by create-vhs CLI demos
│   ├── cards/                        # used by create-playwright (this skill)
│   │   ├── title.html.j2
│   │   └── outro.html.j2
│   ├── compile.py                    # create-vhs compiler
│   ├── pw_compile.py                 # THIS skill — scenes.yaml -> driver.py + cards/*.html + compiled.json (PEP 723; uv run)
│   ├── pw_driver.py.j2               # THIS skill — Jinja template for the generated driver
│   ├── narrate.py                    # REUSED — compiled.json -> voice/*.mp3 + recording-narrated.mp4
│   ├── .env.example                  # REUSED — ElevenLabs credentials template
│   └── .env                          # GITIGNORED — real ELEVENLABS_API_KEY etc.
└── YYYYMMDD-<slug>/                  # one folder per demo (CLI or browser)
    ├── scenes.yaml                   # committed — SOURCE OF TRUTH
    ├── outputs/                      # committed except storage_state.json
    │   ├── 01-landing.har
    │   ├── 02-create-agent.har
    │   └── storage_state.json        # GITIGNORED — contains auth tokens
    ├── driver.py                     # committed (generated) — Playwright script
    ├── cards/
    │   ├── title.html                # committed (generated)
    │   └── outro.html                # committed (generated)
    ├── compiled.json                 # committed (generated) — narration timeline
    ├── voice/                        # GITIGNORED — per-beat TTS clips
    │   └── scene-NN-beat-MM-<sha8>.mp3
    ├── recording.webm                # GITIGNORED — Playwright direct output
    ├── recording.mp4                 # GITIGNORED — ffmpeg-transcoded H.264
    └── recording-narrated.mp4        # GITIGNORED — final with voiceover
```

## Symmetry with `/create-vhs`

| Concern | `/create-vhs` (CLI) | `/create-playwright` (Browser) |
|---|---|---|
| Spec | `scenes.yaml` | `scenes.yaml` (same key shapes, different scene body) |
| Action unit | `command:` + `output_file:` | `actions:` (list) + `har:` |
| Frozen capture | `outputs/*.txt` (stdout) | `outputs/*.har` (network) |
| Render engine | `vhs tape.tape` | `uv run driver.py` (Playwright) |
| Compiler | `compile.py` → `tape.tape` | `pw_compile.py` → `driver.py` |
| Cards | ANSI in `lib/cards.sh` | HTML in `lib/cards/*.html.j2` |
| Narration | `narrate.py` (shared) | `narrate.py` (shared) |
| Final mux | ffmpeg `adelay+amix` (shared) | ffmpeg `adelay+amix` (shared) |

## References

External best-practice sources consulted:

- [Playwright Python docs — video recording](https://playwright.dev/python/docs/videos)
- [Playwright Python docs — network replay via `route_from_har`](https://playwright.dev/python/docs/mock#mocking-with-har-files)
- [Playwright Python docs — codegen + storage state](https://playwright.dev/python/docs/auth)
- [HAR 1.2 spec](http://www.softwareishard.com/blog/har-12-spec/)
- [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python)
- [PEP 723 — inline script metadata](https://peps.python.org/pep-0723/)

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/03_DEMO.md` if recording as part of an issue.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

# Clawrium Quickstart Onboarding — Long-Form All-LIVE Demo
# Records: title card -> 7 scenes (live on wolf-i with PlaybackSpeed compression on scene 4) -> outro
# Output : recording.mp4 alongside this tape (gitignored; uploaded to YouTube).
# Storyboard : docs/demos/20260618-quickstart-onboarding/storyboard.md
# Helper     : docs/demos/20260618-quickstart-onboarding/helpers.sh (sources docs/demos/lib/cards.sh)
# Captures   : docs/demos/20260618-quickstart-onboarding/outputs/  (reference only — this tape is all-LIVE)
# Requires   : host wolf-i registered; clawrium-gtm-litellm provider in secret store
#
# SECURITY: titles inside Type `...` backticks pass through bash. Keep titles plain alphanumeric.
# Hidden setup deletes any pre-existing quickstart-demo agent so the install in scene 4 is fresh.

Require vhs
Require clawctl

Output docs/demos/20260618-quickstart-onboarding/recording.mp4

Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 900
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set Padding 20
Set Margin 20
Set MarginFill "#1e1e2e"
Set BorderRadius 8
Set TypingSpeed 50ms
Set Framerate 30

# --- Setup (hidden) ---
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 500ms
Type `source "$(git rev-parse --show-toplevel)/docs/demos/20260618-quickstart-onboarding/helpers.sh"`
Enter
Sleep 500ms
# Clean slate: ensure quickstart-demo does not exist before scene 4 reinstalls it.
Type "clawctl agent delete -y quickstart-demo >/dev/null 2>&1 || true"
Enter
Sleep 60s
Type "clear"
Enter
Sleep 300ms
Show

# Pre-roll so first visible frame is not mid-action
Sleep 1s

# === TITLE CARD ===
Type "titlecard"
Enter
Sleep 4s

# === SCENARIO CHECKLIST (all pending) ===
Type "progress 0"
Enter
Sleep 5s

# ============================================================
# SCENE 1 — clawctl version  (FIXED OPENER)
# Mode: LIVE
# ============================================================
Type `headline 1 "clawctl version"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl --version"
Sleep 300ms
Enter
Sleep 3s
Type "progress 1"
Enter
Sleep 2500ms

# ============================================================
# SCENE 2 — Initialize clawrium service
# Mode: LIVE (idempotent)
# ============================================================
Type `headline 2 "Initialize clawrium service"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl service init"
Sleep 300ms
Enter
Sleep 5s
Type "progress 2"
Enter
Sleep 2500ms

# ============================================================
# SCENE 3 — Register a host
# Mode: LIVE (wolf-i already registered — outputs single "already exists" line)
# ============================================================
Type `headline 3 "Register a host"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl host create wolf.tailf7742d.ts.net --user xclm --alias wolf-i"
Sleep 300ms
Enter
Sleep 4s
Type "progress 3"
Enter
Sleep 2500ms

# ============================================================
# SCENE 4 — Install the hermes agent  (LONGEST SCENE — Ansible install)
# Mode: LIVE — uses PlaybackSpeed 6 to compress the middle Ansible TASK output.
# Approx record wall-clock: ~5 min. Approx playback: ~70s.
# ============================================================
Type `headline 4 "Install the hermes agent"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl agent create quickstart-demo --type hermes --host wolf-i"
Sleep 300ms
Enter
# Show start at normal speed (10s — opening [validate] / [base] lines)
Sleep 10s
# Compress the bulk Ansible TASK output (~4.5 min wall-clock compressed to ~45s playback)
Set PlaybackSpeed 6
Sleep 270s
Set PlaybackSpeed 1
# Show the PLAY RECAP and `ready` finish at normal speed (30s — buffer for install variance)
Sleep 30s
Type "progress 4"
Enter
Sleep 2500ms

# ============================================================
# SCENE 5 — Configure the agent (attach provider)
# Mode: LIVE — non-interactive --stage providers --provider <name>
# ============================================================
Type `headline 5 "Configure the agent"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl agent configure quickstart-demo --stage providers --provider clawrium-gtm-litellm"
Sleep 300ms
Enter
# Configure runs an Ansible play — gives it 35s wall-clock at normal speed
Sleep 35s
Type "progress 5"
Enter
Sleep 2500ms

# ============================================================
# SCENE 6 — Check fleet status
# Mode: LIVE — full fleet visible (9 rows including quickstart-demo at top of hermes group)
# ============================================================
Type `headline 6 "Check fleet status"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl agent get"
Sleep 300ms
Enter
Sleep 5s
Type "progress 6"
Enter
Sleep 2500ms

# ============================================================
# SCENE 7 — Chat with the agent
# Mode: LIVE — interactive TUI. One prompt -> one streamed response -> Ctrl+D
# ============================================================
Type `headline 7 "Chat with the agent"`
Enter
Sleep 2500ms
Hide
Type "clear"
Enter
Show
Type "clawctl agent chat quickstart-demo"
Sleep 300ms
Enter
# TUI prompts; wait for "you>" prompt
Sleep 4s
Type "hello, what model are you?"
Sleep 500ms
Enter
# Wait for streamed response (~30s for clawrium-gtm-litellm)
Sleep 35s
Ctrl+D
Sleep 2s
Type "progress 7"
Enter
Sleep 2500ms

# === OUTRO CARD ===
Type "outrocard"
Enter
Sleep 5s

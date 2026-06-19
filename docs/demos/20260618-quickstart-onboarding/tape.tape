# Clawrium Quickstart — Long-Form Storyboarded Demo
# GENERATED FROM scenes.yaml — DO NOT EDIT BY HAND.
#   Edit scenes.yaml then re-run: uv run docs/demos/lib/compile.py docs/demos/20260618-quickstart-onboarding
#
# Records: title card -> checklist -> N scenes (replay) -> outro card.
# Output : recording.mp4 alongside this tape (gitignored).

Require vhs

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

# --- Setup (hidden — NOT in recording timeline) ---
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 500ms
Type `source "$(git rev-parse --show-toplevel)/docs/demos/20260618-quickstart-onboarding/helpers.sh"`
Enter
Sleep 500ms
Type "clawctl agent delete -y quickstart-demo >/dev/null 2>&1 || true"
Enter
Sleep 60.0s
Type "clear"
Enter
Sleep 300ms
Show

# Pre-roll so the first visible frame is not mid-action
Sleep 1.0s

# === TITLE CARD ===
Type "titlecard"
Enter
Sleep 4.0s

# === SCENARIO CHECKLIST (all pending) ===
Type "progress 0"
Enter
Sleep 5.0s

# ============================================================
# SCENE 1 — clawctl version
# Mode: replay
# ============================================================
Type `headline 1 "clawctl version"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "cat docs/demos/20260618-quickstart-onboarding/outputs/01-version.txt"
Sleep 0.3s
Enter
Sleep 3.0s
Type "progress 1"
Enter
Sleep 2.5s

# ============================================================
# SCENE 2 — Initialize clawrium service
# Mode: replay
# ============================================================
Type `headline 2 "Initialize clawrium service"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "cat docs/demos/20260618-quickstart-onboarding/outputs/02-service-init.txt"
Sleep 0.3s
Enter
Sleep 5.0s
Type "progress 2"
Enter
Sleep 2.5s

# ============================================================
# SCENE 3 — Register a host
# Mode: replay
# ============================================================
Type `headline 3 "Register a host"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "cat docs/demos/20260618-quickstart-onboarding/outputs/03-host-create.txt"
Sleep 0.3s
Enter
Sleep 3.0s
Type "progress 3"
Enter
Sleep 2.5s

# ============================================================
# SCENE 4 — Install the hermes agent
# Mode: replay
# ============================================================
Type `headline 4 "Install the hermes agent"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "head -n 15 docs/demos/20260618-quickstart-onboarding/outputs/04-agent-create.txt; echo '   …'; tail -n 10 docs/demos/20260618-quickstart-onboarding/outputs/04-agent-create.txt"
Sleep 0.3s
Enter
Sleep 14.0s
Type "progress 4"
Enter
Sleep 2.5s

# ============================================================
# SCENE 5 — Configure the agent
# Mode: replay
# ============================================================
Type `headline 5 "Configure the agent"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "cat docs/demos/20260618-quickstart-onboarding/outputs/05-agent-configure.txt"
Sleep 0.3s
Enter
Sleep 5.0s
Type "progress 5"
Enter
Sleep 2.5s

# ============================================================
# SCENE 6 — Check fleet status
# Mode: replay
# ============================================================
Type `headline 6 "Check fleet status"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "cat docs/demos/20260618-quickstart-onboarding/outputs/06-agent-get.txt"
Sleep 0.3s
Enter
Sleep 5.0s
Type "progress 6"
Enter
Sleep 2.5s

# ============================================================
# SCENE 7 — Chat with the agent
# Mode: replay
# ============================================================
Type `headline 7 "Chat with the agent"`
Enter
Sleep 2.5s
Hide
Type "clear"
Enter
Show
Type "cat docs/demos/20260618-quickstart-onboarding/outputs/07-agent-chat.txt"
Sleep 0.3s
Enter
Sleep 8.0s
Type "progress 7"
Enter
Sleep 2.5s

# === OUTRO CARD ===
Type "outrocard"
Enter
Sleep 5.0s

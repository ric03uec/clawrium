# Clawrium agent installation demo
# Records: clm agent install --type zeroclaw --host clawdmin --yes
# Requires: clawdmin host registered, no existing zeroclaw agent

Output docs/demos/agent-install.gif

Set Shell "bash"
# Non-standard: FontSize 16 (vs 18) + Height 800 keep the full ansible install
# output visible without horizontal/vertical clipping. Framerate 10 +
# PlaybackSpeed 3 compress the 25s ansible run into ~8s playback.
Set FontSize 16
Set Width 1400
Set Height 800
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set Padding 20
Set Margin 20
Set MarginFill "#1e1e2e"
Set BorderRadius 8
Set TypingSpeed 50ms
Set Framerate 10
Set PlaybackSpeed 3

# Activate venv so clm is available (resolved from repo root)
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 1s
Show

# Install zeroclaw agent on clawdmin
Type "clm agent install --type zeroclaw --host clawdmin --yes"
Sleep 300ms
Enter
Sleep 25s

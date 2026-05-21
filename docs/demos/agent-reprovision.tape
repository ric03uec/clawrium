# Agent Provisioning
# Records: clm ps (no nemotron-alpha) -> install -> clm ps (with new agent) -> agent ps --host wolf-i
# Requires: nemotron-alpha NOT present in fleet (remove first if needed)
# Notes: PlaybackSpeed 2 compresses ~45s real into ~22s playback;
#        ansible install logs scroll fast but the final success line is visible.

Output docs/demos/agent-reprovision.gif

Set Shell "bash"
Set FontSize 13
Set Width 1200
Set Height 600
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful
Set Padding 20
Set Margin 20
Set MarginFill "#1e1e2e"
Set BorderRadius 8
Set TypingSpeed 50ms
Set Framerate 24
Set PlaybackSpeed 2

# Activate venv silently so `clm` is on PATH
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 500ms
Show

# 1. Fleet status — nemotron-alpha is not present (clm ps checks each agent for ~5s before rendering)
Type "clm ps"
Sleep 300ms
Enter
Sleep 8s

# 2. Provision the new agent
Type "clm agent install --type zeroclaw --host wolf-i --name nemotron-alpha -y"
Sleep 300ms
Enter
Sleep 28s

# 3. Fleet status — nemotron-alpha now appears
Type "clm ps"
Sleep 300ms
Enter
Sleep 8s

# 4. Filtered view for the host where the new agent lives
Type "clm agent ps --host wolf-i"
Sleep 300ms
Enter
Sleep 7s

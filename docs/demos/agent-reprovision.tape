# Agent Provisioning
# Records: clawctl agent get (no nemotron-alpha) -> install -> clawctl agent get (with new agent) -> agent ps --host wolf-i
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

# Activate venv silently so `clawctl` is on PATH
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 500ms
Show

# 1. Fleet status — nemotron-alpha is not present (clawctl agent get checks each agent for ~5s before rendering)
Type "clawctl agent get"
Sleep 300ms
Enter
Sleep 8s

# 2. Provision the new agent
Type "clawctl agent create --type zeroclaw --host wolf-i --name nemotron-alpha -y"
Sleep 300ms
Enter
Sleep 28s

# 3. Fleet status — nemotron-alpha now appears
Type "clawctl agent get"
Sleep 300ms
Enter
Sleep 8s

# 4. Filtered view for the host where the new agent lives
Type "clawctl agent get --host wolf-i"
Sleep 300ms
Enter
Sleep 7s

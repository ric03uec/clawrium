# Clawrium README demo
# Records: clm host list + clm ps
# Requires: a configured fleet with at least one host and agent

Output docs/demos/readme.gif

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

# Activate venv so clm is available (resolved from repo root)
Hide
Type `source "$(git rev-parse --show-toplevel)/.venv/bin/activate"`
Enter
Sleep 1s
Show

# Show registered hosts
Type "clm host list"
Sleep 300ms
Enter
Sleep 3s

# Show agent fleet status
Type "clm ps"
Sleep 300ms
Enter
Sleep 3s

# Shared card/headline/progress functions sourced by every per-demo helpers.sh.
# Reads four variables that the per-demo helpers must set BEFORE sourcing this file:
#   _SCENES         — bash array of scene titles (order = playback order)
#   _TITLE          — title shown on titlecard + progress card
#   _SUBTITLE       — subtitle shown under _TITLE on titlecard
#   _OUTRO_LINE_1   — primary outro line
#   _OUTRO_LINE_2   — secondary outro line (typically a URL)
#
# Exposed functions (called from inside the .tape):
#   titlecard       — opening branded frame
#   outrocard       — closing branded frame
#   headline N "T"  — per-scene banner (N of total scenes, title T)
#   progress N      — checklist with first N scenes struck through

# ANSI palette references:
#   1;36 = bold cyan   1;37 = bold white   1;32 = bold green
#   1;90 = bold grey   9    = strikethrough

progress() {
  local done=${1:-0}
  clear
  printf '\n'
  printf '\033[1;36m============================================================\033[0m\n'
  printf '\033[1;36m  %s  —  Progress\033[0m\n' "$_TITLE"
  printf '\033[1;36m============================================================\033[0m\n\n'
  local i n
  for i in "${!_SCENES[@]}"; do
    n=$((i+1))
    if [ "$n" -le "$done" ]; then
      printf '  \033[1;32m[x]\033[0m \033[9;90m%2d. %s\033[0m\n' "$n" "${_SCENES[$i]}"
    else
      printf '  \033[37m[ ]\033[0m \033[37m%2d. %s\033[0m\n' "$n" "${_SCENES[$i]}"
    fi
  done
  printf '\n'
}

headline() {
  local n=$1
  local title=$2
  local total=${#_SCENES[@]}
  clear
  printf '\n\n\n'
  printf '\033[1;36m============================================================\033[0m\n'
  printf '\033[1;36m                    SCENE %d / %d\033[0m\n' "$n" "$total"
  printf '\033[1;37m              %s\033[0m\n' "$title"
  printf '\033[1;36m============================================================\033[0m\n\n'
}

titlecard() {
  clear
  printf '\n\n\n\n'
  printf '\033[1;36m============================================================\033[0m\n'
  printf '\033[1;37m       %s\033[0m\n' "$_TITLE"
  printf '\033[1;90m                    %s\033[0m\n' "$_SUBTITLE"
  printf '\033[1;36m============================================================\033[0m\n\n'
}

outrocard() {
  clear
  printf '\n\n\n\n'
  printf '\033[1;36m============================================================\033[0m\n'
  printf '\033[1;32m         %s\033[0m\n' "$_OUTRO_LINE_1"
  printf '\033[1;90m            %s\033[0m\n' "$_OUTRO_LINE_2"
  printf '\033[1;36m============================================================\033[0m\n\n'
}

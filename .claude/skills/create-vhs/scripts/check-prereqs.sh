#!/usr/bin/env bash
# Validates that the create-vhs skill has every binary it needs before any
# storyboard, capture, or tape work begins. Exit non-zero on the first miss.
set -euo pipefail

missing=0
report_missing() {
  local bin="$1" hint="$2"
  echo "MISSING: $bin"
  echo "  install: $hint"
  missing=1
}

check() {
  local bin="$1" hint="$2"
  local path
  path="$(command -v "$bin" 2>/dev/null || true)"
  if [ -z "$path" ] || [ ! -x "$path" ]; then
    report_missing "$bin" "$hint"
  else
    echo "OK: $bin -> $path"
  fi
}

echo "create-vhs prereq check"
echo "-----------------------"

check vhs     "go install github.com/charmbracelet/vhs@latest"
check ttyd    "brew install ttyd | apt install ttyd | https://github.com/tsl0922/ttyd/releases"
check ffmpeg  "brew install ffmpeg | apt install ffmpeg"
check clawctl "uv tool install clawrium"

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "Prerequisite check FAILED. Install the missing binaries above and re-run."
  exit 1
fi

echo ""
echo "All prerequisites satisfied."

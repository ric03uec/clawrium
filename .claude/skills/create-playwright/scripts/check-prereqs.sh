#!/usr/bin/env bash
# Validates that the create-playwright skill has every binary + browser it
# needs before any storyboard, capture, or driver work begins. Exit non-zero
# on the first miss.
#
# Key constraints:
#   - The driver pulls Playwright via PEP 723 (`playwright>=1.40`). The check
#     must use the SAME dep constraint so we don't false-positive on a
#     pre-installed older Playwright whose browsers won't satisfy the driver.
#   - Playwright's `chromium.launch(channel="chrome")` drives the SYSTEM
#     Chrome binary, but VIDEO RECORDING still needs Playwright's bundled
#     ffmpeg under `~/.cache/ms-playwright/ffmpeg-*/`.
#   - On Ubuntu 26.04 the installer needs `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE`
#     because Playwright's supported-OS matrix lags. The 24.04 binaries run
#     fine on 26.04.

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

echo "create-playwright prereq check"
echo "------------------------------"

check python3 "apt install python3 | brew install python"
check uv      "curl -LsSf https://astral.sh/uv/install.sh | sh"
check ffmpeg  "apt install ffmpeg | brew install ffmpeg"
check jq      "apt install jq | brew install jq   # used to scrub HAR files"

# System Chrome path — the driver launches with channel="chrome", so we need
# a real Chrome binary at one of these paths.
chrome_bin=""
for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
  if path="$(command -v "$candidate" 2>/dev/null)"; then
    chrome_bin="$path"
    echo "OK: chrome -> $path (will be driven via channel=\"chrome\")"
    break
  fi
done
if [ -z "$chrome_bin" ]; then
  report_missing "google-chrome / chromium" "apt install google-chrome-stable | https://www.google.com/chrome/"
fi

# Playwright + bundled ffmpeg. We probe with the SAME dep constraint the
# driver uses so a stale pre-installed Playwright can't satisfy us.
if command -v uv >/dev/null 2>&1; then
  probe='
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    bt = pw.chromium
    # Verify the bundled ffmpeg exists. Path layout:
    #   ~/.cache/ms-playwright/ffmpeg-<rev>/ffmpeg-linux
    cache = Path.home() / ".cache" / "ms-playwright"
    if not any(cache.glob("ffmpeg-*/ffmpeg-linux")):
        sys.exit("missing-ffmpeg")
'
  if uv run --quiet --with "playwright>=1.40" python -c "$probe" >/dev/null 2>&1; then
    echo "OK: playwright>=1.40 + bundled ffmpeg"
  else
    osid="$(. /etc/os-release 2>/dev/null && echo "${ID:-linux}${VERSION_ID:-}-x64")"
    case "$osid" in
      ubuntu26.04-x64)
        report_missing "playwright bundled ffmpeg" \
          "PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 uv run --with 'playwright>=1.40' -- playwright install ffmpeg"
        ;;
      *)
        report_missing "playwright bundled ffmpeg" \
          "uv run --with 'playwright>=1.40' -- playwright install ffmpeg"
        ;;
    esac
  fi
fi

if [ "$missing" -ne 0 ]; then
  echo ""
  echo "Prerequisite check FAILED. Install the missing items above and re-run."
  exit 1
fi

echo ""
echo "All prerequisites satisfied."

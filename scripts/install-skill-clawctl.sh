#!/usr/bin/env bash
# Install the /clawctl skill globally for any installed AI assistant
# (Claude Code, opencode). Idempotent — re-running updates an existing
# install.
#
# The audit-trail tool (`clawctl audit ...`) ships as a subcommand of
# clawctl itself — there is no separate companion binary to install.
# Make sure `clawctl` is on your PATH before using the skill.
#
# Supports: Ubuntu / Debian-family Linux and macOS.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ric03uec/clawrium/main/scripts/install-skill-clawctl.sh | bash
#
# Override the version (defaults to the locally-installed clawctl, else "main"):
#   curl -fsSL ... | CLAWCTL_VERSION=v26.6.3 bash
#
# Exit codes:
#   0  success — installed for at least one detected assistant
#   1  no supported assistant detected on this machine
#   2  unsupported OS
#   3  required command (curl) missing
#   4  network/download failure for every detected assistant

set -euo pipefail

REPO="ric03uec/clawrium"
SKILL_NAME="clawctl"

# ---------------------------------------------------------------------------
# 0. Preflight
# ---------------------------------------------------------------------------

OS="$(uname -s)"
case "$OS" in
  Linux|Darwin) ;;
  *)
    printf 'error: unsupported OS: %s (this script supports Linux and macOS)\n' "$OS" >&2
    exit 2
    ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  printf 'error: curl is required but not installed.\n' >&2
  case "$OS" in
    Linux)  printf '       install with: sudo apt-get install -y curl\n' >&2 ;;
    Darwin) printf '       install with: brew install curl  (or use the system curl on macOS 10.15+)\n' >&2 ;;
  esac
  exit 3
fi

# ---------------------------------------------------------------------------
# 1. Determine which clawrium version's skill to fetch
# ---------------------------------------------------------------------------

VERSION="${CLAWCTL_VERSION:-}"
if [ -z "$VERSION" ] && command -v clawctl >/dev/null 2>&1; then
  detected="$(clawctl version 2>/dev/null | awk '{print $2}' || true)"
  if [ -n "${detected:-}" ]; then
    VERSION="v${detected}"
  fi
fi
# Fall back to main if clawctl isn't installed locally — the skill works
# standalone; the operator can install clawctl later.
: "${VERSION:=main}"

printf '==> Installing /%s skill (version: %s)\n' "$SKILL_NAME" "$VERSION"
printf '    OS: %s\n' "$OS"

# ---------------------------------------------------------------------------
# 2. Detect installed AI assistants and install the skill globally for each
# ---------------------------------------------------------------------------

TOOLS_FOUND=0
DOWNLOAD_FAILURES=0

# Download one file from the repo at the chosen VERSION to a destination.
# Args: $1 label, $2 source-path-in-repo, $3 dest-file.
# Returns 0 on success.
download_to() {
  label="$1"
  source_path="$2"
  dest_file="$3"
  url="https://raw.githubusercontent.com/${REPO}/${VERSION}/${source_path}"
  tmpfile="$(mktemp)"

  printf '    %s: fetching %s\n' "$label" "$url"
  if curl -fsSL "$url" -o "$tmpfile"; then
    mkdir -p "$(dirname "$dest_file")"
    mv "$tmpfile" "$dest_file"
    printf '    %s: installed -> %s\n' "$label" "$dest_file"
    return 0
  else
    rm -f "$tmpfile"
    printf '    %s: download failed (url: %s)\n' "$label" "$url" >&2
    return 1
  fi
}

# Claude Code: looks for the `claude` binary or the conventional config dir.
if command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; then
  TOOLS_FOUND=$((TOOLS_FOUND + 1))
  if ! download_to "Claude Code" \
      ".claude/skills/${SKILL_NAME}/SKILL.md" \
      "$HOME/.claude/skills/${SKILL_NAME}/SKILL.md"; then
    DOWNLOAD_FAILURES=$((DOWNLOAD_FAILURES + 1))
  fi
fi

# opencode: looks for the `opencode` binary or the XDG config dir
# (same path on Linux and macOS — opencode follows XDG on both).
if command -v opencode >/dev/null 2>&1 || [ -d "$HOME/.config/opencode" ]; then
  TOOLS_FOUND=$((TOOLS_FOUND + 1))
  if ! download_to "opencode" \
      ".opencode/skills/${SKILL_NAME}/SKILL.md" \
      "$HOME/.config/opencode/skills/${SKILL_NAME}/SKILL.md"; then
    DOWNLOAD_FAILURES=$((DOWNLOAD_FAILURES + 1))
  fi
fi

if [ "$TOOLS_FOUND" -eq 0 ]; then
  cat >&2 <<'EOM'

No supported AI assistant detected. Looked for:
  - claude  (Claude Code)        - install: https://docs.claude.com/en/docs/claude-code/getting-started
  - opencode                     - install: https://opencode.ai

Install one and re-run this script.
EOM
  exit 1
fi

if [ "$DOWNLOAD_FAILURES" -eq "$TOOLS_FOUND" ]; then
  printf '\nerror: all detected assistants failed to download the skill.\n' >&2
  printf '       check network and try again, or pin a known-good version with CLAWCTL_VERSION=vXX.Y.Z\n' >&2
  exit 4
fi

# ---------------------------------------------------------------------------
# 3. Report + clawctl preflight
# ---------------------------------------------------------------------------

if ! command -v clawctl >/dev/null 2>&1; then
  cat >&2 <<'EOM'

warning: clawctl is not on your PATH.
         The /clawctl skill drives audit logging through `clawctl audit ...`,
         which is a subcommand of clawctl itself. Install clawctl before
         using the skill:

           uv tool install clawrium

EOM
fi

cat <<EOM

Done. The /${SKILL_NAME} skill is now globally available for every detected assistant.

Audit-trail commands ship inside clawctl:
  clawctl audit log "<action>" --result success
  clawctl audit tail
  clawctl audit stats

Audit trail will be written to:
  ~/.config/clawrium/changelog/<YYYYMMDD>.jsonl

Open your assistant and type \`/${SKILL_NAME}\` to use it.
EOM

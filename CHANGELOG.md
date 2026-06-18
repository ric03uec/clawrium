# Changelog

All notable changes to this project are documented here. Per-release frozen
archives live under [`docs/releases/`](docs/releases/) — that directory is
the single place to read the full history of what shipped in each version.

The project follows a `YY.M.PATCH` calendar versioning convention; the
`## [Unreleased]` section below is the working log for the next release
cut. The `itx:release` skill archives this section into a new
`docs/releases/<version>/CHANGELOG.md` and resets this file to an empty
`[Unreleased]` template on every release.

## [Unreleased]

### BREAKING

### Added

- `/clawctl` AI-assistant skill — embeds the full `clawctl` CLI reference (all
  commands, flags, sub-commands, and common workflows) into any
  opencode-compatible assistant **and** Claude Code, enabling natural-language
  fleet management from the control machine without leaving the assistant
  session. Ships in two byte-identical copies so it's discoverable by both
  tools: `.opencode/skills/clawctl/SKILL.md` and
  `.claude/skills/clawctl/SKILL.md`. Registered in `AGENTS.md` and documented
  in the website guides (`website/docs/guides/ai-assistant.md`). Closes #741.
- `scripts/install-skill-clawctl.sh` — one-shot installer for the `/clawctl`
  skill. Works on Ubuntu / Debian-family Linux and macOS, auto-detects which
  AI assistants (Claude Code, opencode) are installed, drops the skill into
  the right **global** discovery path for each (no Clawrium project checkout
  required), and pins the skill to the locally-installed `clawctl` version.
  Idempotent. Curl-pipe-bash:
  `curl -fsSL https://raw.githubusercontent.com/ric03uec/clawrium/main/scripts/install-skill-clawctl.sh | bash`.
- `clawctl audit` subcommand — operator-side audit trail for the `/clawctl`
  skill, exposed as a built-in subcommand of `clawctl` (no separate companion
  binary to install). The skill instructs the assistant to record every
  mutating `clawctl` command — and every command-line failure — via
  `clawctl audit log` so the operator has a full reproducible trace of what
  the assistant did, when, and with what result. Logs live at
  `~/.config/clawrium/changelog/<YYYYMMDD>.jsonl` (one file per UTC day,
  JSONL, append-only). Schema v1 fields per entry: `type`, `uuid`,
  `parent_uuid`, `session_id`, `timestamp` (ms precision), `cwd`,
  `version` (`{audit, clawctl}`), `actor`, `action`, `result`, `notes` —
  inspired by Claude Code's `~/.claude/projects/*.jsonl` shape.
  Subcommands: `log`, `show`, `tail`, `stats`, `path`, `session new`.
  The skill mints a session id via `clawctl audit session new` and exports
  it as `$CLAWCTL_AUDIT_SESSION_ID` before multi-step workflows so the
  operator can replay a whole workflow with `clawctl audit show --session-id <id>`.
- `openclaw` agents can now attach `type=litellm` providers — custom
  OpenAI-compatible endpoints (LiteLLM, vLLM, any `/v1/chat/completions`
  proxy). `clawctl agent configure` / `clawctl agent sync` render a
  `models.providers.<provider-name>` block into `.openclaw/openclaw.json`
  with `api: "openai-completions"`, inline `apiKey`, and `baseUrl`
  normalized to `<endpoint>/v1`. The bearer lives in `openclaw.json`
  exclusively — no new `.openclaw/env` var emitted. Closes #723.
- Right-hand rail on the `/blog` listing (About, Tags, Community sections),
  filling the previously empty `col--2` slot. Sticky-positioned with its own
  scroll on short viewports; hidden below 996px. Individual post pages still
  render the standard table of contents in that column.

### Changed

- `clawctl host create` manual-setup output now prints a macOS preflight
  block instructing operators to enable Remote Login (`sshd`) locally on
  the Mac before running the SSH-paste block. (#718)
- Blog post titles shrunk from 3rem to 2.25rem (1.6rem on screens ≤576px).
  In-post body headings (`h1`–`h4`) reduced by one step. All overrides scoped
  to `.blog-wrapper` so docs typography is unaffected.
- Left blog sidebar now groups posts by month (e.g. "June 2026") instead of
  year and shows every post (`blogSidebarCount: 'ALL'`).
- Sidebar "All posts" label is now a link back to `/blog` so readers can
  navigate back from any post page.

### Fixed

### Documentation

- Document the macOS-only requirement to enable Remote Login (sshd) before
  running the `xclm` host-preparation block, and surface the same preflight
  in the `clawctl host create` manual-setup output. (#718)

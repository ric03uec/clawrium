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

- **openclaw brave plugin now requires openclaw `>= 2026.6.8`** (previously
  `>= 2026.4.10`). Any host running openclaw in the `2026.4.10..2026.6.7`
  range with the brave integration attached will hit a hard
  `CanonicalSyncError` on the next `clawctl agent sync` with the message
  `openclaw on '<host>' is <X.Y.Z>; brave plugin requires >= 2026.6.8`.
  **Operator action:** run `clawctl agent upgrade <agent>` (which now
  installs `2026.6.8` by default) before the next sync. There is no
  automated migration — the upgrade must be initiated explicitly.

### Added

- New `brave` integration type for the Brave Search API. Register once
  with `clawctl integration registry create my-brave --type brave
  --api-key <key>` (or pipe the key via `--api-key-stdin`), attach to
  any supported agent with `clawctl agent integration attach <agent>
  my-brave`, and `clawctl agent sync` writes the per-agent env shape:
  `BRAVE_SEARCH_API_KEY` on hermes (name-mapped from the
  operator-facing `BRAVE_API_KEY`), `BRAVE_API_KEY` plus
  `ZEROCLAW_web_search__search_provider=brave` on zeroclaw (both lines
  are required to actually flip the provider router off the
  duckduckgo default), and `BRAVE_API_KEY` on openclaw. Openclaw also
  installs `@openclaw/brave-plugin@2026.6.8` automatically on
  configure (idempotent, sentinel-gated) and preflights the on-host
  openclaw version against the plugin's `minHostVersion` (>= 2026.6.8)
  before any sync write. New `clawctl integration rotate <name>`
  rotates the credential and re-syncs every bound agent in one shot.
  Closes #734.
- OpenCode inference provider support. `clawctl provider registry create` now
  accepts `--type opencode` and `--type opencode-go`, with model catalog
  entries for both hosted gateways and renderer wiring for hermes, zeroclaw,
  and openclaw agents (#722).
- `clawctl agent shell <name> -- <cmd>` runs an arbitrary command on
  the host as the agent user in a full login + interactive bash shell
  (`bash -lic`) so `~/.bash_profile`, `~/.profile`, and `~/.bashrc`
  all load before the command runs — tilde expansion, PATH shims,
  virtualenvs, pipes, and redirects all work. Non-interactive;
  `--timeout` controls the kill window (default 120s, hard-capped at
  1800s; `0` means "no client timeout" but the 30-min remote cap
  still applies). Linux hosts only in v1 (macOS returns a clear
  preflight error, tracked separately). Closes #761.

### Changed

- Default openclaw install target bumped from `2026.5.28` to `2026.6.8`.
  `clawctl agent create --type openclaw` and `clawctl agent upgrade`
  now install `2026.6.8` by default; manifest entries added for
  ubuntu 22.04 / 24.04 (x86_64) and macos arm64. Existing agents pinned
  to a specific `--version` are unaffected.
- Openclaw brave-plugin preflight (`_get_host_openclaw_version`) is now
  forked per OS — Linux uses `/home/<agent>/.openclaw/bin/openclaw`,
  macOS uses `/Users/<agent>/.openclaw/bin/openclaw`, with PATH-fallback
  safelists matching each OS's install playbook. The Linux-only
  hardcoded path that shipped earlier in `[Unreleased]` would have
  silently fallen through to a system-PATH binary on Darwin.

### Fixed

- openclaw renderer no longer emits `{"allow": true}` for entries in
  `channels.discord.guilds.<id>.channels.<id>`. openclaw 2026.5.28+
  rejects `allow` as an additional property
  (`must not have additional properties: "allow"`); presence in the
  channels map alone permits the channel under
  `groupPolicy: "allowlist"`. The legacy `clm` CLI's discord setup
  prompt (`cli/agent.py`) emitted the same shape and is patched in
  the same change. The canonical renderer also now emits
  `channels.discord.groupPolicy: "allowlist"` explicitly so the
  channel-presence semantics no longer depend on openclaw's implicit
  default. **Operator action:** if you have hand-edited
  `~/.openclaw/openclaw.json` on an agent host running openclaw
  2026.5.28+, remove `"allow": true` from each
  `channels.discord.guilds.<id>.channels.<id>` entry (leave the entry
  as `{}`), or re-run `clawctl agent configure <agent>` /
  `clawctl agent sync <agent>` to re-render the file.

### Documentation

- Landing page audit: restructured the GitHub README first-success path —
  added a Support Matrix near the top (control/host OS, agent runtimes,
  providers, channels), dropped the deliberate `xclm SSH verification
  failed` step from the 5-Minute Setup, added **Tested on Ubuntu** and
  **Tested on macOS** badges, and updated FAQ #1 to reflect macOS
  end-to-end support.
- Renamed the generic noun "Claw" / "Claws" → "Agent" / "Agents" across
  the README, AGENTS.md, the Docusaurus landing (tagline, hero,
  HomepageFeatures), website docs (intro, architecture, configuration,
  CLI reference, skills, fleet management, hermes/memory pages), and the
  repo-rooted docs index. Brand names (Clawrium, OpenClaw, ZeroClaw,
  IronClaw, NemoClaw, Hermes) are preserved, as are real on-disk
  identifiers (`*claw` systemd glob, `claw_supports_memory` Python
  symbol).
- Replaced remaining `clm` references with `clawctl` on the website
  landing's `HomepageFeatures` ASCII diagram and sample output, and in
  the `troubleshooting.md` setup-snippet placeholder. Dated migration
  blog posts and `docs/releases/*/CHANGELOG.md` archives are intentionally
  left untouched.
- Added the **"Agent Fleet Manager"** subtitle to the Clawrium hero on
  the Docusaurus landing (via the site tagline) and to the centered
  intro on the GitHub README.
- Upgraded Hermes and ZeroClaw status from 🚧 in-development to ✅
  fully supported across the README Support Matrix, README "What is an
  Agent?", `HomepageFeatures` TSX card, `website/docs/intro.md` (list +
  FAQ #2), and `website/docs/architecture.md`. OpenClaw / Hermes /
  ZeroClaw are now uniformly listed as the three fully-supported
  agent types; IronClaw remains planned.
- Rewrote the README 5-Minute Setup to surface the xclm bootstrap as
  explicit numbered steps: (1) `clawctl service init` on the control
  machine, (2) `clawctl host create` on the control machine to generate
  the per-host keypair and print the host setup commands, (3) SSH into
  the host and paste the printed block (Linux example inlined), (4)
  re-run `clawctl host create` to register the host, (5) provider +
  agent install + start + chat. Replaces the implicit "prerequisite"
  callout that hid the bootstrap step.

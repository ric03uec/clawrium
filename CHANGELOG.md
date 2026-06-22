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

- **`clawctl audit show`, `clawctl audit tail`, and `clawctl audit
  stats` now require explicit scope** (#780). Each of these read
  verbs exits 2 unless invoked with either `--agent <name>` (filter
  to one agent's entries) or `--all` (the unscoped global view that
  also surfaces legacy rows written before the `agent_name` schema
  field existed). The two flags are mutually exclusive. There is no
  automated migration — operators and any scripts, cron jobs, or
  skills that ran these commands unscoped MUST update to pass
  `--all` for the previous behavior, or `--agent <name>` to scope
  to a single agent. The new `clawctl agent audit <name>` command
  is the recommended per-agent read surface and is equivalent to
  `clawctl audit show --agent <name>`. The `--actor`, `--result`,
  `--session-id`, `--grep`, `--last`, `--date`, and `--json` flags
  on `show` retain their old semantics and compose with the new
  scope flag.

- **`clawctl agent sync --workspace` is removed.** Use `--no-restart`
  for canonical render + workspace overlay without a unit restart, or
  `--workspace-only` to push the operator overlay alone. There is no
  automated migration — operators must update any scripts or CI that
  pass `--workspace`. The deprecated flag now exits 2 with the
  replacement guidance on stderr; in `-o json` mode it produces a
  parseable error object on stderr and zero stdout bytes. Issue #760.

  **Zeroclaw bearer rotation extends to both replacements (Phase 2,
  #768).** `clawctl agent sync --workspace-only` and
  `clawctl agent sync --no-restart` against a zeroclaw agent now
  rotate the gateway bearer on every invocation, matching the
  full-flow `sync` contract documented in AGENTS.md "Gateway Token
  Lifecycle (zeroclaw)". Remote `clawctl agent chat` sessions against
  a zeroclaw agent will get a clean 401 on their next request after
  any `sync` flavor and must reconnect. Local chat reconnects
  transparently. **Operator action:** if you previously relied on
  `--workspace-only` to leave the bearer untouched (no documented
  reliance, but worth calling out), expect token rotation now.

  **Hermes `~/.hermes` is shared between operator overlay and
  Clawrium-managed paths (Phase 3, #769).** Hermes is the only agent
  whose workspace overlay destination root (`~/.hermes`) coincides
  with `core/render.py` output (`config.yaml`, `.env`),
  `skills_apply.yaml` writes (`skills/clawrium/`), and the daemon's
  own SQLite state (`state.db`, `state.db-journal`, `state.db-wal`,
  `state.db-shm`, `sessions/`, `logs/`). The manifest's exclude list
  reserves every one of those paths. **Operator action:** if you have
  files at any of those paths in your local hermes workspace slot
  (`~/.config/clawrium/agents/hermes/<name>/workspace/`), they will
  surface as `WorkspaceExcluded` events and never reach the host. Move
  them elsewhere or accept that they are filtered. There is no
  automated migration.
- **openclaw brave plugin now requires openclaw `>= 2026.6.8`** (previously
  `>= 2026.4.10`). Any host running openclaw in the `2026.4.10..2026.6.7`
  range with the brave integration attached will hit a hard
  `CanonicalSyncError` on the next `clawctl agent sync` with the message
  `openclaw on '<host>' is <X.Y.Z>; brave plugin requires >= 2026.6.8`.
  **Operator action:** run `clawctl agent upgrade <agent>` (which now
  installs `2026.6.8` by default) before the next sync. There is no
  automated migration — the upgrade must be initiated explicitly.

### Added

- **`clawctl agent audit <name>` — agent-scoped audit trail** (#780).
  A new read-only command that filters `clawctl audit` output to one
  agent's entries via a positional `<name>`. Composable with
  `--actor`, `--result`, `--session-id`, `--grep`, `--last`,
  `--date`, and `--json`. Legacy rows (no `agent_name` field)
  intentionally do not surface — only the unscoped global view
  (`clawctl audit show --all`) shows them. Unlike every other
  `clawctl agent <verb> <name>` surface, this command does NOT
  reject `<name>` values that are missing from `hosts.json` — the
  audit trail outlives the agent, so inspecting a deleted agent's
  history is a first-class use case. When the result is empty AND
  the name is not currently registered, a one-line stderr notice
  (`Note: '<name>' is not a registered agent…`) flags likely typos;
  exit code stays 0.

- **`agent_name` field on the audit-trail schema** (#780).
  `clawctl audit log` accepts `--agent <name>` to populate the new
  field; downstream `clawctl audit show / tail / stats` accept
  `--agent <name>` to filter and `--all` to bypass scoping. The
  schema version stays at `"1"` because the change is additive and
  reads are tolerant — pre-#780 rows render as "unscoped" and only
  appear under `--all`. `audit stats` adds a `By agent:` breakdown.
  Formatter output gains a fixed-width agent column so scoped and
  unscoped rows align in mixed listings; agent names are
  bidi-sanitized before terminal emission.

- **Workspace overlay sync (openclaw + zeroclaw + hermes, Ubuntu).**
  Files dropped under `~/.config/clawrium/agents/<type>/<name>/workspace/`
  are now mirrored onto the agent host at the per-agent
  `destination_root` on every `clawctl agent sync` and
  `clawctl agent configure`. Two new sync flags: `--workspace-only`
  pushes the overlay alone (skips canonical render / restart / verify)
  and `--no-restart` runs canonical + overlay without flapping the
  unit. The per-agent manifest declares its overlay shape via
  `features.workspace_overlay.destination_root` (manifest-driven so
  third-party manifests can opt in) plus an optional `excludes` list.
  Per-type destinations: openclaw `~/.openclaw/workspace`
  (no excludes), zeroclaw `~/.zeroclaw/workspace` (no excludes; every
  sync also rotates the gateway bearer per #437), and hermes
  `~/.hermes` (excludes reserve `config.yaml`, `.env`, `auth.json`,
  `state.db`, `state.db-{journal,wal,shm}`, `sessions/`, `logs/`,
  `skills/clawrium/` — the canonical-render and daemon-managed paths
  shared with the destination root). The architecture is Ansible-only:
  a new per-agent `playbooks/workspace.yaml` is the single host-write
  path; Python `core/workspace_sync.py` is a thin enumerator/stager
  that filters symlinks, applies manifest excludes, and floors
  secret-pattern files (`*.key`, `*.pem`, `*.env`, `*credentials*`,
  `*secret*`, `*token*`, `*password*`) to mode 0600 regardless of
  local perms. Hermes' playbook adds a per-file `workspace_excluded`
  Jinja filter at the copy boundary that mirrors the Python
  `_is_excluded` semantics exactly — belt-and-suspenders so a bypass
  at the Python layer cannot overwrite reserved files. Bidi/zero-width
  codepoints in operator-controlled paths are stripped at the NDJSON /
  text emission boundary so a hostile workspace filename cannot spoof
  terminal output. macOS support is deferred to follow-up subtasks
  #770 (openclaw), #771 (zeroclaw), and #772 (hermes) — the
  `workspace_macos.yaml` stubs return a clean Ansible `fail:` for
  now. Closes Ubuntu-side Phases 1–3 of #760
  (issues #767, #768, #769).
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

- GUI agent detail page now renders its shell instantly and loads each
  runtime section progressively. The single backend route was split
  into `/api/fleet/agents/{key}` (cheap, local — hosts.json only) and
  `/api/fleet/agents/{key}/health` (the slow SSH probe plus the
  registry version lookup). A failed or slow probe no longer blanks
  the page; the header, tabs, and provider/skills cards stay
  interactive while the status pill and upgrade badge populate on
  arrival. `latest_supported_version` moved off the static endpoint
  onto `/health`. Closes #758.
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

- **`clawctl audit show --grep <pattern>` no longer raises a Python
  traceback** when the pattern is not a valid regex (#780). A
  malformed pattern (e.g. `--grep '['`) now exits 2 with
  `Error: invalid --grep regex: <details>` and a hint, matching the
  rest of the audit error surface.

- **`clawctl audit show --date <value>` validates the value as
  `^[0-9]{8}$`** (#780). A typo like `--date 2026-06-21` previously
  produced a silently empty result by interpolating a non-existent
  log filename; it now exits 2 with `Error: --date must be 8 digits
  (YYYYMMDD); got '2026-06-21'` and an example hint. The same
  validation applies to `clawctl agent audit <name> --date <value>`.

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

- Added a **`/create-playwright` skill** for recording browser-session demos
  with Playwright. Mirrors `/create-vhs` for browser flows: `scenes.yaml` is
  the source of truth, `docs/demos/lib/pw_compile.py` generates `driver.py`
  + intro/outro card HTML + a `compiled.json` narration timeline, and
  `narrate.py` is reused for ElevenLabs voiceover. First demo lands at
  `docs/demos/20260621-clawrium-gui-walkthrough/` — a 75-second walkthrough
  of every tab in the `clawctl gui` dashboard, embedded in the README and on
  the website's [Web Dashboard guide](website/docs/web-dashboard.md) and
  [Introduction](website/docs/intro.md).
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

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
- `tape.output_format` key in `docs/demos/<demo>/scenes.yaml` — set to
  `gif` to emit `recording.gif` from `vhs`; defaults to `mp4` (existing
  behavior). GIF outputs skip the `narrate.py` step since GIF has no
  audio container. The `/create-vhs` skill documents this in its
  scenes.yaml template and Step 6 (narration).
- `clawctl version` and `clawctl --version` now show the git commit SHA alongside the release version (#656).

### Changed

- GUI Integrations page now renders the official vendor brand SVG icon
  for every configured integration (github, gitlab, atlassian, linear,
  notion, brave, git) in place of the two-letter type badge, making
  configured rows scannable at a glance. The **Add Integration** button
  was moved out of the page header and now sits directly above the
  configured integrations list, co-located with the list it mutates
  (#786).

### Fixed

### Documentation

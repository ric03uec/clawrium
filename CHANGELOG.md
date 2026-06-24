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

- **openclaw bedrock model prefix renamed `bedrock/` → `amazon-bedrock/`.**
  The openclaw gateway's Bedrock provider is registered as
  `amazon-bedrock` upstream; the previous `bedrock/<id>` prefix caused
  `Unknown model: bedrock/<id>` errors at request time. The renderer,
  `.env.j2`, `openclaw.json.j2`, and `verify_config.py` all emit
  `amazon-bedrock/<id>` going forward.

  **No automated migration.** Operators with a previously-installed
  openclaw agent whose `hosts.json.agents.<name>.config.provider.default_model`
  starts with `bedrock/` must update it manually before the next
  `clawctl agent sync` — either edit `~/.config/clawrium/hosts.json`
  directly to replace the `bedrock/` prefix with `amazon-bedrock/`, or
  reattach the provider via `clawctl agent provider attach <agent>
  --provider <provider> --model <id-without-prefix>`. Syncing without
  the manual update will continue to write the old prefix, and the
  gateway will continue to fail with `Unknown model`.

- **openclaw brave plugin pin bumped to `2026.6.9` and
  `min_host_version` raised to `2026.6.9`.** The
  `clawctl agent sync` brave preflight now rejects hosts running
  openclaw `< 2026.6.9` when the brave integration is attached, with
  a `clawctl agent upgrade <name>` remediation hint. Operators on
  older openclaw versions who use brave must upgrade openclaw before
  the next sync.

  **Heads-up before upgrading:** `clawctl agent upgrade` on openclaw
  is known to strip provider and channel attachments (see issue tracker
  and operator notes from the wolf-i upgrade on 2026-06-18 — systemd
  reports the unit ready but `clawctl agent doctor` will show the
  attachments gone). Recommended flow: capture `clawctl agent doctor
  <name>` output BEFORE the upgrade, run the upgrade, then re-attach
  the provider + channels and run `clawctl agent sync <name>` to
  re-materialize them on the host.

### Added

- `tape.output_format` key in `docs/demos/<demo>/scenes.yaml` — set to
  `gif` to emit `recording.gif` from `vhs`; defaults to `mp4` (existing
  behavior). GIF outputs skip the `narrate.py` step since GIF has no
  audio container. The `/create-vhs` skill documents this in its
  scenes.yaml template and Step 6 (narration).
- openclaw macOS support in `clawctl agent sync`: the canonical pipeline
  now dispatches per-OS for atomic file replace (`install -g staff` on
  macOS vs per-user group on Linux), unit restart (launchctl kickstart
  with dual-label and bootstrap fallback for hermes, vs systemctl
  restart on Linux), and health verification (`nc -z 127.0.0.1 <port>`
  TCP-connect poll on macOS — chosen over `lsof -i :<port>` because
  macOS `lsof` only shows ports owned by the running user, and the
  sync runs as `xclm` while the daemon runs as `<agent_name>`; vs
  `systemctl is-active` on Linux). The macOS branches live in
  `lifecycle_macos.py` and are routed via a thin dispatcher in
  `lifecycle_canonical.py`; no `if Darwin` guards inside the canonical
  business logic. Per-instance gateway port pulled from
  `hosts.json.agents.<name>.config.gateway.port`.
- openclaw v2026.6.9 platform entries in the openclaw manifest
  (Ubuntu 24.04 x86_64, Ubuntu 22.04 x86_64, macOS ≥14 arm64).

### Changed

- GUI Integrations page now renders the official vendor brand SVG icon
  for every configured integration (github, gitlab, atlassian, linear,
  notion, brave, git) in place of the two-letter type badge, making
  configured rows scannable at a glance. The **Add Integration** button
  was moved out of the page header and now sits directly above the
  configured integrations list, co-located with the list it mutates
  (#786).
- openclaw WebSocket chat protocol negotiation now spans
  `minProtocol=3, maxProtocol=4`. openclaw v2026.6.9+ requires
  protocol 4 (the daemon rejects min=3/max=3 handshakes with
  `expected=4 probeMin=4`); the 3..4 range keeps `clawctl agent
  chat` compatible with both older daemons still on protocol 3 and
  v2026.6.9+ (#719).
- openclaw install now threads the OPERATOR'S `sys.platform`
  (normalized to the bare family name — `freebsd13` → `freebsd`,
  etc.) through to the pair script as the `operator_platform`
  inventory extravar. The daemon stores this on the paired device
  entry; `clawctl agent chat` sends the same value on subsequent
  connects. Previously the pair script recorded the AGENT HOST's
  OS (Mac mini → `darwin`) while the chat client hardcoded
  `"linux"` — every cross-platform install required UI re-approval
  to chat. Same-platform installs are unaffected (#719).

### Fixed

- `clawctl agent create` no longer guesses `platforms[0]` (the oldest
  manifest entry) when host hardware facts are missing. It now fails
  fast with `InstallationError` and tells the operator to populate
  hardware first via `clawctl host create`. Eliminates the
  `npm ETARGET: No matching version found for openclaw@0.1.0`
  class of failure (#720).

### Documentation

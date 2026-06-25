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

- `clawctl agent shell <name> -- <cmd>` now works against macOS hosts
  (#808). The new `shell_macos.yaml` playbook is selected per-OS via
  `core.playbook_resolver.resolve_shell_playbook`; the kill window is
  enforced via Homebrew's `gtimeout` (coreutils) when available, and
  the ansible-runner outer timeout is the kill backstop when it is
  not (`brew install coreutils` is suggested for the tighter window).
  The rc-file prepend sources `~/.bash_profile` first on darwin to
  match macOS login-shell convention before `~/.bashrc`.
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
- openclaw workspace overlay end-to-end on macOS (#770). The
  per-agent `workspace_macos.yaml` playbook is now a real copy pipeline
  rather than the Phase-1 deferral stub. Files dropped under
  `~/.config/clawrium/agents/openclaw/<name>/workspace/` mirror onto
  darwin hosts at `/Users/<name>/.openclaw/workspace/` on every
  `clawctl agent sync` and `clawctl agent configure`. The OS→home-root
  mapping (`/home` vs `/Users`) lives in the single seam
  `core.playbook_resolver.home_root_for`; `core.workspace_sync`
  consumes it to keep its no-OS-literal invariant intact. zeroclaw and
  hermes macOS variants remain deferred to Phases 5/6.
- zeroclaw workspace overlay end-to-end on macOS (#771, Phase 5 of
  #760). The zeroclaw `workspace_macos.yaml` playbook is now a real
  copy pipeline rather than the Phase-2 deferral stub. Files dropped
  under `~/.config/clawrium/agents/zeroclaw/<name>/workspace/` mirror
  onto darwin hosts at `/Users/<name>/.zeroclaw/workspace/` (alongside
  the canonical memory tree) on every `clawctl agent sync` and
  `clawctl agent configure`. The bearer-rotation invariant (#437)
  holds identically across Linux and macOS — every sync entry point
  (`default`, `--workspace-only`, `--no-restart`) mints a fresh
  bearer and emits exactly one `gateway_token_rotated` event. The
  hermes macOS variant remains deferred to Phase 6.
- hermes workspace overlay end-to-end on macOS (#772, Phase 6 of
  #760 — final phase). The hermes `workspace_macos.yaml` playbook is
  now a real copy pipeline rather than the Phase-3 deferral stub.
  Files dropped under `~/.config/clawrium/agents/hermes/<name>/workspace/`
  mirror onto darwin hosts at `/Users/<name>/.hermes/` on every
  `clawctl agent sync` and `clawctl agent configure`. The full
  hermes exclude list (`config.yaml`, `.env`, `auth.json`, `state.db`
  + all three SQLite WAL companion files, `sessions/`, `logs/`,
  `skills/clawrium/`) is enforced on darwin via the same per-file
  `workspace_excluded` Jinja filter the Linux variant uses — the
  adjacent `filter_plugins/clawrium_filters.py` is auto-discovered by
  Ansible for both playbook variants, so the filter logic cannot
  drift between Linux and macOS. This closes out the workspace-overlay
  macOS matrix; all three GA agent types (openclaw, zeroclaw, hermes)
  now support darwin hosts end-to-end.

### Changed

- `clawctl agent sync <openclaw-agent>` now installs the openclaw
  plugins required by attached integrations (`@openclaw/brave-plugin`
  today; generalizes via the `plugins:` block in the openclaw
  manifest). Previously the plugin install lived in
  `playbooks/openclaw/configure.yaml` only, so an operator who ran
  `clawctl agent integration attach <brave> --agent <name>` followed
  by `clawctl agent sync <name>` got a daemon with `BRAVE_API_KEY` in
  its env but no plugin to consume it — sync had to be followed by a
  separate `clawctl agent configure --stage <...>` dance for the
  plugin to materialize. With #755 the canonical sync pipeline owns
  plugin install end-to-end: install runs after the brave preflight
  and BEFORE the systemd restart, fails-loud-and-short-circuits on
  any install error (the unit is never restarted on a half-installed
  plugin), and is idempotent via a per-version sentinel
  (`.<plugin>-plugin-installed.<version>`). Install uses openclaw's
  own `openclaw plugins install --force --pin <pkg>@<ver>` CLI so
  `openclaw plugins list` actually discovers the plugin — UAT on
  esper-mac-oc proved that the pre-#755 `npm install --prefix
  ~/.openclaw` approach wrote files but did not register the plugin
  with the daemon. **Operator workflow change:** the canonical
  sequence is now `attach <integration> → sync`. The
  `attach → configure → start` path documented in the quickstart
  no longer installs plugins (configure is scoped to onboarding
  stages — providers / identity / channels — only); operators on
  the configure-then-start path must add a `clawctl agent sync` in
  between to materialize plugins. No automated migration; the next
  `clawctl agent sync` against any openclaw agent with brave
  attached will install the plugin in-place.
- openclaw `~/.openclaw/openclaw.json` is now written through the
  canonical Python renderer (`clawrium.core.render._render_openclaw_json`)
  on every code path: `clawctl agent create` (install) pre-renders a
  baseline + gateway stub via `_prerender_openclaw_install_stub`;
  `clawctl agent configure` pre-renders full canonical bytes via
  `render_openclaw(build_render_inputs(...))`; `clawctl agent sync`
  was already canonical and is unchanged. The four Ansible playbooks
  (`install.yaml`, `install_macos.yaml`, `configure.yaml`,
  `configure_macos.yaml`) now `copy: content:` the pre-rendered bytes
  instead of templating server-side. The legacy Jinja template
  `openclaw.json.j2` is deleted. End state: one writer for
  `openclaw.json` across all three lifecycle entry points (#756).
- `load_hosts()` now strips the legacy `config.provider`,
  `config.providers`, and `config.channels` mirror from every agent
  record at load time. #794 stopped writing these keys; this prunes
  any residue from `hosts.json` files written before that change so
  the file naturally shrinks on the next `save_hosts()` round-trip.
  `config.gateway`, `config.dashboard`, and `config.api_server` are
  the canonical on-disk store for those settings and are preserved
  byte-for-byte. No operator action required; this is not a breaking
  change (#795, Phase 3 of #790).
- Internal cleanup of dead code and defensive comments referencing
  the now-removed `config.provider` / `config.providers` /
  `config.channels` mirror. `lifecycle.sync_agent` and
  `lifecycle.start_agent`'s hermes pre-start reconfigure path now
  build a separate `render_payload` dict for the ansible call rather
  than mutating the persisted-config view in place; behavior is
  unchanged (#797, Phase 4 of #790, closes #790).
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

- `clawctl agent sync` on Linux no longer prints `synced (drift=0)`
  when the agent's gateway port is not actually accepting connections.
  The Linux `_verify_health` step previously only checked
  `systemctl is-active`, which our `Type=simple` units report as
  `active` the moment the daemon process is spawned — before it has
  bound the gateway port, and (for a crashlooping daemon) between
  restart cycles. Sync now follows the macOS path and also probes
  the loopback gateway port via `bash -c 'exec
  3<>/dev/tcp/127.0.0.1/<port>'`; if the port is not accepting
  within the verify timeout, sync raises `CanonicalSyncError` and
  exits non-zero with a journal-pointing remediation hint instead of
  reporting green (#812).
- `clawctl agent sync <openclaw-agent>` no longer crashes with
  `AttributeError: 'dict' object has no attribute 'replace'` when
  `hosts.json.agents.<name>.config.gateway.auth` is dict-shaped
  (`{"mode": "token", "token": "<hex>"}`). Reachable today only via
  manual `hosts.json` patches or operational recovery — install no
  longer writes the dict shape directly — but still a latent crash.
  All install / lifecycle / configure write paths and the renderer
  now route through two helpers in `core/hosts.py`:
  `read_gateway_auth` (tolerates the legacy dict shape and returns
  the bare token) and `set_gateway_auth` (single write contract,
  always persists the bare string). Read-only consumers in
  `cli/chat.py`, `core/validation.py`, the GUI fleet/agents routes,
  and the TUI fleet view continue to read directly — they only need
  presence/truthiness and never crash on a dict shape. The on-disk
  contract for `hosts.json.agents.<name>.config.gateway.auth` is now
  the bare-string bearer token; the `{mode, token}` shape lives only
  inside `~/.openclaw/openclaw.json` on the agent host, written by
  the renderer. Dict-shape `auth` self-normalizes back to the bare
  string on the next `clawctl agent configure`, zeroclaw `sync` /
  `restart` (bearer rotation), or fresh install. Openclaw `sync`
  does not write `gateway.auth` and therefore does not normalize
  a pre-existing dict shape, but it no longer crashes on one (#820).
- `clawctl agent configure <name> --stage providers --provider <litellm>`
  no longer fails at the `Verify openclaw.json configuration`
  Ansible task for litellm providers. `verify_config.py`
  (`_expected_model_id`) was missing a litellm branch and fell
  through to the raw `default_model`, so the verify step mismatched
  the correctly-rendered `<provider-name>/<model>` on disk. The
  script now mirrors `clawrium.core.render`'s litellm prefix rule
  (#819). Direct follow-up to #756 / PR #818 — the canonical render
  was right; the downstream verifier was stale.
- openclaw with a litellm provider now correctly emits
  `agents.defaults.model.primary` as `<provider-name>/<model>` on
  `clawctl agent configure`. Previously the configure path used the
  Jinja template `openclaw.json.j2`, which had no litellm branch and
  wrote the raw model id without the provider prefix — the openclaw
  daemon then fell back to `openai/<model>` and failed with
  `FailoverError: Unknown model: openai/<model>`. The fix collapses
  install / configure / sync onto a single canonical renderer (see
  the matching `### Changed` entry below) so litellm prefixing is
  handled in one place (#756).
- `clawctl agent create` no longer guesses `platforms[0]` (the oldest
  manifest entry) when host hardware facts are missing. It now fails
  fast with `InstallationError` and tells the operator to populate
  hardware first via `clawctl host create`. Eliminates the
  `npm ETARGET: No matching version found for openclaw@0.1.0`
  class of failure (#720).
- `clawctl agent sync` and `clawctl agent configure` no longer write
  `config.provider`, `config.providers`, or `config.channels` mirrors
  back into `~/.config/clawrium/hosts.json`. The Ansible payload still
  receives the overlays so templates can render the model and channel
  hulls, but the canonical stores (`providers.json` + tier-1
  `agent_record["providers"]` for providers; `channels.json` for
  channels) are now the single source of truth on disk. Eliminates
  the stale-mirror class of bugs fixed in the GUI read path by #793
  (#794, Phase 2 of #790).
- openclaw and nemoclaw also benefit from the channels strip — the
  previous bot_token/app_token scrub was guarded by `if resolved_type
  in ("hermes", "zeroclaw")`, so any accumulated stale
  `config.channels.discord.bot_token` on those types persisted
  unscrubbed. The unconditional strip now applies to all agent types
  and removes the gap on first `clawctl agent configure` after
  upgrade. No operator action required (#794).

### Changed

- Internal: `_get_host_openclaw_version_linux` and
  `_get_host_openclaw_version_macos` in `core/lifecycle_canonical.py`
  now source their per-OS home root via
  `core.playbook_resolver.home_root_for("linux" | "darwin")` instead
  of hardcoded `/home` and `/Users` literals. Behaviorally
  equivalent — the literals already matched the resolver output —
  but consolidates the OS→home-root mapping behind the single seam
  required by the no-OS-literal invariant in CLAUDE.md/AGENTS.md.
  Adds regression-guard tests that monkeypatch the seam to a
  sentinel root and assert the variant picks it up (#752).
- `clm agent configure --stage channels` (the legacy `clm` wizard) now
  prints a deprecation banner and exits with code 2 on entry. The
  wizard's prompt + Ansible-push flow no longer worked after the #794
  hosts.json mirror strip — channels collected interactively would be
  silently dropped before reaching the host. Operators must use the
  modern `clawctl channel registry create <name> --type <type>` →
  `clawctl agent channel attach <name> --agent <agent>` →
  `clawctl agent sync <agent>` pipeline. The full removal of the
  wizard module is tracked under Phase 4 of #790.

### Documentation

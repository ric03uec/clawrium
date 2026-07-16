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

- `clawctl agent doctor <name>` — read-only health diagnostics command that
  runs five checks in dependency order (SSH reachable → unit running →
  gateway reachable → token stored → onboarding complete) and prints a
  pass/fail table with per-check remediation hints.  If a check fails,
  downstream checks are marked "skipped" rather than reporting spurious
  failures (closes #903).
- `clawctl apply` now generates an ed25519 SSH keypair for new Host resources
  that declare `bootstrap: true`, printing the public key with instructions to
  add it to `authorized_keys` on the remote host. Previously the host record
  was written to `hosts.json` but no key was generated, causing every
  subsequent Ansible operation to fail with "No SSH key found for host"
  (#902).
- `clawctl host edit --hostname <new-ip>` lets operators update a host's IP
  address (e.g. after a DHCP lease renewal) without deleting and recreating
  the host record. Updates `hostname` and the primary `addresses[]` entry
  atomically; `key_id` and the SSH key are preserved. Prints a reminder to
  confirm the public key is still in `authorized_keys` on the host. (#901)

### Changed

### Fixed

- `clawctl agent doctor <name>` now works for **ethos agents** (#923). Previously the command
  failed with `Error: no renderer registered for agent type 'ethos'` because the doctor
  dispatch table only covered hermes, zeroclaw, and openclaw. Fix adds a `render_ethos()`
  Python renderer that exercises the same five Jinja2 templates as the Ansible configure
  playbook (`.ethos/.env`, `.ethos/config.yaml`, and three personality files), extends
  `GatewayInputs` with `api_key` and `internal_port` fields (populated from the gateway
  blob for ethos; default-empty for all other types), and surfaces both fields in the
  doctor gateway diagnostic block.
- Ethos configure/sync now render config through the same Python renderer doctor uses
  (#924 review of #923). `clawctl agent configure` pre-renders all five ethos config
  files via `render_ethos` and the configure playbook deploys the bytes with
  `copy: content:` instead of templating server-side; `clawctl agent sync` gains an
  ethos entry in the canonical renderer table. This collapses the dual Jinja2 render
  path (Python for doctor vs Ansible for configure) — the bug class #622 closed for
  hermes. Also from the same review: the doctor gateway block (api_key presence,
  internal_port) now appears in the default table output and is emitted only for
  ethos agents in JSON/YAML output; renderer errors surface as a structured
  `status: broken` report instead of a traceback; an explicit
  `gateway.internal_port: 0` is no longer silently replaced with the 44410 default,
  and non-numeric values produce an actionable config error; `provider`/`model`
  values in the rendered ethos `config.yaml` are now JSON-quoted so model ids with
  colons cannot produce unparseable YAML.
- Ethos agents stuck in `onboarding.state=pending` (e.g. due to SSH drop or provider API
  unreachable during configure) now auto-recover when `clawctl agent start` is called.
  `start_agent` re-runs configure before raising `LifecycleError`; if recovery succeeds
  the start proceeds normally. If it fails the error message includes the configure failure
  reason instead of the previous opaque "Run clawctl agent configure first" hint (#904).
- `clawctl agent exec`, `clawctl agent sync`, and the sync validate-phase
  unit-path probe now work correctly for ethos agents (#898). Previously,
  `agent exec` rejected ethos with "does not support exec", `sync` raised
  `ValueError` from the unit-path probe, and attaching an `openrouter`,
  `anthropic`, or `openai` provider to an ethos agent caused a
  `ProviderType not in _AGENT_TYPE_PROVIDER_SUPPORT` error. The `codex`
  device-auth provider is now also wired through `build_render_inputs`
  without requiring a stored API key.
- `clawctl agent sync` no longer prints a spurious `warning: registry record missing for <type> after sync` line for zeroclaw agents whose instance name differs from their type. The post-sync state transition now looks up the agent by its instance name instead of its type (#917).
- **ethos token refresh on start/restart (#900)**: `start_agent` now refreshes
  `ETHOS_CHAT_TOKEN` in the local secrets store immediately after the ethos
  health-check gate succeeds. Previously the daemon minted a new API key on
  every cold start but clawrium never updated the stored bearer, causing 401
  UNAUTHORIZED on the next `clawctl agent chat` call until the operator
  manually ran `clawctl agent configure --stage providers`. The fix emits a
  `gateway_token_rotated` event matching the zeroclaw contract (#437) so the
  CLI renders a yellow notice on restart.
- `clawctl agent chat <name> --once "msg"` now sends a single message,
  prints the reply, and exits with code 0 on success (non-zero on
  transport / auth / protocol error). Previously the flag was
  advertised in `--help` but short-circuited to a `Not implemented`
  message. (#918)
- Parameterized seven hardcoded operator-home paths (`/home/clawrium-d01/…`) in the zeroclaw config template so `knowledge.db`, `plugins/`, `project-reports/`, `estop-state.json`, security-ops `playbooks/` + `security-reports/`, and `workspaces/` all resolve under each agent's own home. Prevents cross-agent data collision on multi-agent hosts and recovers project-intel / knowledge features that were writing to the wrong home. Also recovers `#913`. (#911)
- Zeroclaw: preserve `[onboard_state].completed_sections` in
  `~/.zeroclaw/config.toml` across `clawctl agent sync` renders. The
  template previously hardcoded `= []`, wiping the daemon's live
  onboarding state on every sync and forcing `clawctl agent chat` to
  fail with a `Quickstart` protocol error. Fresh installs still render
  `[]`; subsequent sync reads the on-host value and threads it back
  through the render context. (#910)

### Documentation

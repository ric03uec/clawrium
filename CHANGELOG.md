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

- `clawctl apply` now generates an ed25519 SSH keypair for new Host resources
  that declare `bootstrap: true`, printing the public key with instructions to
  add it to `authorized_keys` on the remote host. Previously the host record
  was written to `hosts.json` but no key was generated, causing every
  subsequent Ansible operation to fail with "No SSH key found for host"
  (#902).

### Changed

### Fixed

- `clawctl agent exec`, `clawctl agent sync`, and the sync validate-phase
  unit-path probe now work correctly for ethos agents (#898). Previously,
  `agent exec` rejected ethos with "does not support exec", `sync` raised
  `ValueError` from the unit-path probe, and attaching an `openrouter`,
  `anthropic`, or `openai` provider to an ethos agent caused a
  `ProviderType not in _AGENT_TYPE_PROVIDER_SUPPORT` error. The `codex`
  device-auth provider is now also wired through `build_render_inputs`
  without requiring a stored API key.
- `clawctl agent sync` no longer prints a spurious `warning: registry record missing for <type> after sync` line for zeroclaw agents whose instance name differs from their type. The post-sync state transition now looks up the agent by its instance name instead of its type (#917).
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

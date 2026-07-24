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

- zeroclaw agents synced before this release wrote `knowledge.db`,
  `plugins/`, `project-reports/`, `estop-state.json`, security-ops
  `playbooks/` + `security-reports/`, and `workspaces/` under the
  previously-hardcoded operator home (`/home/clawrium-d01/.zeroclaw/`).
  After upgrading, `clawctl agent sync` re-renders `config.toml`
  pointing those paths at `/home/<agent_name>/.zeroclaw/` (or
  `/Users/<agent_name>/.zeroclaw/` on macOS). The daemon will no
  longer find data at the old location. There is no automated
  migration — move directories manually before or immediately after
  sync, for example:

  On Linux:

  ```bash
  mv /home/clawrium-d01/.zeroclaw/knowledge.db      /home/<agent_name>/.zeroclaw/
  mv /home/clawrium-d01/.zeroclaw/plugins           /home/<agent_name>/.zeroclaw/
  mv /home/clawrium-d01/.zeroclaw/project-reports   /home/<agent_name>/.zeroclaw/
  mv /home/clawrium-d01/.zeroclaw/estop-state.json  /home/<agent_name>/.zeroclaw/
  mv /home/clawrium-d01/.zeroclaw/playbooks         /home/<agent_name>/.zeroclaw/
  mv /home/clawrium-d01/.zeroclaw/security-reports  /home/<agent_name>/.zeroclaw/
  mv /home/clawrium-d01/.zeroclaw/workspaces        /home/<agent_name>/.zeroclaw/
  ```

  On macOS (substitute `/Users/` for `/home/` — consistent with the
  darwin home-root convention documented for the workspace-overlay
  macOS matrix, #770/#771/#772):

  ```bash
  mv /Users/clawrium-d01/.zeroclaw/knowledge.db      /Users/<agent_name>/.zeroclaw/
  mv /Users/clawrium-d01/.zeroclaw/plugins           /Users/<agent_name>/.zeroclaw/
  mv /Users/clawrium-d01/.zeroclaw/project-reports   /Users/<agent_name>/.zeroclaw/
  mv /Users/clawrium-d01/.zeroclaw/estop-state.json  /Users/<agent_name>/.zeroclaw/
  mv /Users/clawrium-d01/.zeroclaw/playbooks         /Users/<agent_name>/.zeroclaw/
  mv /Users/clawrium-d01/.zeroclaw/security-reports  /Users/<agent_name>/.zeroclaw/
  mv /Users/clawrium-d01/.zeroclaw/workspaces        /Users/<agent_name>/.zeroclaw/
  ```

  This BREAKING entry closes both #911 (path parameterization) and
  #913 (project-intel / knowledge features recovered as a
  side-effect once the paths point at the agent's own home).

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

### Documentation

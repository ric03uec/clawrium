# Release 26.7.3 — openclaw sandboxed under NemoClaw

Archived changelog for the **26.7.3** release. This is the frozen record of
everything that shipped in this version; the working changelog for the next
release lives at the repository root in [`CHANGELOG.md`](../../../CHANGELOG.md).

Versions follow [SemVer](https://semver.org/), and the project tracks a
calendar versioning convention: `YY.M.PATCH`.

## [26.7.3]

### BREAKING

- **`clawctl agent sync` now wires github + git integrations end-to-end (#649).** Attaching a `clawrium-github` integration to a hermes, openclaw, zeroclaw, or ethos agent and running `clawctl agent sync <name>` now runs `gh auth login --with-token` and `gh auth setup-git` on the host as the agent user, so raw `git push` / `git pull` over HTTPS from an agent shell works with no manual steps. Same for `git`-type integrations: `~/.gitconfig` `[user]` / `[init]` / `[pull]` / `[core]` sections are rendered at sync time.
  - **Migration**: none for operators — the first `clawctl agent sync` after upgrading materializes the fix. Existing hermes/openclaw agents that were provisioned before this release and never had `gh auth setup-git` run manually will get `~/.gitconfig` populated on their next sync.
  - **Playbook contract change**: the `Render ~/.gitconfig for each git integration` and `GitHub CLI authentication block` tasks are **removed** from every `configure.yaml` (hermes, openclaw Linux + macOS, zeroclaw, ethos). Any third-party fork that invoked those playbooks directly must move github wiring to their sync path.
  - The `src/clawrium/platform/templates/gitconfig.j2` template file and the `shared_template_path` Ansible extravar are **deleted** — no consumers remain.
- **`clawctl agent create --type openclaw` now requires `--provider` (#11 / #946).**
  NemoClaw's `install.sh` bundles substrate install with sandbox
  onboarding, and onboarding step 3/8 demands a provider or install
  crashes with a half-configured sandbox on the host. Every openclaw
  create must now name a registered provider whose API key sits in the
  secrets store; the install path threads `NEMOCLAW_PROVIDER` +
  `NEMOCLAW_PROVIDER_KEY` + `NEMOCLAW_POLICY_MODE=suggested` +
  `NEMOCLAW_SANDBOX_NAME` into NemoClaw's install.sh and auto-attaches
  the provider to `hosts.json.agents.<name>.providers` on success. No
  post-install `configure` step is required for `clawctl agent chat`
  to work end-to-end. Recovery for scripted workflows: `clawctl
  provider registry create` a provider first, then re-run with
  `--provider <name>`. Other agent types (hermes, zeroclaw, ethos) are
  unchanged — the split `create → configure` lifecycle stays intact
  for them.

  §7.5 answered with Option A (env-var handoff into sandbox), not the
  guessed `nemoclaw <sandbox> gateway provider add` argv shape. The
  fail-closed `gateway_register_provider` seam in `core/nemoclaw.py`
  is kept as a future-proofing surface for a gateway-forwarded auth
  substitute; today the sandbox reads bearers from its own env like
  bare openclaw always did.

- **Openclaw is now sandboxed under NemoClaw (#11 / #945).** New
  openclaw creates go through `install.sh` with the NemoClaw
  substrate; `runtime: nemoclaw` is recorded in `hosts.json`. Existing
  bare openclaw records are **grandfathered** — they continue to
  sync + run untouched until you explicitly `remove + create` them.
  The `runtime != "nemoclaw"` acceptance in
  `core/lifecycle_canonical._openclaw_nemoclaw_onboard` is intentional
  so operators can upgrade Clawrium without touching working prod
  agents. To migrate an individual agent at your own pace:

  ```bash
  clawctl agent delete <name>
  clawctl agent create --type openclaw --host <host> --name <name> --provider <provider>
  ```

  Full migration notes live in the
  [Migration appendix](#migration-bare-openclaw--nemoclaw-sandbox) at
  the bottom of this file. macOS openclaw remains blocked at install
  pending an upstream NemoClaw darwin binary (#11 §7.2). Ubuntu 24.04+
  is the supported floor for sandboxed openclaws.

- **Removed the `nc` agent-type alias.** The alias was stale — no
  `nemoclaw` agent type exists in the registry, so `clawctl agent
  create --type nc <…>` was silently mapping to a nonexistent target
  instead of failing loudly. Recovery: pass a real agent type
  (`--type openclaw`, `--type zeroclaw`, `--type hermes`, `--type
  ethos`). No automated migration — the alias had zero live use sites
  in bundled Clawrium code. Part of Phase 1 groundwork for the
  NemoClaw runtime substrate (#11 / #943).

- **Zeroclaw path parameterization moves seven on-disk paths (#911).**
  zeroclaw agents synced before this release wrote `knowledge.db`,
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

- `clawctl host validate <hostname>` — read-only fleet-visibility probe
  that runs `nemoclaw status <sandbox>` for every openclaw agent on the
  host and reports per-agent health in a table. Exits 0 when all
  sandboxes are healthy, 1 when any sandbox is unhealthy or a legacy
  bare record blocks the probe. Supports `-o table|json|yaml`.
  Phase 3 of the NemoClaw rollout (#11 / #945).
- `clawctl agent get` now shows a `RUNTIME` column at the end of the
  default table. Openclaw rows render `nemoclaw@<version>`; other
  agent types render `-` so the schema stays uniform. Wide view
  keeps the previous columns and appends `RUNTIME` before `INSTALLED`
  (#11 / #945).

- NemoClaw runtime substrate (`v0.0.97`) is now installed as part of
  `clawctl host prepare` for openclaw hosts. New openclaw agents are
  provisioned into a NemoClaw sandbox — `clawctl agent get` records
  `runtime: nemoclaw` in the agent's `config` block, and every
  `clawctl agent sync` short-circuits before restart if the sandbox
  fails to onboard. Existing bare openclaw agents keep their shape
  and continue to sync cleanly through Phase 2 (Phase 3 / issue #945
  is the breaking cut-over that removes the bare path). Host prereqs
  the substrate depends on (Ubuntu >= 24.04, >= 8 GB RAM, >= 20 GB
  disk, Docker Engine, NVM + Node 22.16) are asserted / installed by
  the same host-prep phase. macOS openclaw installs are blocked at
  preflight pending an upstream NemoClaw darwin binary (see #11 §7.2).
  Part of Phase 2 of the NemoClaw rollout (#11 / #944).
- `clawctl doctor nemoclaw` — read-only probe that verifies the pinned
  NemoClaw upstream release
  ([`NVIDIA/NemoClaw`](https://github.com/NVIDIA/NemoClaw)) is
  reachable, the pinned tag exists, and the local architecture is
  supported. The probe never downloads the tarball and never touches
  any host. Phase 1 of the NemoClaw rollout (#11 / #943); Phase 2
  wires the runtime into OpenClaw's install path.
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

- **CI workflow hardening (#471)**: pinned all floating action tags to
  commit SHAs across `publish.yml`, `test.yml`, and `docs.yml` with
  release-URL comments (B1, S3). Added pre-release guard to
  `publish.yml` (W3), version/tag parity check (W4), `contents: read`
  permission (W5), and Python matrix `3.10–3.12` to `test.yml` (W6).
  Switched publish pipeline to `make test-cov` (W1), `uv sync --frozen`
  (W2), wheel smoke test (S1), and `skip-existing: true` on PyPI
  publish (S2). Note: S4 (fail-fast reorder) is deferred to a follow-up
  PR as it changes pipeline semantics.

- Removed the legacy `src/clawrium/cli/skill.py`, `host.py`,
  `integration.py`, and `provider.py` modules (#707, Phase 1). These
  four files were orphaned when the `clm` entry point was deleted in
  #706 — no code in `src/` or `tests/` imported them. Deleting them
  removes ~2.9k LOC of dead code without touching any behavior.
  Remaining hybrid `cli/*.py` modules (chat, agent, memory, etc.) are
  tracked for staged removal in follow-up phases on #707.

### Fixed

- `git push` / `git pull` over HTTPS from a hermes or openclaw agent shell now works out of the box when a `github` integration is attached (#649). Previously `gh auth login` had to be run manually via SSH after every fresh agent create — the modern `clawctl agent sync` pipeline never ran the github-wiring block that lived in the (largely-unreachable) `configure.yaml`. See the BREAKING entry for the sync-path lift.

- Clearer error when `clawctl agent create` runs against a host whose
  facts have not been (or could not be) gathered. Instead of formatting
  manifest requirements against sentinel values (`"host has ubuntu
  unknown"`, `"host has 0MB"`), the CLI now enumerates the exact missing
  facts (`os`, `os_version`, `memtotal_mb`), suggests re-running
  `clawctl host create` or passing `--version`, and points at #738 for
  the Docker-container case (#737).

- **Security (#453)**: `clawctl agent` CLI now sanitizes remote-host
  messages and exception strings before printing them. `console.print`
  sites in `src/clawrium/cli/agent.py` (`on_event` lifecycle callbacks,
  `LifecycleError` / generic exception interpolations, error-string
  return paths, and `_print_configure_warnings`) previously rendered
  values sourced from ansible-runner artifacts and remote daemons
  without stripping C0/C1 control bytes and Unicode bidi / zero-width
  codepoints. A compromised remote host could visually reorder the
  operator's terminal (RLO/LRO) or hide content (ZWSP/ZWJ) in a
  routine `clawctl agent sync` / `restart` / `remove` run. Both
  `rich_escape()` and the canonical `sanitize()` from
  `cli/output/_sanitize.py` are now applied at every render boundary.
- `tests/test_gui_routes_fleet.py::test_fleet_health_returns_200_under_concurrent_clients` and `test_fleet_health_host_filter_forwarded` — module-level `asyncio.Lock()` (`_LAST_ACCESS_LOCK`) was bound to the first pytest event loop, causing `RuntimeError: Lock is bound to a different event loop` on subsequent tests. Migrated to the same per-loop lazy accessor pattern (`_get_last_access_lock`) already used for the fleet-health semaphore. The concurrent-clients test also switched from `executor.shutdown(wait=False, cancel_futures=True)` to a `with`-block so futures complete normally instead of being force-cancelled, eliminating spurious `CancelledError` (#676).

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
- Zeroclaw: preserve `[onboard_state].completed_sections` in
  `~/.zeroclaw/config.toml` across `clawctl agent sync` renders. The
  template previously hardcoded `= []`, wiping the daemon's live
  onboarding state on every sync and forcing `clawctl agent chat` to
  fail with a `Quickstart` protocol error. Fresh installs still render
  `[]`; subsequent sync reads the on-host value and threads it back
  through the render context. (#910)

### Documentation

### Internal

- Removed ~640 lines of unreachable legacy wizard body from
  `_run_channels_stage` in `src/clawrium/cli/agent.py`, plus the
  `_build_legacy_discord_channels_block` and `_sync_channel_config`
  helpers whose only production callers lived in that dead body
  (#860). `_run_channels_stage` is now typed `-> NoReturn` since it
  always exits. No user-visible change: `clawctl agent configure
  <name> --stage channels` continues to print the deprecation guidance
  and exit 1.

---

## Migration: bare openclaw → NemoClaw sandbox

New openclaw agents are sandboxed under
[NVIDIA NemoClaw](https://github.com/NVIDIA/NemoClaw). `runtime:
nemoclaw` gets recorded in `hosts.json` at create time. Existing bare
openclaw records (installed before this release) are **grandfathered**
— they keep syncing + running until you explicitly migrate them.

There is no hard cutover: `clawctl agent sync` continues to work for
bare records. Migrating each agent is opt-in, at your own pace.

### Do I have bare openclaws?

Run:

```bash
clawctl agent get -o json | jq -r '
  .[] | select(.type == "openclaw" and (.runtime // "" | test("nemoclaw") | not))
       | .name
'
```

Every name printed is a bare openclaw. Migrating is recommended (the
sandbox model is the go-forward substrate) but not required.
Alternatively, on any host that runs openclaw:

```bash
clawctl host validate <hostname>
```

Bare records show up as `legacy` in the STATUS column with detail
`no sandbox_name in hosts.json — remove + re-create`. The command
exits non-zero when any openclaw is legacy or unhealthy.

### Migration steps (per affected agent)

There is **no automated migration**. Provider/channel/integration/skill
attachments survive the round-trip because they are captured by
`set_installing` (#816) — you do not have to re-attach providers, but
you MUST re-configure the sandbox so the freshly-onboarded NemoClaw
container has your provider credentials:

```bash
# 1. Remove the bare agent — this ALSO tears down any orphaned
#    systemd unit, per-user home directory, and (post-#945) NemoClaw
#    sandbox that may already exist for the name.
clawctl agent remove <name>

# 2. Re-create — the new record is stamped with runtime=nemoclaw and
#    sandbox_name=<name> automatically. `create` runs the install
#    playbooks which now include NemoClaw host-prep (install_prereqs
#    + install_nemoclaw) as of Phase 2.
clawctl agent create --type openclaw --host <host> --name <name>

# 3. Configure — writes provider config through to the sandbox.
clawctl agent configure <name>

# 4. Start.
clawctl agent start <name>

# 5. Confirm the sandbox is healthy.
clawctl host validate <host>
```

### What survives, what does not

Survives (captured by `set_installing` before the wipe-and-recreate):

- Provider attach records (`clawctl agent provider attach`)
- Channel attach records
- Integration attach records + secrets
- Skills attached to the agent
- Workspace overlay under `~/.config/clawrium/agents/openclaw/<name>/workspace/` (re-pushed on next sync)

Does not survive:

- Runtime state inside the bare openclaw process (in-flight sessions,
  daemon caches). Bare openclaw kept these on the host filesystem
  under `/home/<name>/.openclaw/`; the wipe-and-recreate deletes that
  tree. If you need any of it, rsync it off the host before running
  `clawctl agent remove`.
- Any manual edits to `/etc/systemd/system/openclaw-<name>.service` —
  the unit is regenerated by the install playbook.

### Host prerequisites

The NemoClaw substrate has stricter host prereqs than bare openclaw:

- Ubuntu 24.04+ (Debian 12 is unverified; other distros unsupported)
- ≥ 8 GB RAM
- ≥ 20 GB disk
- Docker Engine (installed by `install_prereqs.yaml`)
- NVM + Node 22.16 (installed by `install_prereqs.yaml`)
- Agent user in the `docker` group (added by `install_prereqs.yaml`)

Hosts that do not meet these floors will fail `install_prereqs.yaml`
with a specific message pointing at the missing prereq. macOS hosts
are blocked at install pending an upstream NemoClaw darwin binary
(#11 §7.2) — there is no migration path for macOS openclaw in this
release.

### Rollback

There is no in-place rollback. If a migration fails, pin the previous
Clawrium release (26.7.2), re-install the bare openclaw record, and
open an issue at
[ric03uec/clawrium#issues](https://github.com/ric03uec/clawrium/issues)
with the `install_prereqs.yaml` or `install_nemoclaw.yaml` failure
output.

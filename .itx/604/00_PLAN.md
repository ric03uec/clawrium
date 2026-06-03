# Issue #604 — Openclaw on macOS

**Issue:** https://github.com/ric03uec/clawrium/issues/604
**Extends:** #469 (Mac OS install support — closed, hermes only)

## Customer Outcome
A user runs `clawctl agent create <name> --type openclaw --host <mac-host>` against a prepared Mac host and gets the same install → configure → start → dashboard lifecycle as Linux, with hermes optionally running on the same Mac.

## Investigation Findings (from reading the codebase)

### Dispatcher — fully built, nothing to change
`src/clawrium/core/playbook_resolver.py` is the single fork point:
- `resolve_base_playbook(os_family)` → `platform/playbooks/base{,_macos}.yaml`
- `resolve_agent_playbook(agent_type, op, os_family)` → `registry/<type>/playbooks/{op}{,_macos}.yaml`
- `resolve_lifecycle_backend(os_family)` → `core.lifecycle` (Linux) or `core.lifecycle_macos` (Darwin)

Convention is documented in the resolver docstring and locked in by AGENTS.md / prior feedback (`[[feedback_dispatcher_only_os_fork]]`). No `if Darwin` inside Linux playbooks.

### `base_macos.yaml` already covers openclaw's prereqs
Brews `node, ripgrep, ffmpeg, uv` — openclaw's installer uses `--install-method npm`, so `node` + `npm` are already there. `ripgrep`/`ffmpeg`/`uv` are hermes-only but harmless. **No changes needed** to `base_macos.yaml` for openclaw.

### Port allocator is OS-agnostic
`src/clawrium/core/install.py:646` calls `_pick_per_instance_port(base=40000, ...)` for openclaw gateway ports — pure Python, no OS branch. Mac will allocate from the same `40000..41999` pool as Linux. **macOS imposes no relevant port limit** in this range for user-bound listeners. **Dynamic allocation works as-is.**

### Hermes manifest pattern for darwin (to copy)
```yaml
- version: "2026.5.29.2"
  os: macos
  os_version: ">=14"
  arch: arm64
  sha256: "..."
  requirements:
    min_memory_mb: 2048
    ...
```

### Openclaw install URL is platform-agnostic
Linux `install.yaml` downloads `https://openclaw.ai/install-cli.sh` and invokes it with `--install-method npm --prefix /home/<agent>/.openclaw`. Same upstream pattern hermes uses across OSes (per `install_macos.yaml` line 13 comment). Plan assumes the openclaw install script also branches internally on `uname` (to verify in Phase 1 by reading the script — single curl).

---

## Architecture Decision: Self-Contained `install_macos.yaml`

`install_macos.yaml` does the **entire** install → start → pair sequence in one playbook, mirroring Linux openclaw's `install.yaml` 1:1 (paths swapped, systemd swapped for launchd). Pairing must happen on the Mac against loopback (the mint endpoint is `127.0.0.1`-only), so the daemon must be live before the pair step — putting all of this in one playbook keeps install atomic and matches the Linux behavior contract.

**Accepted duplication:** the launchd plist write here overlaps with what `lifecycle_macos.py` does for `start/stop/restart`. We share the **plist Jinja template** between the two call sites; the bootstrap/bootout invocations are tiny enough to repeat. This trade is explicitly accepted — simpler than splitting concerns across Python + YAML for one-time install pairing.

---

## Phased Plan

### Phase 1 — Discovery (no code)
**Exit criteria:** openclaw install script's darwin path confirmed; plist template strategy decided.

1. `curl -s https://openclaw.ai/install-cli.sh | head -200` — confirm it branches on `uname` and supports darwin/arm64 via `--install-method npm`.
2. Read `scripts/pair_device.mjs` (Linux uses it today) — confirm it only needs `node` + `ws` package. Both available via brewed `node` + `npm install ws`.
3. Read `core/lifecycle_macos.py` AND `core/launchd.py` to lift the hermes plist-write pattern (label format, `launchctl bootstrap gui/<uid>`, log paths, `KeepAlive`/`RunAtLoad`). **DECIDED:** shared Jinja template lives at `src/clawrium/platform/registry/openclaw/templates/openclaw.plist.j2` — consistent with existing openclaw `.j2` files (`openclaw.json.j2`, `exec-approvals.json.j2`). Both `install_macos.yaml` and `lifecycle_macos.py` render from this single file.
4. Confirm openclaw manifest gets darwin/arm64 platform entry; sha256 `omit` per existing precedent (unpinned upstream URL).
5. Catalog hermes' launchd-specific constants in `core/launchd.py` and `core/lifecycle_macos.py` that hardcode hermes paths/labels (`LABEL_PREFIX='ai.clawrium.hermes'`, `.hermes/logs`, etc.) — these must be parameterized in Phase 3, not just inherited.

### Phase 2 — `install_macos.yaml` (full install + start + pair)
**Exit:** `clawctl agent create --type openclaw --host <mac>` succeeds end-to-end with `gateway.auth` + `gateway.device_*` in `hosts.json`.

Structure mirrors `openclaw/playbooks/install.yaml` (Linux) section-by-section, with Mac substitutions. Path swap: `/home/<agent>/` → `/Users/<agent>/`.

1. **Dispatcher guard** — `when: ansible_os_family != "Darwin"` fail at top.
2. **Agent user** — `dscl`-based create, UID ≥ 700, NFSHomeDirectory `/Users/<agent>`, group `staff` (lifted verbatim from hermes `install_macos.yaml` lines 37–82).
3. **Binary discovery + version-aware skip** — same `openclaw_per_agent_stat` / `which` / `force_install` logic as Linux, with `/home → /Users` and `/usr/local/bin` allowlist updated for Mac (`/opt/homebrew/bin` added).
4. **Install** — `get_url https://openclaw.ai/install-cli.sh`, then `install-cli.sh --prefix /Users/<agent>/.openclaw --install-method npm --version <ver> --no-onboard` as the agent user, with `PATH=/opt/homebrew/bin:...` and `HOME=/Users/<agent>`.
5. **Workspace + config dirs** — `/Users/<agent>/workspace`, `/Users/<agent>/.openclaw`, owner `<agent>:staff`, mode `0700`.
6. **Render templates** — `openclaw.json`, `exec-approvals.json`, `env` into `/Users/<agent>/.openclaw/`. Existing Jinja templates work as-is; only the destination path changes. `no_log: true` preserved on every template write (openclaw.json embeds the gateway bearer).
7. **Resolve gateway port** — `openclaw_port: "{{ config.gateway.port }}"` — same fact as Linux, populated by `install.py` from the OS-agnostic `40000..41999` allocator.
8. **Write launchd plist** — `~/Library/LaunchAgents/com.clawrium.openclaw-<name>.plist`:
   - `Label = com.clawrium.openclaw-<name>`
   - `ProgramArguments = [<resolved-binary>, gateway, run, --allow-unconfigured]`
   - `EnvironmentVariables` — read from `/Users/<agent>/.openclaw/env` and embed (launchd has no EnvironmentFile; either render env into the plist or wrap with a shell stub — match what hermes already does in `lifecycle_macos.py`).
   - `RunAtLoad = true`, `KeepAlive = { SuccessfulExit = false }`, `StandardOutPath` + `StandardErrorPath` under `/Users/<agent>/.openclaw/logs/`.
9. **Bootstrap the unit** — `launchctl bootstrap gui/<agent_uid> <plist-path>`. Register a tear-down step (`bootout`) only invoked on `force_install` (mirror Linux's `Restart openclaw service on ExecStart change` semantics).
10. **Wait for gateway port** — `wait_for: port=openclaw_port host=ansible_host timeout=60 delegate_to: localhost` — same shape as Linux.
11. **Pairing block** (lifted from Linux `install.yaml` lines 250–343, paths swapped):
    - `slurp` `/Users/<agent>/.openclaw/openclaw.json`, parse `gateway.auth.token`, validate (length ≥ 32, regex `^[a-zA-Z0-9_-]+$`).
    - Copy `scripts/pair_device.mjs` → `/Users/<agent>/pair_device.mjs`.
    - `npm install ws` in `/Users/<agent>` as the agent user (`PATH=/opt/homebrew/bin:...`).
    - `node pair_device.mjs ws://127.0.0.1:{{ openclaw_port }} {{ gateway_token_result_stdout }}` — capture stdout, parse JSON, validate `deviceToken` length ≥ 10.
    - Clean up `pair_device.mjs` + `node_modules`.
    - `set_fact … cacheable: true` for `openclaw_gateway_token / _gateway_url / _device_id / _device_token / _device_private_key` — same field names as Linux so `install.py`'s persistence path stays unchanged.
    - **Every task touching the bearer or device token: `no_log: true`** (parity with Linux ATX hardening at lines 254, 261, 275, 300, 306, 317, 342).
12. **Skip pairing when `openclaw_already_installed`** — gating identical to Linux (don't rotate credentials on re-install).

### Phase 3 — Sibling `_macos.yaml` playbooks + `lifecycle_macos.py` extension
**Exit:** All five op-level playbooks resolve cleanly on darwin; `lifecycle_macos.py` and `launchd.py` parameterized by agent type; hermes path byte-identical at call site.

**Playbooks to add** (all five — resolver throws `FileNotFoundError` for any missing op):
1. `configure_macos.yaml` — **REQUIRED** (B1 fix). Mirror hermes `configure_macos.yaml`: path-swap `/home → /Users`, replace `getent` with `dscl . -read /Users/<agent> UniqueID`, render `openclaw.json` / `exec-approvals.json` / `env` (templates already exist). No launchd restart inside playbook (Python lifecycle handles).
2. `start_macos.yaml` — idempotent `launchctl bootstrap gui/<uid>` if not loaded; `launchctl kickstart` to bring up; reuse plist on disk.
3. `stop_macos.yaml` — `launchctl bootout gui/<uid>/com.clawrium.openclaw-<name>` (preserve plist).
4. `remove_macos.yaml` — bootout + delete plist + delete `/Users/<agent>/.openclaw` + `dscl . -delete /Users/<agent>`.
5. `exec_macos.yaml` — **REQUIRED** (W2 fix). Run `<resolved-openclaw-binary> <args>` as agent user. `clawctl agent exec` is the AGENTS.md quickstart smoke test — missing playbook = silent FileNotFoundError at runtime.

All five start with the dispatcher fail-guard (`when: ansible_os_family != "Darwin"`).

**Python changes:**
6. **`core/launchd.py`** — parameterize the hermes hardcodes:
   - `LABEL_PREFIX` from `'ai.clawrium.hermes'` → derived from `agent_type` parameter with default preserving hermes behavior.
   - Log path templates accept agent-type-specific roots (`.hermes/logs` vs `.openclaw/logs`).
   - Launchd domain selectable: hermes uses `system` (`/Library/LaunchDaemons`); openclaw uses `gui/<uid>` (`~/Library/LaunchAgents`) since the plist label scheme in Phase 2.8 (`com.clawrium.openclaw-<name>`) and bootstrap target (`gui/<uid>`) are both user-domain. **[DECISION RECORD]:** openclaw runs as a LaunchAgent (gui domain), not LaunchDaemon, because pairing requires the user session active, the daemon is per-user, and mirrors how a developer would `brew install` openclaw on their own Mac. Documented in PR body.
7. **`core/lifecycle_macos.py`** — emit `com.clawrium.<agent_type>-<name>` labels (parameterized), accept agent-type in `start_agent_macos / stop_agent_macos / restart_agent_macos / remove_agent_macos`. Hermes call site keeps current signature via default value.

**Tests added in this phase** (B2/B3/B6/B7 fixes):
- `tests/core/test_launchd.py`: `test_launchd_plist_label_uses_agent_type` (hermes → `ai.clawrium.hermes-*`, openclaw → `com.clawrium.openclaw-*`); `test_launchd_domain_selection` (hermes → system, openclaw → gui).
- `tests/core/test_lifecycle_macos.py` (extend, do not rewrite): `test_lifecycle_macos_openclaw_start_uses_user_domain`; `test_lifecycle_macos_hermes_unchanged_regression` (snapshot test — hermes plist render byte-identical before/after refactor).
- `tests/core/test_playbook_resolver.py`: assert each of `install_macos.yaml`, `configure_macos.yaml`, `start_macos.yaml`, `stop_macos.yaml`, `remove_macos.yaml`, `exec_macos.yaml` resolves under `openclaw` + `darwin`. (B3 fix.)
- `tests/integration/test_macos_e2e_mocked.py` (extend): each of the four lifecycle ops on darwin/openclaw raises a clear `ClawrumError` (not `FileNotFoundError`) when launchctl returns non-zero, and leaves `hosts.json` unchanged on failure. Use the `_FakeClient` pattern from existing `test_lifecycle_macos.py`. (B6 fix.)
- `tests/platform/test_openclaw_plist_template.py` (new): `test_render_openclaw_plist_requires_port` (Jinja `StrictUndefined` raises when `port` missing), `test_render_openclaw_plist_embeds_port` (port appears in `ProgramArguments`), `test_render_openclaw_plist_keepalive_on_failure_only` (`KeepAlive = { SuccessfulExit = false }`, not bare `true`). (B7 fix.)
- `tests/platform/test_plist_drift_guard.py` (new): render the shared `openclaw.plist.j2` once via the Python loader used by `lifecycle_macos.py` and once via the Ansible loader path used by `install_macos.yaml` (load the file directly with the same Jinja env config — `StrictUndefined`, no autoescape); assert byte-equal output for a fixed input fixture. (W4 fix — guards against plist drift between the two call sites.)

### Phase 4 — Manifest entry
**Exit:** install.py's manifest-selection picks the darwin/arm64 entry on Mac hosts.

```yaml
# src/clawrium/platform/registry/openclaw/manifest.yaml
platforms:
  - version: "2026.5.28"   # current pin or bump
    os: macos
    os_version: ">=14"
    arch: arm64
    requirements:
      min_memory_mb: 2048
      gpu_required: false
```

No `sha256:` — per existing comment, openclaw installer URL is unpinned and the digest rotates without manifest bumps. Hardening tracked separately.

**Tests added in this phase** (B5 fix):
- `tests/platform/test_registry.py` (extend): `test_manifest_selects_macos_arm64_for_openclaw` (host facts `os=macos, arch=arm64` returns the new entry); `test_manifest_rejects_macos_x86_64_for_openclaw` (host facts `os=macos, arch=x86_64` returns clear `UnsupportedPlatformError`, not silent fallback to linux/x86_64 entry).

### Phase 5 — Coexistence + idempotency + port-pool + CHANGELOG + docs
**Exit:** Hermes + openclaw running on the same Mac; all unit tests green; PR mergeable.

1. **Manual coexistence check** — on a Mac already running a hermes agent, `clawctl agent create --type openclaw`. Verify:
   - launchd labels distinct: `com.clawrium.hermes-<name>` vs `com.clawrium.openclaw-<name>`.
   - Port pools disjoint: hermes dashboard `45000..46999`; openclaw gateway `40000..41999`.
   - Both UIs reachable via `clawctl agent open <name>` (loopback tunnel).
   - `hosts.json` records both cleanly under `agents`.
2. **Skip-pairing idempotency test** (B4 fix) — `tests/platform/test_openclaw_install_idempotency_macos.py`: mirror `test_install_preserves_onboarding.py`'s shape but for openclaw/darwin. Mock the install runner; assert that after a second `install_agent` call with `openclaw_already_installed=True`, the in-memory `hosts.json` fixture has identical `gateway.auth`, `gateway.device_id`, `gateway.device_token`, `gateway.device_private_key` values vs. the first call. Data-corruption regression guard.
3. **Port-pool isolation test for macOS** (W3 fix) — `tests/core/test_install_ports.py` (extend): add a darwin/openclaw fixture. Assert openclaw allocates from `40000..41999` and hermes dashboard from `45000..46999` on the same darwin host record without overlap; assert `_pick_per_instance_port` returns the existing port on a second invocation (preservation).
4. **`make test` + `make lint`** green. All Phase 3 + 4 + this-phase tests pass.
5. **CHANGELOG** `[Unreleased] ### Added`: "Openclaw can now be installed and run on macOS hosts alongside hermes (#604)."
6. **Docs** — extend `docs/host-preparation.md` only if Mac openclaw needs prereqs hermes doesn't cover (none expected; `base_macos.yaml` already brews `node`). Mirror to `website/docs/guides/host-setup.md` per AGENTS.md rule.

### Phase 6 — Real-host verification (merge gate)
Per `[[hermes_v2026_5_7_chat_bugs]]`: end-to-end on an actual Apple Silicon Mac. CI-only sign-off is not sufficient.

**Host:** `mac-test` (alias) — `100.120.88.97`, darwin/arm64. Already in `~/.config/clawrium/hosts.json`.

Verification sequence:
1. `clawctl agent create openclaw-mactest --type openclaw --host mac-test` — succeeds end-to-end.
2. Inspect `hosts.json.agents.openclaw-mactest.config` — confirm `gateway.port` in `40000..41999`, `gateway.auth`, `gateway.device_*` populated.
3. `clawctl agent configure openclaw-mactest` — provider credentials write.
4. `clawctl agent start/stop/restart openclaw-mactest` — round-trip via launchctl.
5. `clawctl agent open openclaw-mactest` — dashboard reachable via loopback tunnel.
6. Re-run `clawctl agent create` with the same name — skip-already-installed path triggers, no re-pair, device credentials unchanged.
7. If a hermes agent is already on `mac-test`, verify both launchd labels coexist; both UIs reachable; ports disjoint.
8. `clawctl agent remove openclaw-mactest` — clean teardown, no orphan plist / launchd unit / `/Users/openclaw-mactest/` dir.
9. Findings + any non-obvious snags documented in the implementation PR body.

## Out of Scope (track as follow-ups)
- Openclaw skill attach on Mac.
- `clawctl agent chat` against openclaw on Mac.
- Intel x86_64 Mac (target arm64).
- Tunnel-manager Mac hardening beyond hermes baseline.

## Risks
- **Openclaw upstream `install-cli.sh` darwin path.** If npm install fails on darwin/arm64 for the pinned version, fall back to source build or bump the pinned version. Catch in Phase 1 by running the script manually on a Mac.
- **launchd vs systemd semantics gap.** `Restart=always` (Linux systemd) maps to `KeepAlive = { SuccessfulExit = false }` on launchd, not bare `KeepAlive = true` — otherwise a clean exit triggers a respawn loop. Same fix hermes uses; copy it.
- **Plist environment loading.** launchd has no `EnvironmentFile=` analog. The Linux openclaw unit reads `/home/<agent>/.openclaw/env` via systemd's `EnvironmentFile=`. On Mac we either (a) parse `env` and inline into `EnvironmentVariables` at plist-write time, or (b) wrap `ProgramArguments` with a shell stub that sources `env` then `exec`s openclaw. Hermes already picked one — match that choice exactly.
- **Pair script `npm install ws` on Mac.** Should "just work" via brewed `node`/`npm`, but verify path: brewed npm writes `node_modules` under the cwd; the cleanup task targeting `/Users/<agent>/node_modules` must match where npm actually installed.
- **Plist-write duplication drift.** Both `install_macos.yaml` and `lifecycle_macos.py` will write the openclaw plist. If only one is updated when the launchd contract evolves, install-time and start-time plists drift. **Mitigation:** extract the plist as a shared Jinja template under `src/clawrium/platform/registry/openclaw/templates/` and render from both sites.

---

<details>
<summary>Prompt Log</summary>

**Stage**: plan
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-02T00:00:00Z
**Model**: claude-opus-4-7

```prompt
add a new issue as an extension of this https://github.com/ric03uec/clawrium/issues/469 to support openclaw on mac. basic setup remains the same, only difference is enabling openclaw alongwith hermes. dont create any files yet. just sshoe me plan
```

Follow-up 1: `yes, file a new issue with the AC and create a plan and show me the plan with the steps`

Follow-up 2: `read the existing hermes installation playbook for mac and follow exact pattern. same, needs to be dynamic port alocation unldess mac poses a limit. use exitinghermes pattern. do the investigation and update the plan`

Follow-up 3: `im good wtih duplication. use option a, update plan and give me workflow. remove option b from the plan and suggestion`

Follow-up 4 (stop-hook review): plan revised in place per a 2/5 review (docs-site-reviewer + test-coverage). Changes:
- **Phase 1.3:** template location decided — `src/clawrium/platform/registry/openclaw/templates/openclaw.plist.j2` (W1).
- **Phase 1.5:** new — catalog hermes launchd hardcodes (`LABEL_PREFIX`, log paths) that need parameterization, not inheritance (B2 context).
- **Phase 3:** added `configure_macos.yaml` (B1) and `exec_macos.yaml` (W2). Renamed phase to call out `lifecycle_macos.py` + `launchd.py` extension work (B2). Recorded LaunchAgent (gui domain) vs LaunchDaemon decision. Enumerated test files for resolver dispatch (B3), launchd parameterization (B2), lifecycle failure modes (B6), plist template render (B7), and plist drift guard (W4).
- **Phase 4:** added manifest-selector tests for darwin/arm64 and explicit rejection of darwin/x86_64 (B5).
- **Phase 5:** added skip-pairing idempotency test (B4) and macOS port-pool isolation test (W3). Renamed phase to reflect added test scope.
- **Prompt log:** Stage field corrected to `/itx:plan-create` (S1).

**Output**: Issue #604 filed. Plan rewritten around the self-contained `install_macos.yaml` approach (the "Option A" path from earlier drafts): one playbook does install + plist write + launchctl bootstrap + port wait + pair, mirroring Linux openclaw `install.yaml` 1:1 with path/launchd substitutions. Plist Jinja template extracted as a shared file so install-time and start-time writes don't drift. Six phases: discovery, install_macos.yaml, sibling playbooks (configure/start/stop/remove/exec) + lifecycle refactor, manifest entry, coexistence + idempotency + port-pool tests + docs, real-host gate.

</details>

# Plan — Issue #811: Control plane lies about zeroclaw agent state

## 1. Problem (verified against wolf-i baseline)

`clawctl agent describe clawrium-d01` reports `Status: ready` while on the host
`zeroclaw-clawrium-d01.service` does not exist in `/etc/systemd/system/`. The
divergence is silent until an operator runs `clawctl agent sync`, which
performs the *entire* render → diff → write pipeline and then fails at
`_restart_unit_linux` with:

```
restart zeroclaw-clawrium-d01.service failed (exit 5):
  Failed to restart zeroclaw-clawrium-d01.service: Unit zeroclaw-clawrium-d01.service not found.
```

Captured transcripts:

- `.itx/811/evidence/wolf-i/00-baseline-describe.txt` — `Status: ready`.
- `.itx/811/evidence/wolf-i/00-baseline-host-state.txt` — confirms unit
  missing on host; `~/.zeroclaw/` exists with `config.toml` +
  `zeroclaw-env.conf` (residual from the manual `mkdir -p` mid-#790
  verification — the directory is no longer the missing piece, the
  systemd unit is).
- `.itx/811/evidence/wolf-i/00-baseline-sync.txt` — sync runs all the
  way through render/diff/write/push_workspace, then crashes at
  `_restart_unit`.

So the live shape today is the "systemd unit missing, home dir present"
sub-case the issue calls out — and the failure surface is identical
to the original report: render+diff+write all execute against an agent
that has no daemon to restart.

## 2. Root cause

Two converging gaps:

1. `core/lifecycle_canonical.py:sync_agent_canonical` opens with
   `emit("validate", f"assembling render inputs for {agent_name}")`
   — but "validate" here means **input-assembly** validation
   (`build_render_inputs` raises if attachments / secrets are
   inconsistent). It does NOT validate that the agent is actually
   installed on the host. Detection of a missing unit happens at
   `_restart_unit` (line 1382), seven phases too late, after the
   pipeline has already written canonical files into a half-installed
   tree.
2. `core/health.py:check_claw_health` (the SSH-based prober that backs
   the GUI `/fleet/health` endpoint) only checks for the agent
   *process* via `pgrep`. When the process is absent, it falls back
   to onboarding state (`get_onboarding_status`), which reads the
   control-plane record and returns `READY`. There is no probe for
   "is the daemon actually installable" — i.e., does the systemd unit
   file exist and does the agent home directory exist.

The CLI `clawctl agent get` and `agent describe` paths
(`cli/clawctl/agent/_shared.py:agent_status`) read hosts.json with no
SSH — they cannot detect the divergence by design. That is fine as
*design*, but it means the only async detection path
(`fleet/health`) is the one that has to grow eyes for missing-install.

## 3. Position on the open question

> Should `clawctl agent get` / `agent describe` reflect on-host state,
> or is the existing "what the control plane thinks" semantic
> intentional?

**Keep `get` and `describe` local-only.** Reasons:

- These commands are used in scripts, tab completion, and the
  describe page that an operator might hit dozens of times in a
  troubleshooting session. Adding a fleet-wide SSH sweep on `get`
  would be a major latency regression and a permission-prompt
  multiplier (each host probe = one bastion keychain ask in some
  setups).
- We already have a SSH-touching surface: the GUI
  `/fleet/health` endpoint backed by `check_claw_health`. That is
  where live state belongs, and the GUI's status pill is wired to it.
- `clawctl agent doctor` is the existing "do diagnostic things now"
  command. We will extend it (out of scope for this PR if it grows
  too much; today it remains local-only — see §4 trade-offs).
- The detection that actually matters is at the point of action:
  `clawctl agent sync`. A wedged "ready" record will hit `sync` (or
  `restart`, or `configure`) sooner or later, and we want that path
  to fail fast with a repair instruction rather than scribbling
  half-rendered config onto a missing install.

So: detection lives in (a) `sync_agent_canonical`'s validate phase
(fast, actionable, every time an operator touches the host), and (b)
`check_claw_health` (passive surfacing in the GUI sweep). `get` and
`describe` keep their cheap, deterministic, no-SSH semantics. The
position is documented in `.itx/811/00_PLAN.md` (this file) and
inline in the new validate helper.

## 4. Chosen approach

Two-pronged, both small and load-bearing:

### 4a. Sync validate-phase host probe

Insert a new phase between input assembly and render in
`core/lifecycle_canonical.py:sync_agent_canonical`:

1. Open the SSH client immediately after `build_render_inputs`
   (already opened later for write — we just move it earlier).
2. Run a host-side probe via paramiko `exec_command`:
   - **Linux**: `test -e /etc/systemd/system/<type>-<name>.service && test -d <home>/<name>/.<type>`
   - **macOS**: `test -e /Library/LaunchDaemons/<label>.plist && test -d /Users/<name>/.<type>`
3. If either probe fails, raise a new exception
   `AgentInstallMissingError(CanonicalSyncError)` that names the
   missing artifact(s) and gives a concrete repair instruction:
   `clawctl agent install <name>` (or for hermes a re-install of the
   service plus dashboard plist on macOS).
4. The probe is **gated by agent type via the existing dispatchers**
   — `_host_is_macos(host)` + `home_root_for(os_family)` for path
   construction; we reuse `label_for` / `plist_path_for` from
   `core/launchd.py` for the macOS path. No literal `/home` or
   `/Library/LaunchDaemons` anywhere outside those existing helpers
   (project invariant: dispatcher-only OS fork).
5. The probe runs **before** any render call, so:
   - No half-rendered files get written to the host.
   - The error surfaces in the same `emit("validate", ...)` stream
     the CLI already renders.
   - Zeroclaw bearer rotation never fires against a missing daemon
     (we never reach that branch).
6. Open question — should the probe error short-circuit
   `dry_run=True` too? Yes. A dry-run sync still needs accurate
   reporting; rendering a diff against a host that can't actually
   restart the unit produces a misleading "would change N files" line.
   The probe is cheap (one SSH exec) so dry-run pays the same cost.

The probe re-uses the existing SSH client by hoisting `_open_ssh()`
above the render/diff calls. Because `diff_files` opens its own
session today (via `read_remote_file`), the probe's SSH client is a
new connection — acceptable: one extra round-trip ≈ 50–100ms on
LAN, and the failure mode it prevents is operator-visible minutes of
debugging time.

### 4b. Health-check missing-install probe

In `core/health.py:check_claw_health`, when `process_running=False`,
additionally probe for the agent's systemd unit + home dir. Add a
new `ClawStatus.INSTALL_MISSING` variant.

Detection layering (after the `pgrep` returns "no process"):

```
if not process_running:
    if not (unit_exists and home_exists):
        return ClawStatus.INSTALL_MISSING (with `error` naming the gap)
    # else fall through to the existing onboarding-state path
```

`INSTALL_MISSING` propagates through:

- `gui/routes/fleet.py:_agent_to_dict` (already serializes via
  `ClawStatus.value`) — no code change there.
- GUI status pill needs a color (red, same family as `failed`) —
  small frontend change in `gui/static/` if a status→color map
  exists.

### 4c. `clawctl agent doctor` — local-only, unchanged

Doctor stays no-SSH for this PR. A future change can grow a
`--probe-host` flag; that is filed as follow-up in #811's closing
comment, not implemented here. Reason: the issue's reported pain is
the `sync` failure; surfacing it in doctor too is incremental
hardening, not a blocker.

## 5. Files

| File | Change |
|---|---|
| `src/clawrium/core/lifecycle_canonical.py` | Add `_probe_host_install(client, ...)`, call it from `sync_agent_canonical` after `build_render_inputs` and before `render`. Add `AgentInstallMissingError`. Hoist `_open_ssh` if needed (or open a second short-lived client just for the probe — leaning toward second client to minimize blast radius). |
| `src/clawrium/core/health.py` | Add `ClawStatus.INSTALL_MISSING`. Extend `check_claw_health` to probe for unit + home dir when `process_running=False`. |
| `src/clawrium/core/playbook_resolver.py` | (Maybe) add a `unit_path_for(os_family, agent_type, agent_name)` helper so neither lifecycle_canonical.py nor health.py constructs `/etc/systemd/system/...` literally. |
| `tests/core/test_lifecycle_canonical.py` | Add tests: probe success → sync proceeds, probe fail (unit missing) → `AgentInstallMissingError` before render, probe fail (home missing) → same, macOS variant routes to plist path. |
| `tests/core/test_health.py` (or new file) | Add tests for `INSTALL_MISSING` status when process down + unit gone. |
| `.itx/811/evidence/wolf-i/*.txt` | Baseline + post-fix transcripts. |
| `.itx/811/evidence/kevin/*.txt` | Induced-divergence transcripts. |
| `CHANGELOG.md` | Entry under `### Fixed`. |

The macOS dispatcher work means we do **not** need to touch any
Ansible playbook — the probe is paramiko-only.

## 6. Test strategy

### Unit tests

1. `test_sync_probe_unit_missing_raises_before_render` — set up the
   stub so the probe reports unit absent; assert `_open_ssh` ran but
   `renderer` was never called and the raised exception is
   `AgentInstallMissingError` with the unit path in its message.
2. `test_sync_probe_home_missing_raises_before_render` — same shape,
   home dir absent.
3. `test_sync_probe_both_missing_lists_both` — both absent; error
   message mentions both artifacts so operator gets one-pass
   diagnosis.
4. `test_sync_probe_passes_proceeds_normally` — both present; sync
   continues into render/diff/write (this is the existing happy path
   guarded behind the new probe).
5. `test_sync_probe_macos_uses_plist_path` — host with `os=macos`,
   probe command constructs the `/Library/LaunchDaemons/<label>.plist`
   path (asserted by spying on `exec_command`'s argument).
6. `test_check_claw_health_install_missing` — process not running,
   unit + home both missing → `ClawStatus.INSTALL_MISSING` with
   error string naming both gaps.
7. `test_check_claw_health_install_present_falls_through` — process
   not running but unit + home present → falls through to
   onboarding-state path (existing behavior preserved).
8. Existing zeroclaw sync tests (`test_zeroclaw_sync_repair_failure_raises`,
   etc.) must keep passing — the new probe must be a no-op when the
   stubbed install is "present" (stub the probe to return
   `(True, True)` in `_stub_sync_environment`).

### `make test` + `make lint`

Both must pass before commit (per project memory:
`feedback_run_make_lint_before_push`).

### Real-host UAT (per issue brief)

1. **wolf-i baseline** (captured above): describe, host-state probe,
   sync failure.
2. **wolf-i after fix**: sync should fail in the new validate phase
   with a clean error referencing the missing unit + repair
   instruction. Capture transcript.
3. **kevin induce-divergence**:
   - Install fresh zeroclaw on kevin (or use an existing one).
   - On the host, `sudo rm /etc/systemd/system/zeroclaw-*.service`
     (and `daemon-reload`).
   - Run `clawctl agent describe <name>` (should still say `ready`
     — control plane unaware; that's the documented position).
   - Run `clawctl agent sync <name>` (should fail in new validate
     phase with the actionable error).
   - Run `clawctl agent describe <name>` from GUI / wait for
     `/fleet/health` poll (should show `INSTALL_MISSING`).
4. **Degenerate path coverage**: do at least one run where only the
   home dir is removed (unit present) and one where only the unit
   is removed (home present). Both should fail validate; both should
   surface in fleet/health.
5. **Happy path regression**: pick a healthy agent
   (`clawrium-triage` on wolf-i — hermes, not zeroclaw, so the
   bearer-rotation branch doesn't fire), run `sync`, confirm it
   proceeds normally.
6. **macOS coverage**: `mac-test` has `hermes-mac` in `onboarding`
   state. If it has a real install, run sync against it after
   removing the gateway plist. If not, we can simulate by passing a
   bogus `<label>.plist` path in a unit test only. Goal: confirm the
   macOS path actually exercises `plist_path_for` and routes through
   `home_root_for("darwin")`.

Save every transcript under `.itx/811/evidence/<host>/`.

## 7. Constraints honored

- **Gateway Token Lifecycle (zeroclaw)** — the new probe runs BEFORE
  the existing bearer-rotation branch. When the probe raises, no
  re-pair is attempted, no rotation event is emitted, no
  `hosts.json.gateway.auth` is overwritten. Existing
  `configure`/`sync`/`restart` bearer-rotation invariants are
  unchanged for the happy path.
- **`dispatcher-only_os_fork`** — all OS branching goes through
  `playbook_resolver.home_root_for` + a new
  `playbook_resolver.unit_path_for` (or via the existing
  `launchd.plist_path_for`). No `if Darwin` inside
  `lifecycle_canonical.py` or `health.py` beyond the existing
  `_host_is_macos` dispatcher pattern.
- **GUI consumes the same field** (`gui/routes/fleet.py`). New
  `INSTALL_MISSING` enum variant just flows through; the only
  required GUI work is the color-map entry if one exists.
- **No push without ask**, **real-host UAT mandatory** — both
  enforced in §6 above and at commit time.

## 8. Out of scope (filed as follow-up if useful)

- `clawctl agent doctor --probe-host` — diagnostic-mode SSH probe
  that runs the same install check. Useful but additive; the sync
  validate-phase is the load-bearing fix.
- A `clawctl agent repair` command that runs `install` + `configure`
  in sequence for a half-installed agent. Today the error message
  points operators at `clawctl agent install <name>`; we leave the
  multi-step repair as a doc trail.
- Periodic background reconciler that walks the fleet and writes the
  `INSTALL_MISSING` status back into `hosts.json` so `get` /
  `describe` reflect it without an SSH sweep. The intentional
  position above is "describe stays local-only"; a daemonized
  reconciler is the only way to combine "describe shows live state"
  with "describe stays cheap", and that's a much larger change.

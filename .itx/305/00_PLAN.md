# Issue #305 — Implementation Plan (v2, post-ATX review)

> **v1 → v2 changes:** Addresses 5 blocking issues from ATX review of v1. New: explicit `creates:` removal, ExecStart-change restart handler, mirrored unsafe-path validator with prescribed task ordering, expanded test specification including `start.yaml` coverage and `ansible.builtin.stat` mock event shape. Hardening gaps (installer checksum, npm pin, verbose secret logging) deferred to **#343** with explicit out-of-scope note.

## Customer Outcome

Re-running `clm agent install` on an OpenClaw agent that is already at the manifest-pinned version completes in seconds, preserves `config.gateway.device` and `config.gateway.auth` byte-identical in `hosts.json`, and never re-pairs — even on hosts where a system-wide `/usr/local/bin/openclaw` exists at a different version than the per-agent install at `/home/<agent>/.openclaw/bin/openclaw`. The systemd unit's `ExecStart` always points at the binary clawrium actually manages, and the running daemon picks up that binary without waiting for a reboot.

## Root Cause

Install and runtime use different sources of truth for which binary "counts":

- **Install** writes to `/home/<agent>/.openclaw/bin/openclaw` via `install-cli.sh --prefix /home/<agent>/.openclaw`.
- **Discovery** (in both `install.yaml` and `start.yaml`) uses `which openclaw` — which on hosts with a system-wide install resolves to `/usr/local/bin/openclaw` regardless of what was just installed.
- **Version check** (added in #163 / PR #304) reads `--version` from the `which`-discovered binary, not the per-agent one.
- **systemd `ExecStart`** runs `{{ openclaw_runtime_binary }}`, which is also set from the `which` result.

Net effect: on any host where the system-wide binary version differs from the manifest target, `openclaw_already_installed` is always false, the skip path never fires, every re-install rotates gateway/device credentials, and the actually-running daemon stays on the system-wide version indefinitely. Pre-#163 the bug was silent (skip on binary existence); post-#163 it surfaces as perpetual re-pair.

## Approach

**Option 1 from the issue: prefer per-agent binary when present.** Cheapest fix, keeps the per-agent isolation model, preserves system-wide as a fallback for legacy hosts where someone manually installed openclaw before clawrium managed it.

Rejected alternatives:
- *Option 2 (always install per-agent, drop PATH discovery):* would silently strand the existing system-wide binary on hosts that have one — and lose the "fall back to a working binary if the agent install failed mid-flight" property. Larger scope, not needed to fix this bug.
- *Option 3 (always install system-wide):* loses per-agent version pinning, larger blast radius, not aligned with the existing `--prefix /home/<agent>/.openclaw` design choice.

## Files to Modify

### 1. `src/clawrium/platform/registry/openclaw/playbooks/install.yaml`

Concrete ordered task changes (named so they don't collide with `_install_was_skipped` substring matching):

1. **New task** `Check per-agent openclaw binary` — `ansible.builtin.stat` on `/home/{{ agent_name }}/.openclaw/bin/openclaw`, register `openclaw_per_agent_stat`. Runs **before** the existing `Discover openclaw binary in PATH` task.
2. **Keep existing** `Discover openclaw binary in PATH` (the `which openclaw` task) unchanged. It runs second.
3. **New task** `Resolve openclaw binary (per-agent preferred, PATH fallback)` — `set_fact` for `openclaw_discovered_binary`:
   - `/home/{{ agent_name }}/.openclaw/bin/openclaw` if `openclaw_per_agent_stat.stat.exists`
   - else `openclaw_which_result.stdout` if `(openclaw_which_result.rc | default(1)) == 0`
   - else `''`
4. **Modify** the existing `Validate discovered binary path` task to validate `openclaw_discovered_binary` instead of `openclaw_which_result.stdout`. **Drop W3's proposed guard condition** — the per-agent path begins with `/home/`, already in the allowlist, so the validator passes unconditionally on the preferred branch and continues to gate the PATH-fallback branch. No ordering hazard.
5. **Modify** `Get installed openclaw version` to invoke `{{ openclaw_discovered_binary }} --version` and gate on `openclaw_discovered_binary | length > 0`.
6. **Modify** `Set install skip condition` so `openclaw_already_installed` is gated on `openclaw_discovered_binary | length > 0` (not `openclaw_which_result.rc`) and `openclaw_runtime_binary` is set from `openclaw_discovered_binary` with the same fallback (`/home/.../.openclaw/bin/openclaw`) when empty.
7. **Modify** the `Mark install as skipped when already installed` debug task message to the exact string: `"OpenClaw v{{ openclaw_installed_version | default('unknown') }} already installed at {{ openclaw_discovered_binary }}. Skipping binary install."` (W2). The Python `_install_was_skipped` detection matches the task **name**, not the message, so the string change is safe — confirm by grep before the rename.
8. **Modify** the `Note that --force was supplied` debug task to reference `openclaw_discovered_binary | default('<no prior install>')`.
9. **B1 — Remove the `creates:` guard** on the `Install OpenClaw CLI runtime` task. Idempotency is fully covered by `when: not openclaw_already_installed`. Today the guard would silently skip the binary install on the "per-agent at non-target version" scenario while the pairing block still rotates credentials — exactly the regression test case 2 below targets.
10. **B3 — Add `Restart openclaw service on ExecStart change` task** after the `Create systemd service file` task (which already `notify: Reload systemd`). New task:
    - Captures the unit-file write result via `register: openclaw_unit_file_result` on the existing copy task.
    - New `ansible.builtin.systemd` task with `name: "{{ agent_type }}-{{ agent_name }}"`, `state: restarted`, `daemon_reload: yes`, `when: openclaw_unit_file_result.changed`.
    - This must execute **before** the `Enable and start openclaw service` task (which is a no-op on already-active services and won't pick up the binary change on its own).

### 2. `src/clawrium/platform/registry/openclaw/playbooks/start.yaml`

Mirror the discovery order; add the unsafe-path validator (B4); add the restart-on-change handler (B3). Concrete ordered tasks (replacing today's lines 22–30 block):

1. **New** `Check per-agent openclaw binary` — `ansible.builtin.stat` on `/home/{{ agent_name }}/.openclaw/bin/openclaw`, register `openclaw_per_agent_stat`.
2. **Existing** `Discover openclaw binary in PATH` — `which openclaw`, unchanged.
3. **New** `Validate discovered PATH binary` — `ansible.builtin.fail` with the same allowlist used in `install.yaml`, **gated on**: `(not openclaw_per_agent_stat.stat.exists) and (openclaw_which_result.rc | default(1)) == 0`. This is the precise ordering called out in B4: only validate the `which` result when we're actually going to use it as the fallback. The per-agent path is allowlisted by construction (`/home/...`), so no validator needed on that branch.
4. **New** `Resolve openclaw binary (per-agent preferred, PATH fallback)` — `set_fact openclaw_runtime_binary` with the same fallback chain as `install.yaml`.
5. **Existing** `Sync systemd service file` (the `copy` task) — unchanged in body; the `ExecStart` now resolves from the new fact. Keep `register: service_file_changed`.
6. **Existing** `Reload systemd if service file changed` — unchanged.
7. **B3 — New** `Restart openclaw service if unit file changed` — `ansible.builtin.systemd` with `name`, `state: restarted`, `when: service_file_changed.changed`. Placed before the existing `Start openclaw service` task.

### 3. `src/clawrium/platform/registry/openclaw/manifest.yaml`

No changes for this bug. (Checksum field is in **#343 scope**, not here.)

### 4. Tests

Test files touched: `tests/test_install_skip.py`, plus a new `tests/test_start_binary_discovery.py` (B5).

**Mock helper to add in `test_install_skip.py`** (and reuse in the new start test file):

```python
def _stat_event(task_name: str, path: str, exists: bool) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": task_name,
            "res": {
                "stat": {"exists": exists, "path": path} if exists else {"exists": False},
                "changed": False,
            },
        },
    }
```

**Existing fixture to update (W1):** `test_install_reuses_existing_installed_name_and_reports_skip` — change the simulated discovery to emit `_stat_event("Check per-agent openclaw binary", "/home/<agent>/.openclaw/bin/openclaw", exists=True)` plus a per-agent `--version` result at the target version. Drop the `/usr/local/bin/openclaw` `which` event (or keep it at a *different* version to exercise the precedence rule). Add an assertion: `openclaw_runtime_binary == "/home/<agent>/.openclaw/bin/openclaw"` in the resolved set_fact event.

**New named test cases in `test_install_skip.py`:**

| # | Function name | Scenario | Expected |
|---|---------------|----------|----------|
| T1 | `test_install_skips_when_per_agent_binary_at_target_and_system_diverges` | per-agent stat: exists, `--version` = target; `which`: `/usr/local/bin/openclaw` at different version | skip fires; no pairing tasks observed; `openclaw_runtime_binary` is per-agent path |
| T2 | `test_install_reinstalls_when_per_agent_binary_at_non_target_even_if_system_matches` | per-agent stat: exists, `--version` ≠ target; `which`: system at target version | does NOT skip; binary install task runs; pairing tasks run |
| T3 | `test_install_falls_back_to_path_when_per_agent_binary_absent` | per-agent stat: not exists; `which`: system at target version | skip fires via PATH fallback; `openclaw_runtime_binary` is the `which` result |
| T4 | `test_install_proceeds_with_install_when_no_binary_anywhere` | per-agent stat: not exists; `which`: rc=1 | does NOT skip; install + pairing both run; `openclaw_runtime_binary` falls back to static per-agent path |

**New `tests/test_start_binary_discovery.py` cases (B5):**

| # | Function name | Scenario | Expected |
|---|---------------|----------|----------|
| S1 | `test_start_uses_per_agent_binary_when_present` | per-agent stat exists; `which` returns system path | unit file `ExecStart` resolves to per-agent path; validator does **not** run |
| S2 | `test_start_falls_back_to_path_binary_when_per_agent_absent` | per-agent stat absent; `which` rc=0 | `ExecStart` is the `which` result; validator runs and passes |
| S3 | `test_start_rejects_unsafe_path_binary` | per-agent stat absent; `which` returns `/tmp/openclaw` | playbook fails on `Validate discovered PATH binary`; unit file not rewritten |
| S4 | `test_start_restarts_service_when_unit_file_changes` | unit file content differs from on-disk version | `Restart openclaw service if unit file changed` runs with `state: restarted` |

**Python-side parser test (W4):** extend `test_openclaw_skip_detection_matches_fact_and_marker` (in whichever existing file owns it — grep before edit) with two cases:
- negative: event stream emits the `openclaw_discovered_binary` set_fact **alone** ⇒ skip NOT detected (the resolved-binary fact is metadata, not a skip signal — guards against future regressions where someone adds an over-broad substring match on it)
- positive: event stream emits the resolved-binary set_fact AND `openclaw_already_installed=True` ⇒ skip detected (the canonical skip path)

## Steps

1. **install.yaml** — apply the 10 ordered changes in §1 above (stat → which → resolve → validate-on-discovered → version check → skip-condition → debug strings → `creates:` removal → restart-on-change handler).
2. **start.yaml** — apply the 7 ordered changes in §2 (stat → which → validate-on-which-only → resolve → unit-file copy with register → daemon-reload → restart-on-change → start).
3. **Tests** — add the `_stat_event` helper, update the W1 fixture, add the 4 install-skip cases and 4 start-discovery cases above, extend the Python parser test (W4). Audit `tests/test_lifecycle.py` and `tests/test_cli_agent_start.py` for mocks that emit `Discover openclaw binary in PATH` without a matching stat event and update them (S3 from review).
4. **`make test && make lint`** — both must pass clean.
5. **Manual verification on wolf-i/maurice** (mandatory acceptance gate):
   - **Reproducer:** repeat the #305 table (runs 1/2/3) with the fix applied; `device.id` and `gateway.auth` must be byte-identical across runs 2 and 3.
   - **ExecStart convergence:** `systemctl cat openclaw-maurice.service` shows `ExecStart=/home/maurice/.openclaw/bin/openclaw …`, not `/usr/local/bin/openclaw …`, after a re-install.
   - **Live daemon swap (B3 acceptance):** `pgrep -a -u maurice openclaw` shows the per-agent binary in the cmdline within seconds of the install completing — **no reboot, no manual restart**. The daemon's reported version (`curl … /version` or whatever the gateway exposes) matches the manifest target.

## Test Strategy

- `make test` — covers all unit-level changes including the new `tests/test_start_binary_discovery.py`.
- `make lint` — `ruff check src tests`.
- Manual reproducer on wolf-i is the acceptance gate — the cred-rotation symptom and the live daemon swap are not observable from unit tests alone.

## Risks

1. **Behavior change for hosts that intentionally rely on a system-wide override.** If anyone is using a hand-installed `/usr/local/bin/openclaw` to override the per-agent binary, this fix shifts them onto the per-agent binary silently. Acceptable: the playbook's contract is "manage the per-agent install"; using the system-wide one was an accident of `which` resolution, not a feature. Surface this in the PR body.
2. **`state: restarted` on the unit causes a brief gateway downtime mid-install.** The pairing block runs immediately after this restart, which already implies a brief window of disconnection. Acceptable; matches the semantics of a "fresh install" path. On the skip path (`openclaw_already_installed=True`), the unit file should be byte-identical, so the restart task no-ops.
3. **Test fixture migration.** The W1 fixture rewrite must be carefully reviewed — it's easy to write a new fixture that passes for the wrong reason (e.g., asserting on a substring that happens to appear in both old and new task names). Mitigation: every new assertion includes the *exact* path string and the *exact* task name.
4. **`ansible.builtin.stat` event shape.** Mocks must emit `res.stat.exists` (boolean) not `res.stdout`/`res.rc` — flagged explicitly in B5; the `_stat_event` helper enforces this.

## Out of Scope

- **Migration of host records that already drifted.** Existing `hosts.json` entries for agents that have been re-paired N times will have whatever credentials the last run produced; this fix prevents *future* rotation but does not reconcile past damage.
- **Provenance of the system-wide `/usr/local/bin/openclaw` on wolf-i.** Separate operational question.
- **Installer integrity (B2), `npm install ws` pinning (W5), and verbose secret logging (W6).** Tracked in **#343**; orthogonal hardening pass, not part of the discovery-convergence bug fix.
- **`device.privateKey` storage location.** Currently lives in `hosts.json` rather than `secrets.json`; architectural inconsistency surfaced by reviewer (S2). Out of scope for this bug — file a separate issue if pursued.

## Subtasks

None — single concern (binary discovery convergence), 2 source files + 2 test files. Direct execution via `/itx:execute 305`.

## ATX Review Summary (v1 → v2)

| Blocker | v1 status | v2 resolution |
|---------|-----------|---------------|
| B1 — `creates:` defeats version skip | Not mentioned | §1 step 9: removed; idempotency covered by `when:` gate |
| B2 — installer checksum bypass | Not mentioned | Deferred to **#343** with explicit out-of-scope note |
| B3 — ExecStart change leaves daemon stale | Risk-only | §1 step 10 + §2 step 7: explicit `state: restarted when: …changed` tasks in both playbooks |
| B4 — start.yaml lacks validator | Not mentioned | §2 step 3: validator mirrored with correct ordering (stat → which → validate-only-when-which-chosen → resolve) |
| B5 — start.yaml has no tests | Not specified | §4 + new `tests/test_start_binary_discovery.py` with 4 named cases; `_stat_event` helper specified |

| Warning | v2 resolution |
|---------|---------------|
| W1 — old skip fixture simulates buggy state | §4 W1 fixture rewrite with explicit assertions |
| W2 — debug string unspecified | §1 step 7 gives exact string and confirms `_install_was_skipped` matches task name |
| W3 — validator guard rationale incorrect | §1 step 4 drops the unnecessary guard with rationale |
| W4 — Python-side parser untested | §4 W4 test extension specified |
| W5 — `npm install ws` unpinned | Deferred to **#343** |
| W6 — secrets logged at verbosity=1 | Deferred to **#343** |

Suggestions S1–S4 from the review folded into Risks (S1), Out of Scope (S2), Steps (S3 — audit `test_lifecycle.py` / `test_cli_agent_start.py`), and §1 task-naming (S4).

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning (v2 — ATX revision)
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-11T00:00:00Z
**Model**: claude-opus-4-7

```prompt
v1: /itx-plan-create 305
v2: revised in response to Stop-hook ATX review of v1 plan (5 blockers, 6 warnings, 4 suggestions). All 5 blockers resolved in plan body; B2/W5/W6 hardening gaps deferred to tracking issue #343.
```

</details>

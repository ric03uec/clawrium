# Plan — Issue #810: failed openclaw install leaves stale integration attachments that block subsequent syncs

## 1. Bug recap

`clawctl agent sync <name>` fails on a version-gate when:

- The agent record is `status=failed, installed_at=null` (a partially-completed `clawctl agent create`).
- The same agent record has one or more attached integrations whose `minHostVersion` exceeds the version of the (incompletely-installed) openclaw binary on the host.

The current pipeline at `src/clawrium/core/lifecycle_canonical.py:1245` runs the brave version-gate against the *broken* on-host openclaw — so the operator is told to "Run `clawctl agent upgrade <name>` first", but `upgrade` is itself known to strip attachments (`clawctl_upgrade_strips_attachments` memory). The only working manual unblock today is `clawctl agent integration detach`, even though the operator never asked to detach.

Surfaced on `wolf-i` during issue #790 verification (callout C1).

## 2. Root-cause hypothesis

`sync_agent_canonical` treats any sync call as an enforcement-time check against the on-host binary state, regardless of the control-plane's record of whether the install ever finished. Specifically:

1. The agent record may carry `status="failed"` and `installed_at=None`, yet `inputs = build_render_inputs(agent_name)` happily yields a `RenderInputs` carrying every attached integration.
2. The brave-version preflight at `lifecycle_canonical.py:1245-1280` SSHes into the host, asks the (probably-old or absent) openclaw binary for its version, and raises `CanonicalSyncError` if it's below the integration's floor.
3. There is no precondition that the install state must be `installed` for the version-gate to apply. The control plane has all the information needed (`claw_record["status"]`, `claw_record["installed_at"]`) but never consults it.

This is the same anti-pattern as `clawctl_upgrade_strips_attachments`: lifecycle ops fail loudly mid-recovery and force the operator to mutate the very metadata they need for the next attempt.

## 3. Solution options

### Option A — Refuse sync on incomplete-install with a clear repair hint (chosen)

Add an early guard inside `sync_agent_canonical` right after `get_agent_by_name(...)` resolves the record. If `status in {"failed","installing"}` *or* `(status is not None and installed_at is None)`, raise `CanonicalSyncError` with a message that:

- Names the actual incomplete state (`status='failed', installed_at=None`).
- Points the operator at `clawctl agent install <name>` (which already has retry-on-failed semantics — `core/install.py:449`).
- Does *not* suggest `clawctl agent upgrade` (avoids the strips-attachments class).

**Pros**: deterministic, single-point fix; preserves attachments (no detach/reattach); aligns with the bug's expected behavior (a): "route to repair/reinstall semantics". Minimal blast radius — only refuses on records that were already broken.

**Cons**: behavior change for any operator who *was* relying on `sync` to no-op against a failed agent (unlikely; today's behavior is "always raise" with a misleading hint).

### Option B — Demote version-gate to a warning when the agent record is in failed state

Keep all sync phases running but skip the brave version-gate (and skip `_openclaw_install_plugins`) when `status="failed"`. Emit a structured `incomplete_install` warning event so it shows in NDJSON / GUI.

**Pros**: matches bug's (b) softer fallback; lets the operator still flush providers/channels into hosts.json that the next `install --resume` will pick up.

**Cons**: silently restarts a probably-broken systemd unit (`restart=True` by default), which is exactly the contract the workspace-overlay guard goes out of its way to avoid (lifecycle_canonical.py:1318+). Plugin-install would be skipped, so the rendered env may carry a `BRAVE_API_KEY` line that the daemon will fail to consume. Brittle.

### Option C — Auto-detach incompatible integrations on sync against a failed agent

Detect the version mismatch + failed state and silently `remove_agent_integration` before continuing.

**Pros**: zero operator action.

**Cons**: rejected. Silently mutating attachment metadata is exactly the `clawctl_upgrade_strips_attachments` anti-pattern this issue is asking us to *break*, not perpetuate.

### Chosen: **Option A**

Reasons:
1. Directly addresses the bug's (a) expectation.
2. Preserves operator intent — the integration stays attached, the install completes, and the next `sync` flushes normally.
3. Single-file, single-call-site change inside `lifecycle_canonical.py`; small, reviewable, easy to add unit coverage for.
4. No new config / flag / contract — existing `status` field and `clawctl agent install` retry semantics carry the recovery.

## 4. File-level changes

### 4.1 `src/clawrium/core/lifecycle_canonical.py`

Add an install-state precondition just after the existing `get_agent_by_name(...)` resolution (around line 1073), *before* any SSH / render / version-gate work. Pseudocode:

```python
install_status = _claw_record.get("status")
installed_at = _claw_record.get("installed_at")
install_incomplete = install_status in {"failed", "installing"} or (
    install_status is not None and installed_at is None
)
if install_incomplete:
    raise CanonicalSyncError(
        f"agent {agent_name!r} on {hostname!r} has an incomplete "
        f"installation (status={install_status!r}, "
        f"installed_at={installed_at!r}); refusing to sync. Run "
        f"`clawctl agent install {agent_name}` to complete the install "
        f"first — your attachments are preserved."
    )
```

Rationale:
- Runs before `_open_ssh` so we don't waste a connect on a known-broken record.
- Runs before the `workspace_only` branch so even `--workspace-only` is refused on a half-install (writing operator overlay onto a failed daemon makes the state harder to reason about; #768 bearer-rotation invariant requires a running daemon to be meaningful).
- The error string deliberately avoids suggesting `agent upgrade`.
- Mentions "attachments are preserved" so the operator does not preemptively detach.

### 4.2 `tests/core/test_lifecycle_canonical.py`

Add a new `TestSyncRefusesIncompleteInstall` class that exercises four cases through `sync_agent_canonical`:

| Test                                  | `_claw_record`                                      | Expectation                                                       |
|---------------------------------------|-----------------------------------------------------|-------------------------------------------------------------------|
| `test_status_failed_raises`           | `{"status":"failed","installed_at":None}`           | `CanonicalSyncError` matching "incomplete installation" + "install" hint |
| `test_status_installing_raises`       | `{"status":"installing","installed_at":None}`       | same                                                              |
| `test_status_installed_no_timestamp`  | `{"status":"installed","installed_at":None}`        | same (covers the install.py:186 "corrupt state" branch)           |
| `test_clean_record_passes`            | `{"status":"installed","installed_at":"2026-..."}`  | proceeds (no raise from the new guard)                            |
| `test_empty_record_passes`            | `{}` (current default mock shape)                   | proceeds — legacy / pre-status records must NOT be refused        |

The empty-record case keeps every existing test in this file green (their `get_agent_by_name` mock returns `{}`).

### 4.3 No other production-code changes

- The existing brave version-gate stays untouched. It is now only reachable on records that *did* complete install at least once; its current "Run `clawctl agent upgrade`" hint is correct for that population.
- `_openclaw_install_plugins` is downstream of the new guard. No change.
- `cli/clawctl/agent/sync.py` already routes `CanonicalSyncError` through `emit_error(f"sync failed: {exc}")` (line 562). No CLI change needed; the operator sees a single clean line.

### 4.4 Documentation

- Append an entry to root `CHANGELOG.md` under `### Fixed` referencing #810. One line — keep it user-facing.

## 5. Test strategy

1. **Unit (new)** — `tests/core/test_lifecycle_canonical.py::TestSyncRefusesIncompleteInstall` per §4.2.
2. **Unit (regression)** — Existing `TestOpenclawBraveVersionPreflight` tests still pass (they mock `_claw_record={}` so the new guard short-circuits to "no-op").
3. **make lint && make test** — must be green per `feedback_run_make_lint_before_push`.
4. **Live-host UAT** — §6.

## 6. Live-host UAT plan

### 6.1 Target host

Primary: `wolf-i` (Linux, openclaw record already in failed-install state per #790 verification — perfect natural repro).
Fallback: `kevin` if `wolf-i` is unreachable or has been re-mediated since.

### 6.2 Baseline repro (pre-fix, captured from current `main`)

On the operator workstation:

```bash
clawctl host get                                            # confirm reachability
clawctl agent get                                            # confirm failed openclaw record on wolf-i
clawctl agent describe <openclaw-name>                       # capture status/installed_at/integrations
clawctl agent integration get --agent <openclaw-name>        # confirm brave is attached
clawctl agent sync <openclaw-name> 2>&1 | tee \
    .itx/810/evidence/wolf-i/00-baseline-repro.txt
# expected: "Error: sync failed: openclaw on '<host>' is 2026.6.8; brave plugin requires >= 2026.6.9"
```

If `wolf-i` has been mediated since, synthesize the state on `kevin`:

```bash
clawctl agent create test810 --type openclaw --host kevin --yes
# Once it installs successfully, manually edit ~/.config/clawrium/hosts.json
# to set status="failed", installed_at=null. Then attach brave:
clawctl integration registry get
clawctl integration attach brave-test --type brave --credential BRAVE_API_KEY=<key>
clawctl agent integration attach brave-test --agent test810
clawctl agent sync test810 2>&1 | tee \
    .itx/810/evidence/kevin/00-baseline-repro.txt
```

### 6.3 Post-fix UAT — happy path

Same sequence on same host after installing the worktree's fix:

```bash
uv tool install --reinstall --from . clawrium                # install the fix
clawctl agent sync <openclaw-name> 2>&1 | tee \
    .itx/810/evidence/<host>/01-postfix-sync-refused.txt
# expected: "Error: sync failed: agent '<name>' on '<host>' has an incomplete
#  installation (status='failed', installed_at=None); refusing to sync. Run
#  `clawctl agent install <name>` to complete the install first — your
#  attachments are preserved."

clawctl agent integration get --agent <openclaw-name> 2>&1 | tee \
    .itx/810/evidence/<host>/02-postfix-attachments-still-present.txt
# expected: brave still attached — no detach happened

clawctl agent install <openclaw-name> 2>&1 | tee \
    .itx/810/evidence/<host>/03-postfix-install-recovers.txt
# expected: install completes (or surfaces a real install error)

clawctl agent sync <openclaw-name> 2>&1 | tee \
    .itx/810/evidence/<host>/04-postfix-sync-green.txt
# expected: synced (drift=0)
```

### 6.4 Post-fix UAT — degenerate cases

- **D1 — operator detaches mid-recovery**: after `clawctl agent install` completes, detach brave (`clawctl agent integration detach brave-test --agent <name>`), `sync` should succeed and the rendered env should no longer include brave key.
- **D2 — version gap remains**: if openclaw upstream hasn't caught up, `clawctl agent install` may itself fail. The fix doesn't claim to repair upstream — verify that `sync` still refuses cleanly (same incomplete-install error) and operator can iterate (detach brave → install bare → reattach brave once upstream is current). Capture transcript at `.itx/810/evidence/<host>/05-postfix-degenerate-upstream-lag.txt`.
- **D3 — clean record regression check**: pick a different openclaw agent record on the same host that is `status=installed`. Run `clawctl agent sync` — must NOT be refused by the new guard; the existing brave version-gate behavior is unchanged. Capture transcript at `.itx/810/evidence/<host>/06-postfix-healthy-agent-still-works.txt`.

### 6.5 Definition of done for UAT

- Baseline repro transcript exists in `.itx/810/evidence/<host>/00-baseline-repro.txt` and shows the misleading "Run `clawctl agent upgrade`" hint.
- Post-fix transcripts 01–06 exist and show the new behavior.
- The repair-path (`install`) actually unblocks `sync` on the same host.
- No silent mutation of attachments observed.

## 7. atx review iteration plan

Run `/home/devashish/bin/atx review` after the fix is committed. Iterate fixing every `B#` blocker (or justify `Out-of-scope` with reasoning) until rating > 3/5. Record each round in the commit message per AGENTS.md `<commit-format-atx>`.

## 8. Out of scope

- Fixing the underlying upstream openclaw plugin install (#755 wired the install path; #810 is about lifecycle handling around a failed create).
- Auto-resuming the install from sync (would conflict with `clawctl agent install`'s own retry semantics in install.py:449).
- A new `clawctl agent repair` verb. The bug's "(a)" wording suggests routing to repair semantics — `clawctl agent install <name>` already serves that role per install.py logic.
- Touching `clawctl agent upgrade`'s strips-attachments class (`clawctl_upgrade_strips_attachments`) — that's its own issue (#707-adjacent).
- Anything macOS-specific. The guard is OS-agnostic and runs before any playbook dispatch.

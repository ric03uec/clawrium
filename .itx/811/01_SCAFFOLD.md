# Scaffold — Issue #811

Three short phases. Each one must hit its exit criteria before the
next begins.

## Phase A — Detection plumbing (paramiko probe + helper)

**Entry criteria**

- `.itx/811/00_PLAN.md` checked in.
- wolf-i baseline transcripts captured under
  `.itx/811/evidence/wolf-i/00-baseline-*.txt`.
- working tree clean on branch `issue-811`.

**Work**

1. Add `unit_path_for(os_family, agent_type, agent_name)` to
   `core/playbook_resolver.py` (or reuse `core/launchd.py:plist_path_for`
   for darwin and keep the `/etc/systemd/system/...` literal in one
   spot — a new helper in `playbook_resolver.py` keeps the
   dispatcher pattern). It returns the absolute path of the
   service-unit / plist artifact for the given OS.
2. Add `AgentInstallMissingError(CanonicalSyncError)` to
   `core/lifecycle_canonical.py`.
3. Add `_probe_host_install(client, *, agent_type, agent_name, host)`
   that runs a single `test -e <unit_path> && test -d <home>/.<type>`
   via paramiko `exec_command`. Returns a small dataclass with two
   booleans + the resolved paths. Pure function (no side effects).
   Open-coded sudo prefix matches the rest of the file (`sudo -n`
   because agent home dirs are 0700; the unit-file check does NOT
   need sudo for `test -e` on `/etc/systemd/system` but sudo is
   harmless and keeps the call symmetric).
4. Don't wire it into `sync_agent_canonical` yet — that's Phase B.

**Exit criteria**

- Helper has unit tests covering: unit + home present, unit missing,
  home missing, both missing, macOS path (plist).
- `make lint && make test` green.
- No call sites yet for the probe — it is dead code by design at the
  end of Phase A. We want to be able to land the helper without
  touching the live sync pipeline.

## Phase B — Wire probe into `sync_agent_canonical`

**Entry criteria**

- Phase A merged.
- Probe helper covered by unit tests.

**Work**

1. In `sync_agent_canonical` (just after `build_render_inputs` and
   before `_RENDERERS.get` is invoked), open a temporary paramiko
   client and call `_probe_host_install`. Emit
   `emit("validate", f"checking host install for {agent_name}")` so
   the CLI stream shows the new phase happening.
2. On probe failure raise `AgentInstallMissingError` with a message
   naming the missing artifact(s) and the repair command
   (`clawctl agent install <name>`). Close the SSH client before
   raising.
3. Keep this *before* the `workspace_only` branch. The probe must
   short-circuit a workspace-only sync too — pushing operator
   overlays onto an uninstalled agent is also a wedge.
4. Stub the probe in `_stub_sync_environment` so existing tests stay
   green (default = both present).

**Exit criteria**

- New tests:
  - probe-fails-on-unit → no render, no diff, no write.
  - probe-fails-on-home → same.
  - probe-passes → existing happy-path sync proceeds.
  - workspace-only-with-probe-fail → no overlay push, no bearer
    rotation (zeroclaw).
- All existing zeroclaw sync tests still green.
- `make lint && make test` green.

## Phase C — Health probe `INSTALL_MISSING`

**Entry criteria**

- Phase B merged.

**Work**

1. Add `ClawStatus.INSTALL_MISSING = "install_missing"` to
   `core/health.py:ClawStatus`.
2. In `check_claw_health`, after the `pgrep` check determines
   `process_running = False`, open a small follow-up ansible_runner
   shell command (or reuse the existing inventory) that runs the
   same `test -e <unit_path> && test -d <home>/.<type>` check.
3. When both fail, return `status=INSTALL_MISSING` with `error`
   string listing the missing artifacts. When at least one is
   present, fall through to the existing onboarding-state path.
4. Surface in the GUI status pill — if `gui/static/` has a status
   color map, add `install_missing → red`. Otherwise document that
   the frontend renders unknown statuses as a generic "warning"
   color and skip the change.

**Exit criteria**

- Test: `process_running=False` + unit + home missing →
  `INSTALL_MISSING`.
- Test: `process_running=False` + unit + home present → existing
  status (ONBOARDING / READY) preserved.
- `make lint && make test` green.

## Phase D — Real-host UAT + commit

**Entry criteria**

- Phases A–C merged on `issue-811`.
- `make lint && make test` green.

**Work**

1. UAT on wolf-i:
   - Run `clawctl agent sync clawrium-d01` — confirm new validate
     phase fails with actionable error before any render/diff/write
     touches the host. Capture transcript to
     `.itx/811/evidence/wolf-i/10-sync-after-fix.txt`.
2. UAT on kevin:
   - Pick or install a zeroclaw agent on kevin.
   - Remove the systemd unit on the host:
     `sudo rm /etc/systemd/system/zeroclaw-<name>.service && sudo systemctl daemon-reload`.
   - `clawctl agent sync <name>` → expect new fast-fail. Capture
     transcript.
   - Restore the unit; remove `~/.zeroclaw` instead. Run sync.
     Capture transcript.
3. UAT happy-path regression: pick any healthy agent
   (e.g. `clawrium-triage`), run sync, capture transcript proving
   the new probe is a no-op when things are healthy.
4. UAT macOS coverage (optional): if `hermes-mac` on `mac-test` is
   reachable, run a sync against it. If not, document that macOS
   coverage rides on unit tests only and re-flag for follow-up.
5. ATX CLI review iterations until rating > 3/5 and no blockers.
6. Update `CHANGELOG.md` under `### Fixed`.
7. Commit locally on `issue-811` with the ATX summary in the
   message. **DO NOT push, DO NOT open PR.**

**Exit criteria**

- All UAT transcripts under `.itx/811/evidence/`.
- ATX rating > 3/5 with all blockers fixed or justified.
- Local commit on `issue-811`, working tree clean.

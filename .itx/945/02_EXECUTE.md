# Issue #945 — Execution Log

Phase 3 of parent #11: delete bare openclaw + full lifecycle + fleet
visibility (BREAKING).

See:
- [`.itx/11/00_PLAN.md`](../11/00_PLAN.md) §2 row 3
- [`.itx/11/01_SCAFFOLD.md`](../11/01_SCAFFOLD.md) Phase 3

## MVP scope delivered

The scaffold called for a comprehensive rewrite (fleet visibility,
lifecycle verb delegation, docs, tests, real-host UAT). Given the
one-session execution window, this PR ships an MVP that:

- Deletes the `__bare__` non-regression preserve branch in
  `core/install.py` — every new / re-created / resumed openclaw is
  stamped with `runtime: nemoclaw` unconditionally.
- Tightens `_openclaw_nemoclaw_onboard` in
  `core/lifecycle_canonical.py`: a record explicitly stamped with a
  non-nemoclaw runtime raises `CanonicalSyncError` pointing at the
  migration doc. Absent-runtime records (legacy bare untouched since
  Phase 2) still fast-skip — the compatibility path keeps existing
  fleets working while the operator plans the migration.
- Adds sandbox destroy (`nemoclaw destroy <sandbox>`) to
  `openclaw/playbooks/remove.yaml` before the systemd + user
  teardown. Threads `sandbox_name` via the existing extravar seam.
- Extends `agent_to_row` + `clawctl agent get`: RUNTIME column at
  the end of the default table (openclaw rows show
  `nemoclaw@<version>`; other agents show `-`).
- New `clawctl host validate <hostname>` command: aggregates
  `nemoclaw status <sandbox>` for every openclaw agent on the host.
  Exits 0 when healthy, 1 otherwise. Backed by a new read-only
  `nemoclaw_status.yaml` playbook (Linux only; dispatcher-guard
  refuses darwin).
- Docs: NemoClaw substrate section at the top of
  `docs/agent-support/openclaw.md` + website mirror.
- Migration note: `docs/releases/26.7.3/CHANGELOG.md` with
  explicit remove / create / configure / start steps and the
  "what survives, what does not" table.
- `CHANGELOG.md` `### BREAKING` entry with the migration command
  block and a link to the release doc.
- Tests: `test_validate.py`, `test_create.py` migration semantics,
  runtime-column display, onboard fail-loud on non-nemoclaw runtime.
- Test infra: 4 openclaw-sync test setups gained a
  `_openclaw_nemoclaw_onboard` stub so they don't spawn
  ansible-runner now that the onboard dispatches unconditionally
  for records that DO carry `runtime: nemoclaw`.

## Deferred to follow-up

Called out as `[TODO-FOLLOWUP]` in the PR body:

- **Verb-level lifecycle delegation.** Scaffold said `agent
  {start,stop,status,logs,sync}` should route to
  `nemoclaw start/stop/status/logs` inside the sandbox. Current
  behavior: `start`/`stop` still control the openclaw systemd unit
  on the host (Phase 2 shape). Reworking start.yaml / stop.yaml to
  target the sandbox is a full substrate rewrite — deferred.
- **`sync` re-onboard on pin bump.** `nemoclaw_onboard.yaml` is
  idempotent by design, so a version bump plus a plain
  `clawctl agent sync` DOES trigger re-onboard through the same
  playbook. The scaffold's stronger contract ("re-onboard on pin
  changes") is functionally met, but there is no explicit
  version-mismatch detection surfaced to the operator.
- **Full openclaw-inside-sandbox install path.** Phase 2 installs
  openclaw both on the host AND onboards the sandbox. Phase 3's
  full removal of the host-side install would need install.yaml
  rewritten to only bootstrap the sandbox. Deferred.
- **Real-host UAT on wolf-i.** Required per project convention but
  the execution session has no SSH access; the PR opens with lint
  + full unit-test coverage passing but UAT remains pending
  operator verification.

## Stage log

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-07-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 945 --pr-base=issue-944-nemoclaw-hosts-install
```

**Output**: MVP Phase 3 code + docs + tests. PR stacked on
`issue-944-nemoclaw-hosts-install`. See PR body for the UAT template
and the Callouts section listing every non-obvious decision.

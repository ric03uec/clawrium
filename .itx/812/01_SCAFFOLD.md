# Execution Scaffold — Issue #812

## Phase 1 — Add gateway probe to Linux `_verify_health`

**Entry**: `_verify_health` on Linux runs `systemctl is-active` and returns
on success; no port probe.

**Work**:
1. Add helper `_verify_gateway_listening_linux(client, *, agent_name,
   gateway_port, timeout)` in `src/clawrium/core/lifecycle_canonical.py`,
   modeled on `verify_health_macos`.
2. After the existing `is-active` block in `_verify_health`, call the
   helper iff `gateway_port is not None`.

**Exit**: The Linux path of `_verify_health` raises `CanonicalSyncError`
when the gateway port is not accepting connections within `timeout`
seconds of the unit reporting active, with a message naming the port
and the agent.

## Phase 2 — Unit tests

**Entry**: Existing `TestVerifyHealthDiagnosticWrap` cases still pass.

**Work**: Add `TestVerifyHealthLinuxGatewayProbe` cases per plan:
- happy first-poll
- delayed-success (third poll)
- timeout
- bash-missing diagnostic
- gateway_port=None backwards-compat
- invalid port (parametrized)

**Exit**: `pytest tests/core/test_lifecycle_canonical.py -q` green.

## Phase 3 — Local verify

**Entry**: Code + tests written.

**Work**: `make lint && make test`.

**Exit**: Both green.

## Phase 4 — Real-host UAT

**Entry**: Local verify green.

**Work**: Execute the UAT matrix in `00_PLAN.md`; capture transcripts
under `.itx/812/evidence/<host>/`.

**Exit**: Induced-repro on wolf-i fails sync with the new error;
healthy-host syncs (wolf-i restored, esper-mac-oc) succeed.

## Phase 5 — atx review

**Entry**: UAT clean.

**Work**: `/home/devashish/bin/atx review` iterations until rating > 3/5
with all blockers fixed or justified.

**Exit**: Final review meets the bar; commit message records each round.

## Phase 6 — Commit locally

**Entry**: Review passed.

**Work**: Single commit on `issue-812` with the ATX-format message. No
push. No PR.

**Exit**: `git log` shows the commit; `git status` clean.

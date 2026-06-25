# Scaffold — Issue #810

## Phase A — Implement the guard
**Entry**: plan reviewed, working tree clean on `issue-810`.
**Exit**:
- New install-state precondition added inside `src/clawrium/core/lifecycle_canonical.py:sync_agent_canonical` right after `get_agent_by_name(...)`.
- Raises `CanonicalSyncError` with the message shape from plan §4.1.
- No other production-code edits.

## Phase B — Unit tests
**Entry**: Phase A code in place.
**Exit**:
- New `TestSyncRefusesIncompleteInstall` class in `tests/core/test_lifecycle_canonical.py` with five cases (§4.2 of plan).
- All existing tests in the file still pass without modification.
- `make lint && make test` is green locally.

## Phase C — Live-host baseline repro
**Entry**: Phases A+B complete and committed (or at least staged).
**Exit**:
- `.itx/810/evidence/<host>/00-baseline-repro.txt` captured against `current main` behavior (the bug as documented in issue #810).
- Note: if the natural `wolf-i` state still reproduces, use that. Otherwise synthesize on `kevin` per plan §6.2.

## Phase D — Live-host post-fix UAT
**Entry**: Phases A+B complete; fix loaded into operator's local `clawctl`.
**Exit**:
- `.itx/810/evidence/<host>/01-postfix-sync-refused.txt` — new error message, exit 1.
- `.itx/810/evidence/<host>/02-postfix-attachments-still-present.txt` — brave still attached.
- `.itx/810/evidence/<host>/03-postfix-install-recovers.txt` — `clawctl agent install` unblocks (or surfaces a real install error).
- `.itx/810/evidence/<host>/04-postfix-sync-green.txt` — `clawctl agent sync` succeeds.
- `.itx/810/evidence/<host>/05-postfix-degenerate-upstream-lag.txt` — degenerate D2 covered.
- `.itx/810/evidence/<host>/06-postfix-healthy-agent-still-works.txt` — regression check on a clean record.

## Phase E — atx review
**Entry**: Phases A–D done, code+evidence committed locally.
**Exit**:
- atx CLI review run via `/home/devashish/bin/atx review`.
- Each round captured; iterate until rating > 3/5 with no unresolved blockers (or justified Out-of-scope).
- Commit message updated per AGENTS.md `<commit-format-atx>` template.

## Phase F — Commit (local only)
**Entry**: Phases A–E done; lint+test green; UAT transcripts in evidence dir.
**Exit**:
- `git commit` on branch `issue-810` with the ATX-format message body.
- No push, no PR. Hand off to operator.

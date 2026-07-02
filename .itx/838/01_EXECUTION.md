# Issue #838 — Phase 5 Execution Log

Phase 5 (final) of the #499 orchestrated chain: delete the placeholder
`clawctl mcp` group.

## Scope

1. Delete `src/clawrium/cli/clawctl/mcp.py`.
2. Remove `mcp_app` import + `add_typer(mcp_app, name="mcp")` from
   `src/clawrium/cli/__init__.py`.
3. Delete `tests/cli/clawctl/mcp/test_placeholder.py` and its
   package directory.
4. Update `tests/cli/test_app.py` and `tests/cli/test_non_interactive.py`
   to reflect the removal — `clawctl mcp` now exits 2 with
   `No such command 'mcp'`.
5. New test `tests/cli/clawctl/test_mcp_removed.py` covering the
   top-level, `registry get`, and `registry describe` unknown-command
   cases; negative assertions guard against a partial revert
   re-registering the stub at exit 2.
6. Remove `clawctl mcp` sections from `.claude/skills/clawctl/SKILL.md`
   and `.opencode/skills/clawctl/SKILL.md`.
7. CHANGELOG.md `[Unreleased] ### BREAKING`: rewrite the exit-code
   flip entry as a **removal** entry; migration path =
   `clawctl integration registry create --type slack-user|slack-cookie`;
   references successor issue **#844**.

## Decision — `_stub.py` retained

The scaffold said: "If `mcp` was the only remaining stub group, prune
`_stub.py` entirely; otherwise leave in place." `_stub.py` is still
imported by `agent/edit.py`, `agent/logs.py`, and `agent/chat.py` — so
it stays.

## Successor issue

`#844` — "Generic MCP-server support (arbitrary MCP servers, not just
Slack)". Referenced in CHANGELOG and in `test_mcp_removed.py`.

## ATX review (CLI transport, iteration ceiling 3)

State persisted in `.itx/838/atx-session.json`.

| Iter | Rating | Blocking | Warnings | Notes |
|------|--------|----------|----------|-------|
| 1    | 3/5    | false    | W1–W4    | Skill docs stale (W1/W2); missing negative assertions (W3); no exclusion check (W4); +3 suggestions |
| 2    | 4/5    | false    | none     | W1–W4 + S1 addressed; S2/S3 skipped as nice-to-have / pre-existing |

Cleared: rating > 3/5, no blockers. Below the 3-iteration ceiling.

## Prompt Log

## Execute Phase 5 — #838

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-07-01T22:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 838 --pr-base=issue-837-slack-docs.

This is Phase 5 (final) of the #499 orchestrated chain. Your PR MUST
target issue-837-slack-docs (not main). Include "Stacked on top of
issue-837-slack-docs" in the PR body.

Phase 5 scope per the execution scaffold (`.itx/499/01_EXECUTION.md`):
1. Delete `src/clawrium/cli/clawctl/mcp.py` and its `mcp_app` wiring
   in the parent Typer surface.
2. Delete `tests/cli/clawctl/mcp/test_placeholder.py`.
3. If `mcp` was the only remaining stub group, prune `_stub.py`
   entirely; otherwise leave in place.
4. Test that `clawctl mcp` returns Typer's default unknown-command
   message (exit 2), NOT stub's exit-1.
5. Open a NEW GitHub issue as the successor: "Generic MCP-server
   support (arbitrary MCP servers, not just Slack)". Reference the
   successor issue number in the CHANGELOG.
6. CHANGELOG.md `[Unreleased] ### BREAKING`: document `clawctl mcp`
   removal with migration = `clawctl integration registry create
   --type slack-user|slack-cookie` and successor issue reference.

Review-tool override: use the atx CLI (`atx review request --prompt "..."`)
for code review iterations. Do NOT use mcp__atx__request_review.
Persist review state in .itx/838/atx-session.json with
transport: cli. If atx CLI fails, skip and record a Callout — never
block on ATX. Iteration ceiling 3.

Branch is issue-838-delete-mcp-stub (already checked out). Do not
create a new branch.

CRITICAL: This is orchestrate mode. NEVER call AskUserQuestion or
block on user input. Make best-guess decisions using project
standards (CLAUDE.md, AGENTS.md, memory) and record them as
[DECISION] / [UNRESOLVED] Callouts on the PR. The PR is the sync
point with the user, not mid-execution prompts.

No real-host UAT — CLI removal only; rejection path already covered
by Phase 1's attach-gate tests per the scaffold.
```

**Output**: `clawctl mcp` group deleted; skill docs, tests, and
CHANGELOG updated; successor issue #844 opened; ATX cleared at 4/5
on iteration 2.

# Issue #435 — User can use clawctl with kubectl-style UX across the fleet

GitHub: https://github.com/ric03uec/clawrium/issues/435

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-20T03:40:46Z
**Model**: claude-opus-4-7

```prompt
change the cli from clm to clawctl and align the cli output format with kubectl format. make sure all the commands can be run using cli only and the gui wiring is using the same commaands. this issue is about doing a sweep of the cli surface and stnandardizing it across the board for a cleaner ux
```

**Output**: Created GitHub issue #435 covering (1) rename `clm` → `clawctl`, (2) kubectl-style verb-noun grammar + `-o yaml|json|wide` output, and (3) wiring the GUI through `clawctl` so CLI is the single source of truth.

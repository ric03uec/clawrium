# Execute — Issue #811

## Execute

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-06-24T17:30:00Z
**Model**: claude-opus-4-7

```prompt
Read .itx/811/00_TASK.md — that is your full end-to-end brief for GitHub issue #811. Execute everything in it, in order, autonomously. Use TaskCreate to track phases. Begin now.
```

**Output**: Implementation landed across `src/clawrium/core/{lifecycle_canonical,health,playbook_resolver}.py` (new probe + AgentInstallMissingError + ClawStatus.INSTALL_MISSING) with paired test coverage and real-host UAT transcripts under `.itx/811/evidence/`.

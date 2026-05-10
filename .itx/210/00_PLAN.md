# Issue #210 — Implementation Plan

User can configure basic memory for openclaw agents.

Source of truth: GitHub issue #210, including the implementation plan and
plan-reconciliation comments.

## Phasing strategy

The five phases below ship as **independent PRs** to keep reviews small.
Each PR closes only the phase milestone; the issue stays open until Phase 5.

| Phase | Branch | PR closes |
|-------|--------|-----------|
| 1 | `issue-210-phase-1-memory-core` | core memory module + ansible playbooks + tests |
| 2 | `issue-210-phase-2-cli` | `clm agent <name> memory show\|delete` |
| 3 | `issue-210-phase-3-tui-display` | TUI MEMORY card with size and paths |
| 4 | `issue-210-phase-4-tui-edit` | TUI edit → sync → restart flow |
| 5 | `issue-210-phase-5-docs` | docs + README updates |

Compaction/truncation (acceptance criteria items 6 and 7) is explicitly
deferred to a follow-up issue per the plan-reconciliation comment.

## Workspace layout assumed by all phases

`/home/<agent_name>/.openclaw/workspace/` contains:

- `SOUL.md` — agent personality
- `IDENTITY.md` — agent identity
- `USER.md` — user context
- `TOOLS.md` — available tools
- `memory/` — daily files (`YYYY-MM-DD.md`)

## Phase 1 scope (this PR)

**New files**

- `src/clawrium/platform/registry/openclaw/playbooks/memory_info.yaml`
- `src/clawrium/platform/registry/openclaw/playbooks/memory_read.yaml`
- `src/clawrium/platform/registry/openclaw/playbooks/memory_write.yaml`
- `src/clawrium/platform/registry/openclaw/playbooks/memory_delete.yaml`
- `src/clawrium/core/memory.py`
- `tests/test_core_memory.py`

**Modified**

- `tests/conftest.py` — mock workspace fixture (Gap #5)

**Public API**

```python
def get_memory_info(hostname: str, agent_name: str) -> MemoryStats | None
def read_memory_file(hostname: str, agent_name: str, filename: str) -> str | None
def write_memory_file(hostname: str, agent_name: str, filename: str, content: str) -> tuple[bool, str | None]
def delete_memory_files(hostname: str, agent_name: str, files: list[str]) -> tuple[bool, str | None]
```

**Gaps addressed in Phase 1**

- Gap #1 (offline graceful failure): functions catch ansible-runner failures
  and return `None` / `(False, error)` rather than raising.
- Gap #2 (file ownership on writes): `memory_write` and `memory_delete`
  playbooks set `owner`/`group` to `{{ agent_name }}` and run with `become`.
- Gap #5 (mock workspace fixture): added to `tests/conftest.py`.

Gaps #3, #4, #6 are surfaced in later phases (TUI / CLI safety prompts).

## Acceptance for this PR

- [ ] `make test` green
- [ ] `make lint` green
- [ ] ATX review > 3/5 with no blocking issues
- [ ] PR opened against `main`

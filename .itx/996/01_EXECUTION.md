## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T05:16:00Z
**Model**: gpt-5.6-terra

```prompt
Implement issue #996: type-aware no-daemon lifecycle semantics for the installed CLI agent type `claude`. Defer Claude settings schema/rendering to #997. Validate, ATX-review, commit/push, and open a stacked PR against `issue-995-claude-install-boundary`.
```

**Output**: Added Claude's type-aware no-daemon lifecycle handling, completed-install gating, focused tests, and ATX review record.

### Scope decisions

- Claude remains visible in create/get/list/fleet/detail/remove flows, but has no daemon, service manager, process probe, gateway, port, tunnel, or web UI.
- `start`, `stop`, `restart`, and `logs` report that the installed CLI has no applicable daemon operation. `configure` and `sync` are no-ops only after the install is complete; settings rendering remains deferred to #997.
- Removal keeps the generic remote-first flow and resolves Claude's Linux or macOS remove playbook from the host OS.

### Validation

- Focused tests: `163 passed`.
- `make test`: `4899 passed, 2 skipped`; GUI: `366 passed`.
- `make lint`: passed (Ruff and Next.js ESLint).

### ATX review iterations

1. **2/5** — added direct CLI/core no-side-effect and health tests; guarded incomplete installations from appearing READY.
2. **2/5** — rejected sync/configure no-op success for failed, installing, or timestamp-less installation records.
3. **5/5** — no blockers, warnings, or actionable suggestions. Review IDs: `d3ea87a0-3ac2-4abb-b6ac-44ece7c7951b`, `e2e575cb-48fe-496e-8b88-a00fa17bdf93`, `cb4e9135-dcd4-484a-84e9-387f115734ab`.

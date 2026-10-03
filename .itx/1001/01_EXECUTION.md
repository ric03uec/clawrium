# Issue #1001 — Execution Record

## Scope completed

- Added the canonical Claude Code support contract and website page, linked it from both support matrices and the website sidebar, and updated the installation guide + required website mirror.
- Clarified the README and website CLI reference: `claude` is install-only, uses the finite `agent shell` command path, and does not provide a daemon, native `exec`, chat, UI, port, tunnel, or pairing surface.
- Updated CLI help and the Claude-specific `agent exec` error to distinguish the supported shell path from unavailable operations, with CliRunner regression coverage that verifies help text, the explicit exit-2 diagnostic, and that native exec is never reached.
- Added the required `CHANGELOG.md` documentation entry.

## Validation

- `make test` — passed: 4,994 Python tests, 2 skipped; 366 GUI tests.
- `make lint` — passed: Ruff and Next.js ESLint.
- `npm --prefix website run build` — passed.
- Verified the `docs/installation.md` body exactly matches the website installation mirror below its frontmatter/comment.

## ATX review

- Review 1 — rating 3/5, cost $0.2411688, 97,894 ms. Added concrete main/create/exec/shell help assertions, proved the Claude exec type gate does not reach native execution, and clarified `exec` as unavailable rather than an implicit shell fallback. The remaining credential-safety concern was covered by inherited #1003 regression tests; this issue changes no credential implementation.
- Review 2 — rating 4/5, cost $0.2495716, 112,474 ms. The rendered review reported no blockers. It confirmed the install-only CLI wording, documentation mirroring/navigation, and finite-shell guidance. Session metadata is retained in `atx-session.json`.

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T10:14:00Z
**Model**: gpt-5.6-terra

```prompt
Execute only GitHub issue #1001: document the shipped install-only `claude` agent contract and clarify required CLI help/errors. Update mirrored installation/docs sources and `CHANGELOG.md`; run tests/lint, obtain stateless ATX review, record execution artifacts, commit/push, and open a stacked PR based on `issue-1003-claude-provider-e2e`.
```

**Output**: Documented the Claude Code install-only contract, clarified help/error surfaces, validated the change, and recorded ATX review history for the stacked PR.

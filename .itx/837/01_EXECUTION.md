# Issue #837 — Phase 4: Docs + changelog for Slack integration

Parent: #499. Stacked on Phase 3 (#836 → `issue-836-zeroclaw-slack`).

## Execution scope

Docs-only phase. No code changes. Files touched:

| Path | Change |
|------|--------|
| `docs/agent-support/integrations/slack.md` | **NEW** — unified Slack integration doc (token acquisition, tool list, per-agent-type wiring, SHA256 pin table, composite blast-radius warning, `--credential-stdin` recommendation) |
| `docs/agent-support/integrations/index.md` | Added Slack row to the integrations table |
| `docs/agent-support/hermes.md` | Updated MCP feature-table row + added Slack integration subsection |
| `docs/agent-support/openclaw.md` | Added Slack row to Integration Support + Slack integration subsection |
| `docs/agent-support/zeroclaw.md` | Added Slack row to Feature Support + Slack integration subsection + armv7l follow-up note |
| `CHANGELOG.md` | Appended `### Documentation` entry under `[Unreleased]` |

## Decisions

- **File location.** The Phase 4 plan (`.itx/499/00_PLAN.md`) and the issue body both cite `docs/integrations/slack.md`, but the repo lays integrations under `docs/agent-support/integrations/` (see `atlassian.md`, `brave.md`, `github.md`, etc.). Followed the actual project convention. All `../integrations/slack.md` cross-links in the three agent-support docs match this location. Recorded as `[DECISION]` on the PR.
- **Website mirror.** The AGENTS.md "source of truth" section documents mirror rules for `docs/installation.md` → `website/docs/installation.md` and `docs/host-preparation.md` → `website/docs/guides/host-setup.md`. There is no documented mirror for `docs/agent-support/integrations/` — spot-checked `website/docs/` for existing Atlassian / GitHub mirrors and found none. No mirror work performed. If a mirror expectation exists for this path, it is a follow-up (recorded as `[UNRESOLVED]` on the PR).

## ATX review

- **Transport:** CLI (`atx review request`) per skill override.
- **Iteration 1** — Rating **3.5/5**. Full review captured; 4 warnings + 3 suggestions. All fixed:
  - Binary install path standardized to `/home/<agent-name>/…` (Linux) / `/Users/<agent-name>/…` (macOS) throughout — the earlier `~/<agent-name>/…` notation was ambiguous.
  - ZeroClaw TOML example updated to `name = "slack-my_slack"` with a note documenting the template's hardcoded `slack-` prefix (hermes/openclaw do not add it).
  - Binary asset column corrected: playbooks download **bare binaries** (`slack-mcp-server-linux-amd64`, etc.), not tarballs. SHA256 pins are of the raw binaries.
  - Cookie extraction description defers to upstream README instead of claiming a specific DevTools location.
  - Anti-abuse language reframed as observational ("community reports show", "treat as observable behaviour, not documented policy") instead of attributing specific internal Slack pipeline behavior.
  - Unverifiable "same code path clawctl exercises in CI" clause removed from the stdin section.
- **Iteration 2** — **FAILED (rate limit)**. The upstream Claude API returned "You've hit your limit · resets 8:40pm (America/Los_Angeles)" during iter-2. Per skill contract (`atx CLI fails → skip and record a Callout — never block on ATX`), skipped and recorded as `[ENVIRONMENT]` on the PR.

Session state persisted at `.itx/837/atx-session.json`.

## Verification

- `make lint` — ✅ passes (Python + GUI)
- `make test` — ✅ 4285 passed, 2 skipped (Python) + 305 tests (GUI)
- Real-host UAT — not applicable per Phase 4 exit criteria (docs-only)

## Prompt Log

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-07-01T19:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 837 --pr-base=issue-836-zeroclaw-slack.

This is Phase 4 (docs) of the #499 orchestrated chain. Your PR MUST target
issue-836-zeroclaw-slack (not main). Include "Stacked on top of
issue-836-zeroclaw-slack" in the PR body.

Docs-only phase per the plan — no code changes. Files to create/update per
the execution scaffold:
- docs/integrations/slack.md (new)
- docs/agent-support/hermes.md — Slack subsection
- docs/agent-support/openclaw.md — Slack subsection
- docs/agent-support/zeroclaw.md — Slack subsection
- CHANGELOG.md under [Unreleased] ### Documentation

Review-tool override: use the atx CLI (`atx review request --prompt "..."`)
for code review iterations. Do NOT use mcp__atx__request_review. Persist
review state in .itx/837/atx-session.json with transport: cli. If atx CLI
fails, skip and record a Callout — never block on ATX. Iteration ceiling 3.

Branch is issue-837-slack-docs (already checked out). Do not create a new
branch.

CRITICAL: This is orchestrate mode. NEVER call AskUserQuestion or block on
user input. Make best-guess decisions using project standards (CLAUDE.md,
AGENTS.md, memory) and record them as [DECISION] or [UNRESOLVED] Callouts
on the PR. The PR is the sync point with the user, not mid-execution prompts.

No real-host UAT — docs-only phase per the execution scaffold's Phase 4
exit criteria.
```

**Output**: Docs + CHANGELOG landed under `docs/agent-support/integrations/`
(per project convention, not the `docs/integrations/` path cited in the
issue — captured as a `[DECISION]` on the PR). ATX iter-1 (3.5/5) findings
all applied; iter-2 hit a Claude API rate limit and was skipped per skill
contract.

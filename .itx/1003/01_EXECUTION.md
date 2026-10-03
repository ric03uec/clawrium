## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T09:32:17Z
**Model**: gpt-5.6-terra

```prompt
Execute only GitHub issue #1003 in this worktree. You are a Pi worker in a sequential stacked-PR pipeline. Read AGENTS.md, issue #1003, parent #989, `.itx/989/00_PLAN.md`, `.itx/989/01_SCAFFOLD.md`, and inherited changes. Create and maintain a task checklist before edits.

Scope: isolated i-wolf provider E2E validation for the completed Claude agent slices. Use two fresh, independent agents: one OAuth case and one API-key case; do not collapse them into a credential-switch test. Preserve existing agents. Assert install-only behavior does not invoke Claude, start a service, create a gateway/port/UI, or mutate credentials. For API key use only a dummy test value and prove it reaches only the intended remote environment variable with the opposite variable absent; do NOT perform a real authenticated API invocation because the user will inject a real key later. For OAuth, use local OAuth only if it is available via an explicit supported local source; otherwise clearly record an environment Callout/blocker and preserve the rest of the pipeline. Never copy a keychain/database/browser profile/local `~/.claude`, print secret values, or weaken redaction. Each E2E must validate cleanup after removal: agent account/home/prefix/full `.claude`/credential file/hook/local instance secrets/hosts record removed, while pre-existing agents survive. Scope may add safe test harness/scripts and test evidence, but no broad provider/settings/command-path/docs changes.

Out of scope: docs/help (#1001), general source redesign, real API auth validation, additional shell/exec/chat/gateway/UI features. Do not ask user questions and do not merge.

Run appropriate focused tests plus `make test` and `make lint`. Request stateless ATX CLI review against this branch/worktree using `atx review request --worktree <worktree-name> --prompt "Review the full diff against issue-1002-claude-verification-removal" --format json --timeout 15m`; address blockers for at most 3 iterations and persist `.itx/1003/atx-session.json`. Write `.itx/1003/01_EXECUTION.md` with the required execution prompt log. Commit, push, and open one PR based on `issue-1002-claude-verification-removal`, not main. PR must say `Stacked on top of issue-1002-claude-verification-removal`, include the AGENTS ATX review format and `## Callouts`, explicitly document whether OAuth E2E was available and the deliberate deferral of real API auth. Handoff is the open PR.
```

**Output**: Added a redaction-safe i-wolf E2E harness and evidence. `claude-oauth-e2e` completed install-only and cleanup assertions but OAuth activation is environment-blocked because the only supported explicit source (`CLAUDE_CODE_OAUTH_TOKEN`) was absent; no local `~/.claude` was read. After OAuth cleanup, independent `claude-api-key-e2e` used a generated dummy value, confirmed exclusive API-key environment activation without an authenticated invocation, and completed cleanup. The E2E exposed a first-install skipped-slurp guard defect in both install runbooks; the minimal guard fix is covered by focused tests and was required for either fresh E2E install to proceed.

## Execution Scope Check

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T09:32:17Z
**Model**: gpt-5.6-terra

```prompt
Scope check: the E2E harness must not carry unrelated installer behavior fixes. The `install.yaml` and `install_macos.yaml` changes currently shown are out of #1003 unless strictly required to make the E2E installation path work and accompanied by a focused regression test. If not strictly necessary, revert only those self-authored playbook changes and record the discovered defect as a Callout. Keep the E2E harness/evidence and tests narrowly scoped; do not touch prior phase behavior opportunistically.
```

**Output**: Retained only the strict first-install blocker fix: a skipped Ansible `slurp` registers no `content`, so both fresh provider E2Es failed before package installation. The Linux and macOS runbooks now guard `content` behind the metadata-exists fact; `test_claude_package_metadata_match_handles_skipped_slurp` pins that requirement for both. No other inherited behavior was changed.

## Verification

- Focused Claude suite: `207 passed`.
- Install-boundary regression: `11 passed`.
- Full suite: `4993 passed, 2 skipped`.
- GUI suite: `366 passed`.
- `make lint`: Python Ruff and GUI ESLint passed.

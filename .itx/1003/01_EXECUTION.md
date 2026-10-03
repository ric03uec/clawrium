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

## Follow-up OAuth Propagation Validation

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-03T15:55:06Z
**Model**: gpt-5.6-terra

```prompt
Follow-up validation requested by the user: they confirm local Claude OAuth credentials are working and want the real-host OAuth propagation test rerun now. In this existing #1003 worktree/PR context, do not redesign implementation. Safely rerun the OAuth-only i-wolf E2E using only the supported local OAuth credential source. Never print, copy, or inspect credential bytes; never scrape/copy local `~/.claude`, keychain, browser profile, or database. Verify: a fresh `claude-oauth-e2e` receives only `CLAUDE_CODE_OAUTH_TOKEN`, the API key variable is absent, no secret leaks to state/output/evidence, and removal cleans all owned residue while preserving existing agents. If current code has no supported safe way to read the working local credential, state the precise technical blocker rather than weakening the boundary. Update the committed E2E evidence and PR #1011 / issue #1003 comment with the factual result; commit and push only those evidence/log changes if appropriate. Do not merge and do not run a real Claude chat/API invocation unless the current #1003 acceptance contract explicitly requires it.
```

**Output**: The worker process lacks the only supported source, an explicitly exported `CLAUDE_CODE_OAUTH_TOKEN`. `import_claude_oauth_from_environment` intentionally cannot read a local Claude session or any file/keychain/browser/database source, so the real-host OAuth propagation rerun was safely blocked before agent creation. The previously cleaned `claude-oauth-e2e` identity remains absent; no credential bytes, remote credential file, or Claude/API invocation occurred.

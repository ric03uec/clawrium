# Issue #334 — Execution Log

**Slice 5 of parent #322** — aichat investigation note (docs-only, non-user-facing).

This issue has no standalone `00_PLAN.md`; the plan lives in `.itx/322/00_PLAN.md` under "Slice 5 — aichat investigation note" (line 191).

## Entry criteria

- Per `.itx/322/00_PLAN.md` line 204: "Slice 5 can land at any time." Independent of Slices 1–4 — the doc describes target design, not extant code. No upstream dependency.

## Scope

Single new file under `docs/research/` plus a discoverability entry in `docs/index.md`.

**Scope expansion during execution**: added `docs/index.md` "Design Decisions" entry (originally not in issue scope; required for discoverability per ATX Round 1 W7) and two `systemctl` corrections in `.itx/322/00_PLAN.md:67,183` (factual bug surfaced by ATX Round 2 W-R2-4 — keeps the parent plan accurate for Slice 4 implementers). Both are local, no upstream dependency.

## Exit criteria

- [x] `docs/research/aichat.md` exists with four sections (what aichat is, three options considered, why ref-impl for v1, patterns worth stealing).
- [x] Linked from `docs/index.md` under a new "Design Decisions" section.
- [x] Discoverable from parent #322 via the PR comment posted after merge (see Follow-ups).
- [x] `make lint` clean.
- [x] `make test` clean (no regressions; docs-only).
- [x] ATX automated review iterated to Rating > 3/5 with all blocking issues resolved.

## Notes

- Docs-only change. No source code touched. No tests added (no behavior to test).
- The doc explicitly flags its own status: "Slices 1–4 are unbuilt at the time this lands; symbols described (`ChatBackend`, `HermesOpenAIBackend`, `httpx`, `features.chat.type`, `test_sse_edge_cases`) are *target design*, not present code."
- Project board status update skipped — local `gh` token lacks `project` scope. Non-blocking.

## Follow-ups (after merge)

- Comment on #322 linking the merged doc: *"Slice 5 complete. aichat investigation note: `docs/research/aichat.md` (PR #335)."*

## Prompt Log

<details>
<summary>Execution</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-11T15:05:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 334
```

</details>

<details>
<summary>ATX Review (manual CLI, Round 1)</summary>

**Tool**: `atx review request --prompt "..."` (MCP unavailable in session; used CLI fallback)
**Timestamp**: 2026-05-11T15:19:06Z
**Rating**: 2/5
**Blockers**: 2 (B1 `test_sse_edge_cases` doesn't exist; B2 `httpx` not in dep tree) — both tense errors
**Cost**: $2.6784
**Agents**: leader, core-lifecycle, cli-ux, security-secrets, test-coverage, ansible-playbook

Fixes applied:

| # | Status | Resolution |
|---|--------|-----------|
| B1 | Fixed | Switched to future tense; corrected path to `tests/test_chat_hermes.py::test_sse_edge_cases (Slice 3)`. |
| B2 | Fixed | Rewrote to say Slice 1 will add `httpx>=0.27`. |
| W1 | Clarified | Kept `HERMES_API_SERVER_KEY` (correct in clm's `secrets.json` per `install.py:535`) and explicitly noted it's rendered into hermes' `.env` as `API_SERVER_KEY`. |
| W2 | Fixed | `systemctl status hermes-<agent-name>` (no `--user`, full unit name; system unit at `/etc/systemd/system/`). |
| W3 | Fixed | Model selection corrected to `config.provider.default_model` (rendered by `templates/config.yaml.j2:8`); `features.chat.type` clarified as discriminator only. |
| W4 | Fixed | Added top-of-doc status callout; future-tense audit of `ChatBackend`, `HermesOpenAIBackend`, `_build_hermes_base_url`. |
| W5 | Fixed | Added injection-safety bullet to "When to reconsider sidecar" referencing PR #68 incident. |
| W6 | Fixed | Added explicit "LAN transport is plaintext HTTP" bullet noting the deliberate trade and hermes' own strong-key enforcement. |
| W7 | Fixed | Added "Design Decisions" section to `docs/index.md` linking the new doc. |
| W8 | Fixed | Added "Secret exposure" Con to sidecar option (`ps aux` / `/proc` bearer leakage). |
| W9 | Fixed | Added "Subprocess lifecycle" Con to sidecar option (PTY + SIGINT forwarding). |
| W10 | Acknowledged | "Linked from #322" satisfied via follow-up comment after merge (recorded in Follow-ups above). |
| W11 | Acknowledged | Plan deviation now documented explicitly in this log's preamble. |
| W12 | Fixed | Entry criteria section added above. |

Suggestions S1, S5: incorporated (newcomer context paragraph; promoted "When to reconsider sidecar" reasoning inline). S2, S3, S4, S7: incorporated into the patterns section (version pinning, credential storage, exception sanitization, Rust-binary pinning). S6: not applicable — model is correctly `claude-opus-4-7` per session context.

</details>

<details>
<summary>ATX Review (manual CLI, Round 2)</summary>

**Tool**: `atx review request`
**Timestamp**: 2026-05-11T15:34:00Z
**Rating**: 3/5 (threshold > 3/5)
**Blockers**: 0
**Warnings**: 7
**Cost**: $1.9811

Round 1 fixes all verified clear. New warnings raised and resolved:

| # | Status | Resolution |
|---|--------|-----------|
| W-R2-1 | Documented | Verified `_sanitize_exception_text` bearer-token gap (regex `\b(token|auth|password)\b\s*[:=]\s*` doesn't match `Authorization: Bearer <token>` — no `\b` after `auth`, no `:`/`=` between `Bearer` and the token). Doc now flags the gap explicitly and prescribes a `(?i)\bBearer\s+([A-Za-z0-9._~+/-]{8,})` → `Bearer ***` fix to land with Slice 3. Fixing the function itself is out of scope for this docs-only PR. |
| W-R2-2 | Fixed | Expanded `'L3150'` shorthand to `'gateway/platforms/api_server.py:3150–3169 (is_network_accessible guard)'` and noted `docs/agent-support/hermes.md:191` will need a follow-up update in Slice 1. |
| W-R2-3 | Fixed | Rewrote model-selection bullet: `config.provider.default_model` is the `hosts.json` input, rendered as `model.default` in `~/.hermes/config.yaml` by `templates/config.yaml.j2:33–34` (read at line 8). |
| W-R2-4 | Fixed | Corrected `.itx/322/00_PLAN.md:67,183` to drop `--user` and use full unit name (`systemctl status hermes-<name>.service`). |
| W-R2-5 | Fixed | `docs/index.md` link description switched to future tense + `(planned — see #322)`. |
| W-R2-6 | Fixed | Patterns section tense audit pass — `introduces`/`flips`/`reads` → `will introduce`/`will flip`/`will source`. |
| W-R2-7 | Fixed | Scope-expansion sentence added above. |

Suggestion S-1 (canonical stdin pipe pattern): not incorporated — adds implementation detail beyond what a reconsideration note needs.

</details>

<details>
<summary>ATX Review (manual CLI, Round 3)</summary>

**Tool**: `atx review request`
**Timestamp**: 2026-05-11T15:42:00Z
**Rating**: blocked (review confirmed the local changes weren't yet committed; threshold not assessable)
**Blockers**: 1 (B1 — staged-but-not-committed changes)
**Warnings**: 2 (W-R3-1, W-R3-2)
**Cost**: see ATX log

| # | Status | Resolution |
|---|--------|-----------|
| B1 | Fixed by Round 4 commit | All R2+R3 fixes amended into a single squashed commit on `issue-334-aichat-doc`; force-push to update PR #335. |
| W-R3-1 | Fixed | `clm sources` → `clm will source` in patterns section. |
| W-R3-2 | Fixed | `{8,}` quantifier in prescribed Bearer regex relaxed to `{1,}` (false positives are acceptable for sanitization; short test tokens must still redact). |

Round 3 also surfaced unrelated carry-forward items (`docs/agent-support/hermes.md:191,116`, Slice 1 test gaps). All belong to #322 Slices 1/3, not this PR.

</details>

<details>
<summary>ATX Review (manual CLI, Round 4 — final)</summary>

**Tool**: `atx review request`
**Timestamp**: 2026-05-11T15:46:00Z
**Rating**: 4/5 ✅ (threshold > 3/5 cleared)
**Blockers**: 0
**Warnings**: 1 (W-R4-1, deferred-to-Slice-3)
**Suggestions**: 4 (all deferred to Slice 3 or noted as quality-of-life)
**Composite specialist ratings**: security-secrets 4/5, cli-ux 4/5, test-coverage 3/5

W-R4-1 (no xfail anchor for the sanitizer gap): acknowledged. Belongs to Slice 3 of #322, not this docs-only PR. Suggestions S-R4-1..S-R4-4 all queued for Slice 3.

**Disposition**: PR #335 ready to merge.

</details>

## ATX iteration summary

| Round | Rating | Blockers | Disposition |
|-------|--------|----------|-------------|
| 1 | 2/5 | B1, B2 | Both fixed |
| 2 | 3/5 | 0 | 7 warnings — all fixed |
| 3 | blocked | B1 (uncommitted) | Fixed by commit `dea2408` + 2 warnings fixed |
| 4 | **4/5** | 0 | Merge-eligible; 1 deferred warning belongs to Slice 3 of #322 |

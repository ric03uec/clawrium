# Issue #376 — Execution Scaffolding

**Mode:** multi-phase (3 phases, two of them parallel after Phase 1)

Plan reference: [`.itx/376/00_PLAN.md`](./00_PLAN.md). Each phase maps 1:1 to an existing subtask issue created during planning — **no new subtasks are filed by this scaffold**.

## Phase Topology

```
Phase 1 (#402) ──► Phase 2 (#403)  ┐
                                   ├─► All maurice skills live
              ──► Phase 3 (#404)  ┘
```

Phase 2 and Phase 3 can run in parallel once Phase 1 merges. They touch disjoint files (`skills/hermes/{issue-triage,daily-digest,docs-sync}/` vs `skills/hermes/{release-watcher,blog-author}/`) and exercise the same already-installed agent, so no merge conflicts and no shared runtime state.

---

### Phase 1 — Bootstrap hermes maurice on `wolf-i`

**Subtask:** #402
**Complexity:** moderate
**Dependencies:** None (skills loader #364 and hermes type #68 already shipped)

**Entry Criteria:**
- `clm agent ls` shows openclaw `maurice` on `wolf-i` (the agent we are replacing)
- `OPENROUTER_API_KEY`, `DISCORD_BOT_TOKEN`, and the `clawrium-github` integration are present in `~/.config/clawrium/secrets.json` / `providers.json` / `integrations.json`
- **GitHub PAT is reused, not created.** The existing `clawrium-github` integration already holds a `GITHUB_TOKEN` (created 2026-04-16) used by the current openclaw maurice. The new hermes maurice binds to the **same** integration; this phase does **not** mint a new PAT. The phase only **confirms** that the existing PAT's scope rules are correct (see exit criteria).
- Branch protection on `main` is configured (or will be confirmed as the last step of this phase)
- No in-flight work depends on the existing openclaw `maurice`'s runtime state

**Files Affected:**
- `~/.config/clawrium/hosts.json` — `wolf-i.agents.maurice.agent_type`: `openclaw` → `hermes`
- `~/.config/clawrium/secrets.json` — `wolf-i:hermes:maurice` keys populated (`HERMES_API_SERVER_KEY`, `OPENROUTER_API_KEY`, `DISCORD_BOT_TOKEN`, `GITHUB_TOKEN`)
- `~/.config/clawrium/providers.json` — `maurice-openrouter.default_model` updated to chosen GLM coding model (proposal: `z-ai/glm-4.6`)
- Agent host (`wolf-i`): `~/.hermes/SOUL.md`, `~/.hermes/.env`, `~/.hermes/config.yaml`
- GitHub: branch-protection rule on `main`; label-permission policy on `agent-ready` (no repo file changes)

**Exit Criteria:**
- Old openclaw `maurice` fully removed — `clm ps` shows it gone, no traces in `hosts.json`
- `clm agent install --type hermes --host wolf-i --name maurice` succeeds; `clm ps` shows `maurice` as `hermes`
- `clm agent configure maurice` completes every stage; `validate` stage `health_check` (`curl /health`) returns 200
- `~/.hermes/SOUL.md` exists and is under hermes' 2200-char cap
- `gh auth status` inside `clm chat maurice` shell tool succeeds, **using the existing `clawrium-github` PAT** (no new token created)
- A test Discord post lands in channel `1494198125223612427`
- **PAT scope confirmation** on the existing `clawrium-github` token (no rotation, no new token):
  - Positive: read contents/discussions/releases; write issues/PRs/non-`agent-ready` labels
  - Negative test 1: `gh api -X PUT repos/ric03uec/clawrium/git/refs/heads/main` returns 403
  - Negative test 2: `gh issue edit <test-issue> --add-label agent-ready` returns 403
  - If either negative test passes (i.e., PAT is over-scoped), tighten the PAT scope on github.com before proceeding to Phase 2/3 — but still reuse the same token id, not a new one
- `make test` and `make lint` pass (no regressions — this phase touches no Python source)

---

### Phase 2 — Skills: issue-triage + daily-digest + docs-sync

**Subtask:** #403
**Complexity:** moderate
**Dependencies:** Phase 1 (#402)

**Entry Criteria:**
- All Phase 1 exit criteria met
- Maurice is reachable via `clm chat maurice` and Discord
- `LABELS.md` exists in the repo root (issue-triage depends on it); if missing, this phase creates it before authoring `issue-triage`

**Files Affected:**
- `skills/hermes/issue-triage/SKILL.md` — new
- `skills/hermes/daily-digest/SKILL.md` — new
- `skills/hermes/docs-sync/SKILL.md` — new
- `LABELS.md` — created if missing (issue-triage reads it)
- Agent host (`wolf-i`): `~/.hermes/skills/clawrium/{issue-triage,daily-digest,docs-sync}/SKILL.md`
- `~/.config/clawrium/agents/maurice/skills.json` — desired-state file lists three new slugs
- Host-side scheduler: hermes' internal cron (preferred) or systemd timer units calling `clm chat maurice "<prompt>"`

**Exit Criteria:**
- Each new `SKILL.md` validates against `skills/_schema/native/hermes.schema.json` (covered by `make test`)
- `clm agent skill list maurice` shows all three new slugs
- Triggers are wired and fire at the cadences in the plan (10 min for issue-triage; daily for digest and docs-sync)
- End-to-end demos, with links pasted into #403 before close:
  - issue-triage: a freshly opened test issue receives `type:*` / `complexity:*` / `area:*` labels and a `.itx/active/<id>/plan.md` PR
  - daily-digest: one Discord post in `1494198125223612427` summarizing the last 24h
  - docs-sync: at least one PR proposing a doc or scenario update from a real 24h diff
- No skill bypasses the PAT scope (no push to `main`, no `agent-ready` applied during demos)
- `make test` and `make lint` pass

---

### Phase 3 — Skills: blog-author + release-watcher

**Subtask:** #404
**Complexity:** moderate
**Dependencies:** Phase 1 (#402). **Independent of Phase 2** — may run in parallel.

**Entry Criteria:**
- All Phase 1 exit criteria met
- Maurice reachable; Discord DM path to user `740723459344302120` confirmed (release-watcher uses DM, not channel post)

**Files Affected:**
- `skills/hermes/release-watcher/SKILL.md` — new
- `skills/hermes/blog-author/SKILL.md` — new
- `blog/` directory — created if missing (blog-author writes PRs against it)
- Agent host (`wolf-i`): `~/.hermes/skills/clawrium/{release-watcher,blog-author}/SKILL.md`
- `~/.config/clawrium/agents/maurice/skills.json` — desired-state file appended with two new slugs
- Host-side scheduler: 30 min poll for blog-author release-tag check; daily for release-watcher

**Exit Criteria:**
- Both new `SKILL.md` files validate against `skills/_schema/native/hermes.schema.json`
- `clm agent skill list maurice` shows both new slugs
- Triggers wired at the documented cadences
- End-to-end demos, with links pasted into #404 before close:
  - release-watcher: a real DM to user `740723459344302120` containing 3 candidate features with one-line rationales and approve/skip pattern; on approval, a new GitHub issue is created with `type:*` / `area:*` labels
  - blog-author: a real release tag (or synthetic tag if no recent release) yields a PR against `blog/` with at least one runnable scenario snippet
- Slack-replacement decision documented in `release-watcher/SKILL.md` (Discord DM instead of Slack DM)
- No skill bypasses the PAT scope
- `make test` and `make lint` pass

---

## Closing #376

#376 closes when all three subtasks (#402, #403, #404) are closed AND all acceptance criteria in the issue body are checked off. Each subtask's PR should reference `Closes #<subtask>` and the final PR (or a follow-up doc PR) should reference `Closes #376`.

---

<details>
<summary>Prompt Log</summary>

**Stage**: scaffolding
**Skill**: /itx:plan-scaffold
**Timestamp**: 2026-05-17T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 376
```

Inputs from prior planning session ([`00_PLAN.md`](./00_PLAN.md)):
- 3 subtasks already created and linked as sub-issues: #402, #403, #404
- Host: `wolf-i` (replaces existing openclaw maurice)
- Discord channel/guild/user reused; Slack dropped
- GLM model chosen at execution time (proposal: `z-ai/glm-4.6`)

</details>

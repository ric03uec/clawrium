# Clawrium SDLC Pipeline — Master Plan

## Goal

Run a 4-agent hermes fleet on `wolf-i` that covers the full software delivery
lifecycle for `ric03uec/clawrium`: sourcing → triage → execution → GTM.
Agents are orchestrator-driven today (human or LLM pokes each in sequence).
Auto-chaining is a follow-up.

---

## Architecture

```
Sources (GitHub, HN, Discord, upstream releases)
         │
         ▼
┌──────────────────┐
│ clawrium-maurice │  Sourcing / PM — monitors upstream repos, files GH issues
│   (hermes)       │  Discord: yes (existing discord-maurice bot)
└────────┬─────────┘
         │  creates GitHub issue with labels
         ▼
┌──────────────────┐
│ clawrium-triage  │  Triage — labels, plans, marks planned (+ agent-ready for xs/s)
│   (hermes)       │  Discord: yes — #triage
└────────┬─────────┘
         │  updates issue labels + opens triage PR with plan
         ▼
┌──────────────────┐
│ clawrium-exec    │  Execution — clones repo, writes code, validates, opens PR
│   (hermes)       │  Discord: yes — #coder-fleet
└────────┬─────────┘
         │  PR opened → human merges
         ▼
┌──────────────────┐
│ clawrium-gtm     │  GTM — announces merge, updates CHANGELOG, blogs
│   (hermes)       │  Discord: yes — #announcements
└──────────────────┘
```

---

## Agents

### clawrium-maurice
- **Role**: Sourcing / project manager. Monitors upstream releases for
  hermes-agent, zeroclaw, and openclaw. Files GH issues ONLY when: (1) the
  upstream change is a new user-facing feature, AND (2) it is not already
  tracked in `ric03uec/clawrium`. No approval gate — if both checks pass,
  issue is filed automatically.
- **Host**: wolf-i
- **Type**: hermes
- **Provider**: clm-openrouter
- **Discord**: `#qna` channel `1494198125223612427` — reuses existing `discord-maurice` bot
- **SOUL.md limit**: 2,000 characters
- **Skills**:
  - `upstream-hermes` — monitors NousResearch/hermes-agent releases
  - `upstream-zeroclaw` — monitors zeroclaw/zeroclaw releases
  - `upstream-openclaw` — monitors openclaw/openclaw releases
  - All 3 share the same double-check contract: file only if (new feature) AND (not in clawrium)

### clawrium-triage
- **Role**: Takes a newly filed issue and gets it execution-ready: apply
  type/complexity/area labels, draft `.itx/<n>/00_PLAN.md`, open a triage PR,
  remove `needs-triage`, add `planned`.
  **agent-ready contract**: if triage assigns complexity:xs OR complexity:s,
  it MAY also add `agent-ready`. If complexity is m/l/xl or unknown, it MUST
  NOT add `agent-ready` — that remains a human decision.
- **Host**: wolf-i
- **Type**: hermes
- **Provider**: clm-openrouter
- **Discord**: `#triage` channel `1513395156852674590`
- **SOUL.md limit**: 2,000 characters
- **Skills**:
  - `sdlc-triage` — core triage loop with agent-ready contract

### clawrium-exec
- **Role**: Picks up issues labeled BOTH `agent-ready` AND `planned` with
  complexity xs/s. Works on ONE issue at a time (no parallel execution).
  ALWAYS on a branch — never commits to main. Runs full test suite (`make test`
  + `make lint`) before PR. Uses the validate skill to confirm the branch
  satisfies the issue's Definition of Done before opening a PR.
- **Host**: wolf-i
- **Type**: hermes
- **Provider**: clm-openrouter
- **Discord**: `#coder-fleet` channel `1506153398117077092` — reuses migrated d01 bot token
- **SOUL.md limit**: 2,000 characters
- **Skills**:
  - `sdlc-exec` — full issue→branch→test→validate→PR loop
  - `validate` — reads issue DoD, inspects branch diff, iterates with exec until DoD satisfied, then approves PR

### clawrium-gtm
- **Role**: Closes the loop after a PR is merged. Posts announcement to
  `#announcements`. Updates `CHANGELOG.md [Unreleased]` for user-visible
  changes. Drafts release blog posts. Maintains daily digest of shipped work.
- **Host**: wolf-i
- **Type**: hermes
- **Provider**: clm-openrouter
- **Discord**: `#announcements` channel `1494197384094416906`
- **SOUL.md limit**: 2,000 characters
- **Skills**:
  - `announcements` — post PR announcement to #announcements, update CHANGELOG
  - `blog-author` — draft release blog posts from merged PRs
  - `daily-digest` — daily summary of shipped work to Discord

---

## Agent Creation — Step-by-Step Commands

All skill attachment uses `clawctl agent skill attach` (not `agent skill add`).
Custom skills live under `.sdlc/<agent>/skills/` and are pushed via
`clawctl agent memory edit`. Never edit the clawctl registry directly.

```bash
# 0. PREREQUISITE — migrate clawrium-d01 Discord bot token to clawrium-exec namespace
clawctl secret get wolf-i clawrium-d01 DISCORD_BOT_TOKEN   # copy the value
clawctl secret set wolf-i clawrium-exec DISCORD_BOT_TOKEN  # paste the same value
# Verify both are identical before proceeding.

# 1. Remove clawrium-d01 (token migrated above; d01 dbus-daemon may need sudo pkill)
#    On wolf-i: sudo pkill -9 -u clawrium-d01 && sudo userdel -r clawrium-d01
clawctl agent delete clawrium-d01 --yes

# 2. Push SOUL.md to all agents
clawctl agent memory edit clawrium-maurice SOUL.md --content-file .sdlc/clawrium-maurice/SOUL.md
clawctl agent memory edit clawrium-triage  SOUL.md --content-file .sdlc/clawrium-triage/SOUL.md
clawctl agent memory edit clawrium-exec    SOUL.md --content-file .sdlc/clawrium-exec/SOUL.md
clawctl agent memory edit clawrium-gtm     SOUL.md --content-file .sdlc/clawrium-gtm/SOUL.md

# 3. Push custom skills via memory edit, then attach via clawctl
#    clawrium-maurice
clawctl agent memory edit clawrium-maurice upstream-hermes.md  --content-file .sdlc/clawrium-maurice/skills/upstream-hermes/SKILL.md
clawctl agent memory edit clawrium-maurice upstream-zeroclaw.md --content-file .sdlc/clawrium-maurice/skills/upstream-zeroclaw/SKILL.md
clawctl agent memory edit clawrium-maurice upstream-openclaw.md --content-file .sdlc/clawrium-maurice/skills/upstream-openclaw/SKILL.md
clawctl agent skill attach upstream-hermes  --agent clawrium-maurice
clawctl agent skill attach upstream-zeroclaw --agent clawrium-maurice
clawctl agent skill attach upstream-openclaw --agent clawrium-maurice

#    clawrium-triage
clawctl agent memory edit clawrium-triage sdlc-triage.md --content-file .sdlc/clawrium-triage/skills/sdlc-triage/SKILL.md
clawctl agent skill attach sdlc-triage --agent clawrium-triage

#    clawrium-exec
clawctl agent memory edit clawrium-exec sdlc-exec.md  --content-file .sdlc/clawrium-exec/skills/sdlc-exec/SKILL.md
clawctl agent memory edit clawrium-exec validate.md   --content-file .sdlc/clawrium-exec/skills/validate/SKILL.md
clawctl agent skill attach sdlc-exec --agent clawrium-exec
clawctl agent skill attach validate  --agent clawrium-exec

#    clawrium-gtm
clawctl agent memory edit clawrium-gtm announcements.md --content-file .sdlc/clawrium-gtm/skills/announcements/SKILL.md
clawctl agent memory edit clawrium-gtm blog-author.md   --content-file .sdlc/clawrium-gtm/skills/blog-author/SKILL.md
clawctl agent memory edit clawrium-gtm daily-digest.md  --content-file .sdlc/clawrium-gtm/skills/daily-digest/SKILL.md
clawctl agent skill attach announcements --agent clawrium-gtm
clawctl agent skill attach blog-author   --agent clawrium-gtm
clawctl agent skill attach daily-digest  --agent clawrium-gtm

# 4. Sync all agents (push desired state to host)
clawctl agent sync clawrium-maurice
clawctl agent sync clawrium-triage
clawctl agent sync clawrium-exec
clawctl agent sync clawrium-gtm

# 5. Commit LABELS.md and merge (triage reads it at runtime via gh api)
git add LABELS.md && git commit -m "chore: add LABELS.md taxonomy"
gh pr create --title "chore: add LABELS.md taxonomy"
# merge the PR
```

---

## Label Workflow

### Full state machine

```
FILED
  Labels set: needs-triage, agent-created (if by Maurice),
              source:* (if by Maurice), type:* (from Maurice),
              complexity:* (from Maurice if known)

  ↓ clawrium-triage (sdlc-triage skill)
TRIAGED (planned)
  Removes: needs-triage
  Adds: planned, type:* (if missing), complexity:* (if missing), area:*
  Also adds agent-ready IF complexity is xs OR s (triage contract)

  ↓ HUMAN GATE (if not agent-ready) — review triage PR, add ready + agent-ready

  ↓ clawrium-exec — picks up ONLY if: agent-ready + planned + complexity xs/s
IN PROGRESS (in-progress)
  Removes: ready
  Adds: in-progress
  One issue at a time — exec will not pick up a second issue while one is open

  ↓ exec validate skill confirms DoD satisfied
IN REVIEW (in-review)
  Removes: in-progress
  Adds: in-review
  PR opened against main on branch exec/<N>-<slug>

  ↓ HUMAN merges exec PR
CLOSED
  clawrium-gtm announces + updates CHANGELOG
```

If triage finds the issue body too sparse:
- Removes `needs-triage`, adds `needs-review`
- Posts comment asking for Outcome + DoD
- Stays in `needs-review` until reporter updates → human re-adds `needs-triage`

If exec is blocked:
- Removes `in-progress`, adds `agent-blocked`
- Posts `[EXEC-BLOCKED]: missing required credential (github-token or discord-bot-token)` comment
- Never discloses internal secret-store paths or key names in public comments

### Label gaps — DONE

Repo now has 42 labels. See `LABELS.md` for full taxonomy.

---

## MVP Workflow — Issue → PR Merge → Announcement

```
Orchestrator
  │
  ├─[TC-1] Tell clawrium-maurice: "Create a test issue titled
  │         'test: sdlc pipeline smoke TC-1'. Labels: agent-created,
  │         type:test, complexity:xs, needs-triage."
  │         → returns issue number N
  │
  ├─[TC-2] Tell clawrium-triage: "Triage issue #N"
  │         Triage reads issue, applies area:* label, drafts
  │         .itx/N/00_PLAN.md, opens PR triage/N-pipeline-smoke,
  │         removes needs-triage, adds planned + agent-ready (xs → allowed)
  │         → returns triage PR number T
  │
  │         [TC-2-gate] Human merges triage PR T.
  │         Human adds ready + agent-ready to issue #N (or triage already set agent-ready)
  │
  ├─[TC-3] Tell clawrium-exec: "Execute issue #N. Add a one-liner to
  │         CHANGELOG.md [Unreleased] as the implementation.
  │         Run make test. Open a PR."
  │         Exec: reads DoD, branches exec/N-smoke, implements, runs make test,
  │         validate skill confirms DoD, opens PR exec/N-smoke
  │         → returns exec PR number P
  │
  │         [TC-3-gate] Human reviews and merges PR P
  │
  └─[TC-4] Tell clawrium-gtm: "PR #P was merged for issue #N. Announce it."
            GTM posts to #announcements (channel 1494197384094416906)
            GTM checks CHANGELOG.md — if unchanged, adds one-liner under [Unreleased]
```

---

## Test Plan

### Prerequisites

- All 4 agents online (`clawctl agent get` shows `ready` for all)
- `integration:clawrium-github` GitHub PAT present in secrets (repo scope)
- clawrium-exec Discord bot active (#coder-fleet, reused d01 token)
- clawrium-gtm Discord bot active with access to `#announcements` only
- clawrium-triage Discord bot active with access to `#triage` only
- LABELS.md committed and merged to main

### Test Cases

**TC-1: Maurice creates issue**
- Prompt: `@clawrium-maurice Create a test issue titled "test: sdlc pipeline smoke TC-1". Labels: agent-created, type:test, complexity:xs, needs-triage.`
- Pass: `gh issue view <N>` shows all 4 labels

**TC-2: Triage processes issue**
- Prompt: `@clawrium-triage Triage issue #<N>`
- Pass: planned label on issue, triage PR open, `.itx/<N>/00_PLAN.md` not empty
- Bonus: agent-ready label set (because complexity:xs)

**TC-3: Exec implements and PRs**
- Prompt: `@clawrium-exec Execute issue #<N>. Add a one-liner to CHANGELOG.md [Unreleased] as the implementation. Run make test. Open a PR.`
- Pass: PR open on GitHub, make test passes in PR, PR body links issue with `Closes #N`

**TC-4: GTM announces**
- Prompt: `@clawrium-gtm PR #<P> was merged for issue #<N>. Announce it.`
- Pass: Discord message in #announcements with PR link, CHANGELOG updated if needed

---

## SOUL.md Writing Rules

- Character limit: **2,000** per agent (hermes hard limit)
- Must include: repo URL, project board URL, version, label taxonomy summary,
  pipeline position, skills this agent runs, hard rules, Discord channel ID
- Do NOT exceed 2,000 chars — hermes silently truncates

---

## Open Items

| # | Item | Status | Blocking |
|---|------|--------|---------|
| 1 | Create missing labels (type:test, type:chore, area:*) | done | — |
| 2 | Commit LABELS.md PR | open | triage agent runtime |
| 3 | clawrium-gtm Discord bot created, token registered | done | — |
| 4 | clawrium-triage Discord bot created, token registered | done | — |
| 5 | All Discord channel IDs confirmed | done | — |
| 6 | Verify `integration:clawrium-github` PAT has `repo` scope | deferred (assumed yes) | TC-3 |
| 7 | Write SOUL.md files (all 4 agents, 2,000 char limit) | open | P2.7 |
| 8 | Write skill files: upstream-hermes, upstream-zeroclaw, upstream-openclaw | open | P2.8 |
| 9 | Write/update skill files: sdlc-triage, sdlc-exec, validate, announcements | open | P2.8 |
| 10 | Write skill files: blog-author, daily-digest (gtm) | open | P2.8 |
| 11 | clawrium-d01 delete (sudo pkill -9 -u clawrium-d01 needed on wolf-i) | blocked | — |

---

## Layers (sequence)

1. **Layer 1** — plan, folder structure, agent SOULs, custom skill specs
2. **Layer 2** — push SOULs, install skills, sync all 4 agents
3. **Layer 3** — commit LABELS.md, run TC-1 → TC-4 smoke test
4. **Layer 4** — add scheduling (cron on triage, webhook on PR merge for GTM)
5. **Layer 5** — per-role model assignment (GLM→Maurice, Kimi K2→Triage, Claude→Exec, Deepseek→GTM)

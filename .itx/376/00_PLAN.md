# Issue #376 — Maurice (Hermes) project maintainer for ric03uec/clawrium

Persistent hermes agent named `maurice` that owns every non-code responsibility for this repo: triage, plans, doc sync, release watching, daily digests, blog drafts. Identity stays minimal in `SOUL.md`; behavior lives in five hermes-native skills. All triggers are poll-based. Write enforcement lives at the GitHub PAT scope, not in the agent.

## Overview

The platform primitives required for this work already exist:

- Hermes agent type is shipped (`src/clawrium/platform/registry/hermes/` — install/configure/start/stop/skills_apply playbooks).
- Skills loader (#364) is shipped: `clm agent skill install <agent> <registry>/<name>` materializes `skills/hermes/<name>/SKILL.md` into `~/.hermes/skills/clawrium/<name>/` on the host.
- Provider registration (`clm provider register --type openrouter`), secret store (`secrets.json`), and channels (Discord + CLI/HTTP) are all implemented for hermes.

Therefore #376 is **not** a platform-feature issue. It is:
1. One operational bootstrap (replacing the current openclaw `maurice` on `wolf-i` with a hermes one).
2. Five hermes-native skill authoring tasks under `skills/hermes/<name>/`.
3. GitHub-side hardening (PAT scope, branch protection, label-permission policy).

## Inputs (resolved during user clarification)

| Item | Value |
|---|---|
| Host | `wolf-i` (the issue calls it `workstation`; only `wolf-i` is registered, and the current openclaw maurice already runs there) |
| Agent type | `hermes` |
| Agent name | `maurice` (existing openclaw `maurice` is **retired** as part of bootstrap) |
| Inference provider | `openrouter` (provider name `maurice-openrouter`, reusing existing OPENROUTER_API_KEY) |
| Inference model | Best GLM coding model on OpenRouter at execution time; default proposal `z-ai/glm-4.6` (existing openclaw maurice uses `z-ai/glm-4.5-air`) |
| Discord guild | `1493388235567661127` (reused from existing maurice) |
| Discord home channel | `1494198125223612427` (reused) |
| Discord allowed user | `740723459344302120` (reused) |
| Slack | **Not used** — release-watcher approve/skip flow moves to Discord DM in the same guild |
| GitHub auth | Fine-grained PAT via `clawrium-github` integration (already configured) |
| Cadences | Issue defaults: 10 min issue-triage, 30 min blog-author release-tag poll, daily for docs-sync / release-watcher / daily-digest |

## Files to Modify / Create

### Skills catalog (this repo)

```
skills/hermes/
├── issue-triage/SKILL.md
├── daily-digest/SKILL.md
├── docs-sync/SKILL.md
├── release-watcher/SKILL.md
└── blog-author/SKILL.md
```

Each `SKILL.md` is hermes-native (validated against `skills/_schema/native/hermes.schema.json`) with frontmatter (`name`, `description`, `version`, etc.) followed by the skill prompt. Skills consume `gh` CLI for GitHub access; no MCP server is required for the GitHub side.

### Agent state (~/.config/clawrium/)

- `hosts.json` — `wolf-i.agents.maurice` flips from `agent_type: openclaw` to `agent_type: hermes` after retire+install.
- `secrets.json` — `wolf-i:hermes:maurice` keys: `HERMES_API_SERVER_KEY` (auto), `OPENROUTER_API_KEY` (reuse), `DISCORD_BOT_TOKEN` (reuse), `GITHUB_TOKEN` (via integration).
- `providers.json` — `maurice-openrouter` model field updated to chosen GLM model.

### Agent host (`wolf-i`, under hermes user)

- `~/.hermes/SOUL.md` — minimal identity (under hermes' 2200-char cap).
- `~/.hermes/skills/clawrium/<name>/SKILL.md` — five files written by `clm agent skill install`.
- `~/.hermes/.env` — rendered by `clm agent configure` (OPENROUTER_API_KEY, DISCORD_BOT_TOKEN, GITHUB_TOKEN, HERMES_API_SERVER_KEY).
- Host-side cron/systemd timer units invoking `clm chat maurice "<skill-prompt>"` if hermes' internal scheduler is unavailable (decided at execution).

### GitHub repo configuration

- Branch protection on `main` excluding the Maurice PAT.
- Label-permission policy preventing the Maurice PAT from applying `agent-ready`.
- `LABELS.md` (referenced by issue-triage) — confirm present and authoritative; create if missing.

## Steps

1. **Retire existing openclaw `maurice`.** Stop, remove via `clm agent remove maurice`. Preserve discord token, github integration binding, and OPENROUTER_API_KEY for reuse.
2. **Install hermes `maurice` on `wolf-i`.** `clm agent install --type hermes --host wolf-i --name maurice`.
3. **Configure provider + channels.** `clm agent configure maurice`:
   - providers: pick OpenRouter, set model to the chosen GLM coding model.
   - channels: enable Discord with reused guild/channel/user; CLI on; Slack off.
4. **Set minimal SOUL.md.** `clm agent memory edit maurice SOUL.md` (under 2200 chars, voice + non-marketing rule only).
5. **Verify GitHub auth path.** Bind `clawrium-github` integration; confirm `gh auth status` works from the hermes shell (`clm chat maurice` → shell tool).
6. **Author the five hermes skills** under `skills/hermes/<name>/SKILL.md`. Each skill describes: trigger context, allowed tools, output channel, behavioral guardrails (e.g., max 2 new scenarios per docs-sync run). PR-ready for review; no hand-rolled MCP.
7. **Install skills onto maurice.** `clm agent skill install maurice hermes/<name>` for each. Confirm files land in `~/.hermes/skills/clawrium/<name>/`.
8. **Wire triggers.** Prefer hermes' internal scheduler; fall back to host systemd timers calling `clm chat maurice "<prompt>"`. Cadences as in issue.
9. **GitHub hardening.**
   - Verify Maurice PAT scope matches the allowlist (read contents/discussions/releases; write issues/PRs/non-`agent-ready` labels).
   - Confirm branch protection on `main` blocks the PAT.
   - Confirm `agent-ready` is unwritable by the PAT.
10. **End-to-end demo per skill.** Run each against a real artifact (test issue, real 24h diff, real release tag) and confirm the output channel receives the expected artifact. Capture sample output in subtask issue body.

## Test Strategy

- **Skill schema validation:** `make test` covers `skills/_schema/native/hermes.schema.json`; each new `SKILL.md` must pass.
- **Skill install state:** after each `clm agent skill install`, confirm desired-state file `~/.config/clawrium/agents/maurice/skills.json` contains the slug.
- **Provider connectivity:** `clm agent configure maurice` `verify_provider` stage hits OpenRouter live.
- **Channel reachability:** Discord post lands in the home channel; DM-reachable user verified.
- **GitHub auth:** `gh auth status` inside hermes shell returns success; `gh api repos/ric03uec/clawrium` returns 200.
- **PAT scope (negative tests):** `gh api -X PUT repos/ric03uec/clawrium/git/refs/heads/main` returns 403; `gh issue edit <n> --add-label agent-ready` returns 403.
- **End-to-end per skill:** one real-artifact run per skill, evidence captured in the subtask issue.

## Risks

- **Replacement disruption.** Retiring openclaw `maurice` deletes its working state. Verify no open work or in-flight outputs depend on it before remove.
- **GLM model selection.** "Best GLM for coding on OpenRouter" is a moving target; pick at execution and record the version in `providers.json` + the bootstrap subtask's PR body.
- **Slack-replacement for release-watcher.** Issue spec called for Slack DM approve/skip; we move it to Discord DM in the same guild. Behavior preserved, channel changed; document in release-watcher skill.
- **Scheduler primitive.** Hermes' internal cron may not exist yet; the systemd-timer fallback is acceptable but means cron behavior is enforced outside the agent. Decided during execution.
- **PAT misconfiguration.** The plan only succeeds if the PAT actually cannot push to `main` or apply `agent-ready`. Both negative tests (above) must pass before any skill is enabled.
- **Existing openclaw maurice on `wolf-i`** shares the same OPENROUTER_API_KEY and DISCORD_BOT_TOKEN with this new agent during the cutover window. Order steps so the openclaw is fully removed before the hermes one starts.

## Subtasks (3, per user)

1. **`[Parent #376]` Bootstrap hermes maurice on wolf-i (retire openclaw, install/configure, provider, Discord, SOUL, GitHub PAT hardening)**
2. **`[Parent #376]` Author + install + demo skills: issue-triage, daily-digest, docs-sync**
3. **`[Parent #376]` Author + install + demo skills: blog-author, release-watcher**

Order: subtask 1 must merge before 2; 2 before 3 only if release-watcher reuses patterns from docs-sync (otherwise 2 and 3 may be parallel).

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-17T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 376
```

User clarifications during planning:
- Subtask split: 3 — (1) bootstrap+provider+channels(Discord), (2) issue-triage + daily-digest + docs-sync, (3) blog-author + release-watcher.
- GLM model: best GLM coding model on OpenRouter; chosen at execution.
- Discord channel: reuse exact channel id from the existing maurice agent — this issue replaces that agent.
- Slack: not needed; release-watcher approve/skip moves to Discord DM.

</details>

# Issue #589 — Hermes multi-provider attach via clawctl + GUI

GitHub: https://github.com/ric03uec/clawrium/issues/589

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-30T00:00:00Z
**Model**: claude-opus-4-7

```prompt
create a new issue for this. hermes agents needs to allow multiple providers in config via clawctl. (only hermes) . do a research on what configs need to change to support this. give me a plan first before creating any issues or files
```

**Output**: GitHub issue #589 created describing the remaining work to complete hermes multi-provider attach end-to-end via clawctl + GUI: CLI `--role` flag, template + env rendering, per-attachment API-key hydration, detach guard, tests, and docs. Scoped to hermes only.

## Pre-issue research summary (so future agents don't re-derive)

- #501 landed Phase 1 (data model in `src/clawrium/core/provider_attachments.py` + lifecycle overlay in `src/clawrium/core/lifecycle.py:1263-1296`). Closed.
- CLI attach unconditionally rejects 2nd provider: `src/clawrium/cli/clawctl/agent/provider.py:106-118`. No `--role` flag.
- Template gap: `src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2` reads only `config.provider`; `auxiliary:` hardcoded to `provider: "auto"`.
- Env gap: `src/clawrium/platform/registry/hermes/templates/hermes.env.j2` emits one `*_API_KEY` for primary's type only.
- Hydration gap: `src/clawrium/core/lifecycle.py:2024-2040` loads only primary's API key. TODO marker at `lifecycle.py:1488-1494` explicitly blocks Phase 3 template work on this.
- GUI surface: `src/clawrium/gui/routes/providers.py` + frontend modal need a role selector for hermes.

## Open decisions confirmed during planning

- **Scope**: clawctl + backend + GUI (GUI included per user).
- **First-attach UX**: `--role` always required on hermes (no auto-primary).
- **Out of scope**: fallback chains, `set-role`/promote command, changes to zeroclaw/openclaw.

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-04T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:plan-create https://github.com/ric03uec/clawrium/issues/589 . no file updats, give me a highlevel plan only first
```

**Output**: High-level plan + 4 subtask breakdown; subtasks created and linked as sub-issues; plan posted as comment on #589.

### Overview

#501 wired the data model + lifecycle overlay for hermes multi-provider. #589 finishes the end-to-end path: CLI, GUI, templates, and API-key hydration are still single-provider. Scope: **hermes only** — zeroclaw/openclaw singleton invariant untouched.

Work splits into four orthogonal seams that each compile + test independently:

1. **CLI surface** — `--role` on attach, detach guard, polished `get`.
2. **Hydration** — per-attachment API key dict threaded from `lifecycle.configure_agent` into ansible vars.
3. **Templates** — `hermes-config.yaml.j2` renders `auxiliary.<role>` per non-primary attachment; `hermes.env.j2` emits one `*_API_KEY` per unique provider type. Keep `hermes-config.canonical.yaml.j2` in lockstep.
4. **GUI parity** — `gui/routes/providers.py` + provider modal gain a role selector for hermes attachments.

**Order is load-bearing**: Subtask 2 (hydration) must land before Subtask 3 (templates), otherwise auxiliary slots render with empty `*_API_KEY` and hermes routes auxiliary calls to 401 — exactly the regression the Phase 3 TODO at `lifecycle.py:1488-1494` warns against. 1 and 4 can land in either order around 2/3; natural progression is 1 → 2 → 3 → 4.

### Subtasks

| # | Subtask | Touches |
|---|---|---|
| 1 | CLI `--role` flag, gated singleton check, detach-primary guard | `src/clawrium/cli/clawctl/agent/provider.py`, tests |
| 2 | Per-attachment API-key hydration into ansible_vars | `src/clawrium/core/lifecycle.py` (~2024-2060 + configure path), tests |
| 3 | Multi-provider template rendering | `hermes-config.yaml.j2`, `hermes-config.canonical.yaml.j2`, `hermes.env.j2`, integration tests |
| 4 | GUI role selector + multi-attach flow | `gui/routes/providers.py`, frontend modal, tests |

Docs (`AGENTS.md` hermes section + `docs/`) ride along with whichever PR closes the last subtask in the chain.

### Per-subtask detail

#### Subtask 1 — CLI attach/detach

- Add `--role` Typer option to `attach`. Required on hermes (rejected with remediation hint if missing); rejected with a clear error on non-hermes.
- Gate the existing singleton-invariant rejection on `not supports_multi_provider(agent_type)` — preserves the verbatim zeroclaw/openclaw message that tests pin (`single-provider invariant requires exactly one`, see `provider_attachments.py:130-137`).
- Migrate `_get_attached_providers` / `_set_attached_providers` callers to round-trip via `provider_attachments.normalize` + `validate`. Don't duplicate role-uniqueness — `validate()` already owns it.
- Detach guard: if target attachment is `role == primary` and `len(attachments) > 1`, refuse with a hint pointing at the exact aux-detach commands. Promotion is out-of-scope.
- `get`: confirm table renderer prints `name`, `role`, `model` columns when agent type supports multi; keep flat list for singleton agents.
- Tests: each acceptance-criteria bullet on the CLI gets a unit test.

#### Subtask 2 — Hydration

- In `lifecycle.configure_agent` (~`lifecycle.py:2042`), branch on `_pa.supports_multi_provider(resolved_type)` and presence of `config_data["providers"]`:
  - **Multi path**: iterate `providers[]`, build `provider_api_keys: dict[str, str]` keyed by **provider name** (not type — two attachments of the same type are still distinct provider records). Bedrock entries hydrate AWS creds into a parallel `provider_aws_credentials` dict keyed by provider name.
  - **Singleton path**: leave existing `provider_api_key` / `aws_access_key` / `aws_secret_key` untouched. Zero behavioral change for zeroclaw/openclaw.
- Thread the new dicts through `ansible_vars` so the templates can iterate them.
- Additive, not replacing: the primary's key MUST also continue to populate the legacy `provider_api_key` var so canonical-pipeline templates that haven't migrated keep working.
- Tests: hydration unit test feeding a fake `config.providers` with 1 primary anthropic + 1 aux openrouter + 1 aux bedrock; assert resulting dict shape.

#### Subtask 3 — Templates

- `hermes-config.yaml.j2`:
  - Iterate `config.providers | default([])`.
  - Render the existing per-type `model:` block from the entry where `role == 'primary'` (no behavior change for primary path).
  - For each non-primary entry, render `auxiliary.<role>:` with `provider:` (same per-type switch the primary uses) and `model:` (from `entry.model`). Match upstream `hermes_cli/config.py:716-795`.
  - Keep the existing `auxiliary.title_generation.model:` default for the primary's type **only if** no explicit `title_generation` attachment exists.
- `hermes-config.canonical.yaml.j2`: identical change (AGENTS.md flags these two template families must stay in lockstep until consolidation).
- `hermes.env.j2`:
  - Iterate `config.providers`, collect `(provider_type, api_key)` set (dedup by type — two openrouter attachments share one `OPENROUTER_API_KEY`).
  - Emit one `*_API_KEY` per unique type. Bedrock keeps the AWS-credential triplet.
  - Conflict handling: two providers of the same type with different keys → emit the primary's key and a `# WARNING` comment. Document in AGENTS.md.
- Integration test: fake hosts.json with 1 primary anthropic + 1 aux openrouter; run `configure_agent` (legacy pipeline); snapshot-assert rendered yaml + env contents.

#### Subtask 4 — GUI parity

- `gui/routes/providers.py`: extend attach endpoint to accept optional `role`; validate server-side against `VALID_ROLES`; reject missing role for hermes agents (mirror CLI rule).
- Provider modal: when target agent is hermes, surface a role dropdown populated from `VALID_ROLES`. Filter `primary` from the dropdown when a primary already exists (and inversely require it for the first attach).
- Detach button on the row labeled `primary`: disabled when other rows exist, with a tooltip hint.
- Exact modal shape (extend existing vs. dedicated view) is an execution-time call — contract is functional parity with the CLI for hermes.
- Tests: route-level test for `role` validation + role-list filtering.

### Files to modify

- `src/clawrium/cli/clawctl/agent/provider.py` (subtask 1)
- `src/clawrium/core/lifecycle.py` (subtask 2)
- `src/clawrium/platform/registry/hermes/templates/hermes-config.yaml.j2` (subtask 3)
- `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2` (subtask 3)
- `src/clawrium/platform/registry/hermes/templates/hermes.env.j2` (subtask 3)
- `src/clawrium/gui/routes/providers.py` + provider modal (subtask 4)
- `AGENTS.md` hermes section + `docs/` (rides with final subtask)
- Unit + integration tests per subtask

### Risks

1. **Two template families** — `hermes-config.yaml.j2` (legacy ansible) and `hermes-config.canonical.yaml.j2` (canonical sync pipeline) both need the change. Tests must exercise both paths or one will silently rot.
2. **Empty-key blast radius** — if hydration lands after templates, every aux slot renders with an empty `*_API_KEY` and hermes 401s on auxiliary calls. TODO at `lifecycle.py:1488-1494` exists for exactly this. Subtask ordering is the mitigation.
3. **Singleton regression for zeroclaw/openclaw** — gating change in subtask 1 must preserve the exact error string. `provider_attachments.validate` comment at lines 130-137 calls this out.
4. **Real-host verification** — per memory `hermes_v2026_5_7_chat_bugs.md`, hermes manifest bumps need real-host install verification. This change doesn't bump the manifest, but a `sync` against a real hermes host with 1 primary + 1 aux is the only way to catch upstream schema drift in `auxiliary.<slot>`. Recommended before merging subtask 3.
5. **Detach-primary semantics** — operator workflow becomes "detach all aux → detach primary → re-attach new primary." Document in AGENTS.md and the detach hint string.

### Test strategy

- **Unit** per subtask (see per-subtask notes).
- **Integration**: end-to-end synthetic — fake `hosts.json` with 1 primary anthropic + 1 aux openrouter + 1 aux bedrock → run `lifecycle.configure_agent` in render-only mode → snapshot-assert `hermes-config.yaml` and `hermes.env`.
- **Real-host**: one manual `clawctl agent sync` against a live hermes host after subtask 3, before merge.
- **Regression**: existing zeroclaw/openclaw provider tests run unchanged and pass — canary for the singleton-invariant gating.

### Subtasks created

- #612 — `[Parent #589] CLI: --role flag on provider attach + detach-primary guard for hermes`
- #613 — `[Parent #589] Lifecycle: per-attachment API-key hydration into ansible_vars (hermes)`
- #614 — `[Parent #589] Templates: render auxiliary.<role> + per-type env keys for hermes multi-provider`
- #615 — `[Parent #589] GUI: role selector + multi-attach parity for hermes provider attach`

Ordering: 1 → 2 → 3 → 4. Subtask 3 (#614) is blocked on subtask 2 (#613) until hydration lands; everything else can run in parallel within reason.

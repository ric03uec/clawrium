# Issue #734 — Execution Scaffolding

GitHub: https://github.com/ric03uec/clawrium/issues/734
Plan: [`00_PLAN.md`](00_PLAN.md)

**Mode**: single-PR, 3 user-facing phases.
**Subtasks**: none (per plan — #723 precedent).

Phase boundaries map to **operator-observable milestones**, not code-layer milestones:

1. **Operator can store + attach a Brave key, and it lands correctly on every supported agent.**
2. **Operator can do all of that from the GUI and find docs for it.**
3. **It actually works on real hosts — proven, not just unit-tested.**

Each phase has exit criteria phrased as "what an operator can do that they couldn't before".

---

## Phase 1: Operator can wire a Brave key into any supported agent

**Operator outcome**: `clawctl integration registry create my-brave --type brave --api-key <key>` → `clawctl agent integration attach <agent> my-brave` → `clawctl agent sync <agent>` → the Brave key lands on the host in the shape that agent's upstream expects, for hermes / zeroclaw / openclaw.

**Entry Criteria**:
- Branch cut from `main`, `.itx/734/00_PLAN.md` committed, base `make test` green.

**Exit Criteria**:
- `INTEGRATION_TYPES["brave"]` registered with one required credential `BRAVE_API_KEY` — operator sees only that name.
- `clawctl integration registry create --type brave --api-key <key>` and `--api-key-stdin` work; positional credential rejected; `clawctl integration rotate` re-syncs every bound agent; `delete` blocks when attached (`--force` detaches + re-syncs).
- For each agent type — hermes, zeroclaw, openclaw — `attach` + `sync` produces the correct on-host bytes:
  - hermes `~/.hermes/.env` contains `BRAVE_SEARCH_API_KEY=<value>` (name-mapped in `render_hermes`, not in Jinja).
  - zeroclaw env contains BOTH `Environment=BRAVE_API_KEY=…` AND `Environment=ZEROCLAW_web_search__search_provider="brave"`.
  - openclaw `~/.openclaw/env` contains `BRAVE_API_KEY=<value>`; `configure.yaml` (+ `configure_macos.yaml` sibling) installs pinned `@openclaw/brave-plugin@2026.6.8` (sentinel-guarded, `no_log: true`).
- Openclaw attach against a host at `< 2026.4.10` fails fast with the documented "run `clawctl agent upgrade` first" message.
- Removing an agent purges its `integration:brave:*` secrets — no stale credential on re-create.
- Existing github / linear / notion / gitlab / atlassian byte-locks unchanged (regression-pinned).
- **#437 invariant pinned**: every brave-affecting sync calls `_do_pair()` unconditionally. **#622 invariant pinned**: hermes env bytes written only by `render_hermes()`, pushed via `ansible.builtin.copy`. **Dispatcher-only OS fork**: macOS branching only in `playbook_resolver.py`; `*_macos.yaml` siblings.
- `make test` + `make lint` green.

**Dependencies**: none.

**Complexity**: complex (touches registry, renderer, templates, CLI, lifecycle, playbook, dispatcher OS fork — all the code-side work lives here).

---

## Phase 2: Operator can do it from the GUI and find docs

**Operator outcome**: a non-CLI operator opens the GUI, picks "Add integration → Brave", pastes the key, attaches it to an agent, and finds a docs page that explains the name-mapping, the openclaw min-version, and the zeroclaw routing constraint.

**Entry Criteria**: Phase 1 exit met.

**Exit Criteria**:
- GUI add-integration modal shows a Brave card with a single masked `API key` field. `POST /api/integrations` with `{kind: "brave", credentials: {BRAVE_API_KEY: …}}` returns 201; raw key never appears in any response payload.
- Per-agent attach UI reuses the existing github component — no new wiring, no per-attach secret cloning.
- `docs/agent-support/{hermes,zeroclaw,openclaw}.md` each have a brave row; new `docs/agent-support/integrations/brave.md` covers the `BRAVE_API_KEY` (operator) vs `BRAVE_SEARCH_API_KEY` (hermes) name-mapping, zeroclaw `search_provider` constraint, openclaw `minHostVersion >=2026.4.10`, and a `clawctl integration rotate` example.
- `website/docs/...` mirrors land verbatim per the `AGENTS.md` mirror rule.
- `CHANGELOG.md` `## [Unreleased]` → `### Added` entry names the new type, per-agent matrix, hermes name-mapping, openclaw plugin install + min-version, and GUI support.
- `make test` + `make lint` green.

**Dependencies**: Phase 1.

**Complexity**: moderate.

---

## Phase 3: It actually works on real hosts

**Operator outcome**: a Brave-routed web search succeeds end-to-end on `espresso` (hermes), `clawrium-d01` (zeroclaw), and an openclaw host at `>=2026.4.10` — with logs/screenshots proving the request went through Brave, not a silent fallback.

**Entry Criteria**:
- Phases 1 + 2 exit met.
- Targets reachable: `espresso`, `clawrium-d01`, an openclaw host at `>=2026.4.10` (fresh install or `wolf-i` upgraded via `clawctl agent upgrade`).
- A live Brave Search API key available.

**Exit Criteria**:
- **hermes (`espresso`)**: attach + sync drift=0 on rerun; `web_search` tool call returns a Brave-routed result (log line confirms `BRAVE_SEARCH_API_KEY` resolved; no DDGS fallback).
- **zeroclaw (`clawrium-d01`)**: attach + sync drift=0; `web_search` actually routes via Brave, not silently to duckduckgo. **Decision point**: if env-prefix override doesn't apply at boot, fall back to TOML deep-update of `[web_search]` — captured in PR body as a follow-up if needed.
- **openclaw (≥2026.4.10)**: attach + sync drift=0; `openclaw plugins list` shows `@openclaw/brave-plugin@2026.6.8`; `openclaw agent --message "search the web for clawrium"` returns Brave-routed result.
- Preflight rejection verified once on a deliberately-old openclaw host (`< 2026.4.10`).
- Logs/screenshots attached to PR for each agent.

**Dependencies**: Phases 1 + 2.

**Complexity**: complex (real-host, multi-agent, includes the zeroclaw routing-fallback decision).

---

## Sequencing

```
1 (plumbing — all code/tests) → 2 (GUI + docs) → 3 (live proof)
```

---

## Prompt log

### Scaffolding

**Stage**: scaffolding
**Skill**: /itx-plan-scaffold
**Timestamp**: 2026-06-19T02:57:02Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-scaffold 734
```

Initial scaffold had 6 code-layer phases (render foundation, CLI, lifecycle+playbook, GUI, docs, live verification). User asked for fewer, more user-focused phases. Collapsed to 3 phases where each boundary is an operator-observable milestone — "can wire a Brave key", "can do it from GUI + find docs", "proven on real hosts". All code-side work (registry, CLI, renderer, templates, lifecycle, playbook, dispatcher OS fork) lives in Phase 1 because none of it produces a separately-observable operator outcome before the whole vertical works. The three invariants from the plan (#437, #622, dispatcher-only OS fork) are pinned inside Phase 1's exit criteria so they don't get lost in the consolidation.

**Output**: revised `.itx/734/01_SCAFFOLD.md`; issue comment updated.

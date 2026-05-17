# Issue #384 — Phase 5 Execution Log

Scope (from issue body): mirror Phases 2–3 (CLI per-agent install/list/
remove) in the GUI. Real install on all three claws via browser, drift
recovery, cross-surface parity with `clm agent skill list`.

Plan reference: `.itx/364/00_PLAN.md` § *Files to add → GUI backend
(agents.py extension), GUI frontend (Skills tab + filtered picker)*.

## What shipped

**Backend (`src/clawrium/gui/routes/agents.py`):**

- `GET /api/agents/{agent_key}/skills` — returns `{ agent_name,
  agent_type, installed[], available[] }`. `available` is the catalog
  filtered to "installable on this claw type": `clawrium/*` whose
  `_meta.yaml.compatibility[<claw>] = true` plus the matching
  `<claw>/*` native registry. The filter lives in
  `_is_compatible_for_agent_type` and fail-closes on any catalog
  error — same rule `check_agent_compatibility` uses.
- `POST /api/agents/{agent_key}/skills/{registry}/{skill}` — installs.
  Mutates desired state via `add_skill`, then always invokes
  `apply_state(agent_name)`. Re-installing an already-installed skill
  is the documented drift-recovery path — `changed: false` but the
  playbook still runs.
- `DELETE /api/agents/{agent_key}/skills/{registry}/{skill}` — removes.
  Same idempotency rule: removing an absent skill is a no-op state
  mutation but the playbook still runs to prune any orphan host
  directory.
- `SkillError` → HTTP status mapping (`_skill_error_status`):

  | Error class                                               | Status |
  |-----------------------------------------------------------|--------|
  | `AgentNotFoundError`, `SkillNotFound`                     | 404    |
  | `MissingRegistryPrefix`, `ExternalSourceBlocked`,         |        |
  |   `InvalidSkillRef`, `IncompatibleSkillRegistry`,         |        |
  |   `SchemaValidationError`, `SkillApplyNotSupported`       | 422    |
  | `SkillApplyError`                                         | 502    |

  502 (not 500) is deliberate: a failed ansible/SSH run is an
  upstream-host failure, not a server bug — the GUI should treat it
  as transient and let the user retry. The CLI surfaces these as
  `SkillApplyError`; the GUI maps them to a Bad-Gateway category so
  the alert-banner text is meaningful.

**Frontend types / api / hooks (`gui/src/lib/`, `gui/src/hooks/`):**

- `types.ts`: `AgentSkillRow`, `AgentSkills`,
  `AgentSkillMutationResponse`.
- `api.ts`: `getAgentSkills`, `installAgentSkill`, `removeAgentSkill`.
- `hooks/use-skills.ts`: `useAgentSkills`, `useInstallAgentSkill`,
  `useRemoveAgentSkill` — react-query mutations invalidate the
  `["agent-skills", agentKey]` query key so the installed-list and
  available-picker both re-render after install/remove.

**Frontend (`gui/src/components/agent-detail/skills-tab.tsx`):**

- Replaced the placeholder card with a real Skills tab:
  - "Installed Skills" card lists each row with a registry badge,
    `ref`, version, description preview, and a per-row **Remove**
    button.
  - "Install skill" button opens a modal with the **filtered picker**.
    The picker subtracts already-installed refs so the user can't try
    to "install" a duplicate, and renders an empty-state hint
    pointing at the right catalog directory when nothing is available
    (e.g. a claw type with no native skills + no clawrium skills marked
    compatible).
  - Mutation errors render inline as a `role="alert"` banner above
    the cards, so the user sees the failure without losing context.
- `tab-nav.tsx`: renamed the tab label from "Skills & Tools" to
  "Skills". The "& Tools" half referenced the now-removed integrations
  placeholder card; no integrations work happens in this PR.

**Tests:**

- `tests/test_gui_agent_skills_routes.py` (15 tests):
  - GET: 404 on unknown agent, payload shape, available filtering by
    each claw (hermes/openclaw/zeroclaw), empty-state passthrough.
  - POST: state mutation + apply, idempotency, 404 on unknown agent,
    422 on `ExternalSourceBlocked`, 422 on `IncompatibleSkillRegistry`,
    502 on `SkillApplyError`.
  - DELETE: state mutation + apply, idempotency on no-op, 404, 422.
- `gui/src/components/agent-detail/skills-tab.test.tsx` (9 tests):
  loading state, error state with retry, empty-state hint, installed
  rows, picker filtering, picker hides installed, install + remove
  mutations invoked with `{agentKey, registry, name}`, inline error
  rendering.

## Verification

```
$ make test
============================ 2113 passed in 19.62s =============================
 Test Files  13 passed (13)
      Tests  115 passed (115)

$ make lint
uv run ruff check src tests
All checks passed!
✔ No ESLint warnings or errors
```

(2113 pytest + 115 vitest. Phase 4 baseline was 2098 + 106; this PR
adds 15 backend + 9 vitest tests.)

## Real smoke-test transcript

Test fleet (Phase 0): all three running on `wolf-i` (192.168.1.36).
Agent names: `tdd-hermes`, `tdd-openclaw`, `tdd-zeroclaw`.

GUI server: `uv run uvicorn clawrium.gui.server:app --port 38384`.

### tdd-hermes (hermes — file-drop to `~/.hermes/skills/clawrium/`)

```
$ curl -X POST .../api/agents/tdd-hermes/skills/clawrium/tdd
{"success":true,"agent_name":"tdd-hermes","ref":"clawrium/tdd",
 "changed":true,"installed":["clawrium/tdd"]}

$ ssh wolf-i 'sudo ls /home/tdd-hermes/.hermes/skills/clawrium/'
tdd

$ ssh wolf-i 'sudo head -3 /home/tdd-hermes/.hermes/skills/clawrium/tdd/SKILL.md'
---
name: tdd
description: 'Test-Driven Development discipline. ...'

# Cross-surface parity:
$ clm agent skill list tdd-hermes
       Skills on tdd-hermes
┃ Ref          ┃ Registry ┃ Name ┃
│ clawrium/tdd │ clawrium │ tdd  │

# Drift recovery (delete on host, re-POST → file restored):
$ ssh wolf-i 'sudo rm -rf /home/tdd-hermes/.hermes/skills/clawrium/tdd'
$ curl -X POST .../skills/clawrium/tdd
{"changed":false,"installed":["clawrium/tdd"]}     # state unchanged, but...
$ ssh wolf-i 'sudo ls /home/tdd-hermes/.hermes/skills/clawrium/tdd/'
SKILL.md                                            # ...host reconciled

$ curl -X DELETE .../skills/clawrium/tdd
{"changed":true,"installed":[]}
$ ssh wolf-i 'sudo ls /home/tdd-hermes/.hermes/skills/clawrium/'
(empty)
```

### tdd-openclaw (openclaw — file-drop to `~/.openclaw/skills/`)

```
$ curl -X POST .../api/agents/tdd-openclaw/skills/clawrium/tdd
{"success":true,"changed":true,"installed":["clawrium/tdd"]}

$ ssh wolf-i 'sudo ls /home/tdd-openclaw/.openclaw/skills/'
tdd

# Drift recovery: same pattern — file restored on re-POST.
# DELETE: directory pruned.
```

### tdd-zeroclaw (zeroclaw — native `zeroclaw skills install` to `~/.zeroclaw/workspace/skills/`)

```
$ curl -X POST .../api/agents/tdd-zeroclaw/skills/clawrium/tdd
{"success":true,"changed":true,"installed":["clawrium/tdd"]}

$ ssh wolf-i 'sudo find /home/tdd-zeroclaw/.zeroclaw -name "SKILL.md"'
/home/tdd-zeroclaw/.zeroclaw/workspace/skills/tdd/SKILL.md

# zeroclaw's path differs from the other claws — the native CLI puts
# files under workspace/skills/ (Phase 0 finding). The clawrium GUI
# route is agnostic; whatever the per-claw playbook produces is what
# the host sees.
```

All three claws: install → host materialization confirmed, CLI
parity confirmed via `clm agent skill list`, drift recovery confirmed
(delete on host → re-POST → file restored), remove confirmed
(host directory pruned).

Browser visual smoke: `/tmp/skills-smoke/agent-detail-tdd-hermes.png`
shows the agent-detail page rendering with the new **Skills** tab in
the navigation row. Tab interaction itself is covered by the vitest
suite for `skills-tab.tsx` — chrome-headless `--screenshot` doesn't
fire React onClick handlers, so the interactive flow (click Install →
modal opens → pick row → install fires → row appears under Installed)
is asserted in `skills-tab.test.tsx`. That's the same pattern Phase 4
used in `.itx/383/01_EXECUTION.md`.

## Decisions worth noting

1. **Filtered picker on the server, not the client.** `available` is
   already filtered to "compatible with this claw" before the GUI sees
   it. Reasoning: keeps the compatibility-resolution logic
   (`check_agent_compatibility` + native-registry-self-match) in one
   place — Python — so a future change to the rule doesn't have to be
   mirrored in TypeScript. The frontend only does set-subtraction
   (available minus installed) to hide duplicates from the picker.

2. **502 for apply failures.** A `SkillApplyError` is a host/SSH
   failure, not a server bug. Mapping it to 500 would conflate "your
   request is fine but the host is unreachable" with "this server is
   broken". 502 (Bad Gateway) gives the GUI a clean signal to render a
   retry-able banner and lets log monitors that page on 5xx ignore
   transient host blips by status alone.

3. **`changed: false` does not imply "did nothing"**. The API returns
   `changed` so the UI can render "already installed; host
   reconciled" vs "newly installed" copy if it wants to, but the
   apply playbook runs unconditionally on every POST/DELETE. The
   drift-recovery contract (CLI Phase 2/3) is preserved in the GUI.

4. **Tab label rename.** `"Skills & Tools"` → `"Skills"`. The
   placeholder Skills tab contained a separate "Integrations"
   sub-card, which is why the original label had `& Tools`. With
   integrations living on its own sidebar page (#373), the per-agent
   tab is now skills-only. Single-word label avoids the misleading
   ampersand.

## What's NOT in this PR

- Per-agent **integrations** management. The Phase 5 scope is skills
  only. Integrations stays on the dedicated `/integrations` page.
- Docs / CI / end-to-end multi-skill fixtures. That's Phase 6 (#385+).
- Deep-linking the active tab via `?tab=skills` querystring. Would be
  useful for support handoffs but the issue scope doesn't call for it.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-05-17T19:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 384 --pr-base=issue-383-gui-skill-catalog-browse
```

</details>

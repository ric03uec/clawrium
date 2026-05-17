# Issue #383 — Phase 4 Execution Log

Scope (from issue body): mirror the Phase 1 CLI catalog browse in the
GUI. Open `/skills`, see registry tabs, click a card, see the SKILL.md
detail. No remote host needed, no per-agent install paths — that's
Phase 5+.

Plan reference: `.itx/364/00_PLAN.md` § *Files to add → GUI backend,
GUI frontend, Tests*. Same `core/skills.py` API the CLI uses; the GUI
is a thin read layer on top.

## What shipped

**Backend (`src/clawrium/gui/routes/skills.py`):**

- `GET /api/skills` — registry-grouped catalog. Response shape:

  ```
  {
    "registries": ["clawrium", "openclaw", "hermes", "zeroclaw"],
    "skills": {
      "clawrium": [<summary>, ...],
      "openclaw": [], ...
    }
  }
  ```

  Empty registries appear as empty arrays so the GUI always renders
  four tabs. A missing catalog directory degrades to an all-empty
  response rather than 500 — same UX rule the CLI uses.

- `GET /api/skills/{registry}/{name}` — full skill payload:
  `{ ref, registry, name, metadata, body, compatibility }`. The
  derived `compatibility` map is `{openclaw, hermes, zeroclaw}: bool`
  regardless of source registry, so the frontend never has to switch
  on registry kind.

- `SkillError` → HTTP status mapping:

  | Error class | Status |
  |---|---|
  | `MissingRegistryPrefix`, `ExternalSourceBlocked`, `InvalidSkillRef` | 422 |
  | `SchemaValidationError` (catalog-author error) | 422 |
  | `SkillNotFound` | 404 |

  Catalog-author errors are surfaced as 422 (not 500) so a broken
  `_meta.yaml` doesn't pretend to be a server outage.

- Loading + validation runs in `asyncio.to_thread` since
  `core.skills` does sync filesystem + YAML/JSON parsing.

- Router registered in `gui/server.py` alongside the existing seven.

**Frontend types / api / hooks:**

- `gui/src/lib/types.ts` — `SkillRegistry`, `SkillSummary`,
  `SkillsCatalog`, `SkillDetail`, `SkillCompatibility`.
- `gui/src/lib/api.ts` — `api.getSkills()`, `api.getSkill(reg, name)`.
- `gui/src/hooks/use-skills.ts` — `useSkills`, `useSkill(reg, name)`
  (the latter is `enabled: !!reg && !!name` so it stays idle until a
  card is selected).

**Frontend components (`gui/src/components/skills/`):**

- `skill-card.tsx` — registry-badge + ref + version + truncated
  description. Whole card is a button (`role=button` with explicit
  `aria-label`) so keyboard/screen-reader users can open the detail.
- `skill-detail.tsx` — metadata table + compatibility badges + raw
  SKILL.md body in a `<pre>` block. Incompatible claws render with
  `line-through` styling so the gating is visually obvious.

**Frontend page (`gui/src/app/skills/page.tsx`):**

- Registry tabs (`role=tablist`, `role=tab`, `aria-selected`) with a
  count badge per registry — matches existing tab idioms used in the
  agent-detail view.
- Empty-state message points the user at the matching `skills/<r>/`
  directory in the repo, mirroring the CLI hint from
  `clm skill list --registry <r>`.
- Card click opens a detail modal that fetches `/api/skills/{r}/{n}`
  on demand. Keeps the catalog list lightweight (descriptions only)
  and only pulls SKILL.md bodies when the user opens them.

**Sidebar:** Added `Skills` between `Providers` and `Integrations`.
Test that asserted nav order updated accordingly.

**Tests:**

- `tests/test_gui_skills_routes.py` (10 tests) — covers all four
  200/404/422 paths called out in the issue's exit gates, plus a
  schema-mismatch fixture that proves catalog-author errors don't
  become 500.
- `gui/src/components/skills/skill-card.test.tsx` (6 tests).
- `gui/src/components/skills/skill-detail.test.tsx` (6 tests).
- `gui/src/app/skills/page.test.tsx` (6 tests) — tabs render, empty
  state per registry, card click opens modal.
- `gui/src/components/layout/sidebar.test.tsx` updated to assert the
  new four-item ordering.

## Verification

```
$ make test-py
============================ 2098 passed in 17.44s =============================

$ cd gui && npm test
 Test Files  12 passed (12)
      Tests  106 passed (106)

$ make lint
uv run ruff check src tests
All checks passed!
✔ No ESLint warnings or errors
```

Backend smoke against a running uvicorn:

```
$ curl -s http://127.0.0.1:38383/api/skills | jq '.registries, (.skills | keys), (.skills.clawrium[0].ref)'
["clawrium","openclaw","hermes","zeroclaw"]
["clawrium","hermes","openclaw","zeroclaw"]
"clawrium/tdd"

$ curl -s http://127.0.0.1:38383/api/skills/clawrium/tdd | jq '.compatibility'
{ "openclaw": true, "hermes": true, "zeroclaw": true }

$ curl -sw "%{http_code}\n" -o /dev/null http://127.0.0.1:38383/api/skills/clawrium/does-not-exist
404

$ curl -sw "%{http_code}\n" -o /dev/null http://127.0.0.1:38383/api/skills/bogus/x
422
```

Frontend browser smoke (chrome-headless against the staged static
build served by uvicorn on :38383):

- Visited `/skills` — page renders with the sidebar's `Skills` entry
  active, registry tabs (`Clawrium 1`, `OpenClaw 0`, `Hermes 0`,
  `ZeroClaw 0`), and the `clawrium/tdd` card showing the description
  preview and `v0.1.0` chip.
- Empty tabs and modal interaction are covered by the vitest page
  test (`opens the detail modal when a skill is clicked`,
  `renders the empty-state hint when a tab has no skills`); the
  chrome-headless single-frame capture wouldn't add coverage beyond
  what vitest already proves.

Screenshot: `/tmp/skills-smoke/skills-tab-clawrium.png` (attached to
PR body).

## Decisions worth noting

1. **Modal vs separate detail page.** The plan listed `SkillDetail` as
   a component; routing to `/skills/<registry>/<name>` would mean
   another static-export entry and a back-button dance. Modal keeps
   the catalog browse context intact and matches the existing
   integrations page's "row + detail modal" pattern.

2. **Per-card click target.** Made the whole card a `<button>` (with
   an `aria-label`) rather than a nested "Open" button — fewer click
   targets, better screen-reader announcements, no risk of a buried
   click target inside the description text.

3. **Loader-failure rendering.** A single bad `_meta.yaml` should not
   blank the entire catalog tab. The summary endpoint degrades to a
   `description: null` row (matches the CLI's `?` fallback in
   `_short_description`). The detail endpoint raises 422 because the
   user explicitly opened that one row.

4. **`asyncio.to_thread` boundary.** `core.skills` does sync IO. The
   project's existing routes already wrap sync calls in
   `asyncio.to_thread`; following the same pattern keeps event-loop
   behavior consistent.

## What's NOT in this PR

- Per-agent install/remove (`POST /api/agents/{agent}/skills/...`).
  That's the next phase — the issue scope is explicitly "mirror of
  Phase 1" (browse-only).
- `AgentSkillsPanel` from the plan's Files-to-add list. That belongs
  with the per-agent install flow.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-05-17T19:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 383 --pr-base=issue-382-cli-skill-install-openclaw-zeroclaw
```

</details>

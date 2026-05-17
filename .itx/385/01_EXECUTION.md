# Issue #385 — Phase 6 Execution Log

Phase 6 of parent #364: contributor safety net (docs + CI dual-schema
validation) plus the final acceptance sweep across all three claws.

## Scope shipped

**CI validator + workflow**
- `scripts/validate_skills.py` — dual-schema validator that walks
  `skills/`, validates every skill against its registry's schema, and
  enforces path-traversal + schema-mismatch guards. Importable from
  tests; runnable directly for local dev.
- `.github/workflows/skills-validate.yml` — runs on PRs that touch
  `skills/`, the validator, the schemas, or the validator's tests.

**Tests**
- `tests/test_validate_skills_script.py` — 13 fixture tests covering
  the happy path, the four path-traversal vectors, the three
  schema-mismatch vectors, the missing-file cases, and the
  invariant that the real in-repo catalog always validates.

**Docs**
- `docs/skills/index.md`, `docs/skills/authoring-clawrium.md`,
  `docs/skills/authoring-native.md` — repo-rooted authoring guides.
- `website/docs/skills/intro.md`, `website/docs/skills/authoring.md` —
  user-facing site mirror (registered in `website/sidebars.ts`).
- `AGENTS.md` — quickstart now includes
  `clm agent skill install <agent-name> clawrium/tdd`.

## Final acceptance sweep — CLI + GUI on tdd-* fleet

Host: `wolf-i` (192.168.1.36). Phase 0 fleet (from
`.itx/364/02_PHASE0_FINDINGS.md`).

### CLI

```text
$ uv run clm skill list
clawrium/tdd  clawrium  Test-Driven Development discipline …

$ uv run clm agent skill install tdd-openclaw clawrium/tdd
Installed clawrium/tdd on tdd-openclaw.
$ uv run clm agent skill install tdd-hermes clawrium/tdd
Installed clawrium/tdd on tdd-hermes.
$ uv run clm agent skill install tdd-zeroclaw clawrium/tdd
Installed clawrium/tdd on tdd-zeroclaw.

$ uv run clm agent skill list tdd-openclaw
clawrium/tdd  clawrium  tdd
$ uv run clm agent skill list tdd-hermes
clawrium/tdd  clawrium  tdd
$ uv run clm agent skill list tdd-zeroclaw
clawrium/tdd  clawrium  tdd

$ uv run clm agent skill remove tdd-openclaw clawrium/tdd
Removed clawrium/tdd from tdd-openclaw.
$ uv run clm agent skill remove tdd-hermes clawrium/tdd
Removed clawrium/tdd from tdd-hermes.
$ uv run clm agent skill remove tdd-zeroclaw clawrium/tdd
Removed clawrium/tdd from tdd-zeroclaw.
```

Post-remove `clm agent skill list <agent>` returned "No skills
installed on …" for each of the three.

### GUI (FastAPI surface backing the dashboard)

```text
GET  /api/skills                                  → 200, clawrium/tdd in payload
POST /api/agents/tdd-openclaw/skills/clawrium/tdd → {"success":true,"changed":true,"installed":["clawrium/tdd"]}
POST /api/agents/tdd-hermes/skills/clawrium/tdd   → {"success":true,"changed":true,"installed":["clawrium/tdd"]}
POST /api/agents/tdd-zeroclaw/skills/clawrium/tdd → {"success":true,"changed":true,"installed":["clawrium/tdd"]}

GET /api/agents/tdd-openclaw/skills → installed=[clawrium/tdd], available=[…]
GET /api/agents/tdd-hermes/skills   → installed=[clawrium/tdd], available=[…]
GET /api/agents/tdd-zeroclaw/skills → installed=[clawrium/tdd], available=[…]

DELETE /api/agents/tdd-openclaw/skills/clawrium/tdd → {"success":true,"changed":true,"installed":[]}
DELETE /api/agents/tdd-hermes/skills/clawrium/tdd   → {"success":true,"changed":true,"installed":[]}
DELETE /api/agents/tdd-zeroclaw/skills/clawrium/tdd → {"success":true,"changed":true,"installed":[]}
```

GUI server started with `uv run clm gui --port 9999` and stopped after
the sweep.

## Verification

- `make test` → 2126 Python + 115 GUI tests pass.
- `make lint` → ruff + next lint clean.
- `python scripts/validate_skills.py` → ok against the real catalog.

## PR

Stacked on top of `issue-384-gui-skill-install-all-claws` (parent's
Phase 5 PR), per `/itx:execute 385 --pr-base=issue-384-gui-skill-install-all-claws`.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-17T12:35:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 385 --pr-base=issue-384-gui-skill-install-all-claws
```

</details>

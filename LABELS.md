# Clawrium Label Taxonomy

This file is the authoritative reference for all labels on `ric03uec/clawrium`.
The triage and execution agents read this file directly. Do not rename or remove
labels without updating this file and migrating existing issues.

---

## Workflow State Labels

These labels track where an issue sits in the delivery pipeline. An issue should
carry exactly one state label at a time. The pipeline advances left to right.

| Label | Meaning | Set by |
|---|---|---|
| `needs-triage` | Newly filed; labels/plan not yet applied | Maurice (auto), or human |
| `needs-review` | Body too sparse; Outcome or DoD missing | clawrium-triage |
| `planned` | Triage complete; plan file created | clawrium-triage |
| `planning` | Human is actively writing the plan (manual work in flight) | human |
| `ready` | Plan + scaffold done; cleared for execution | human |
| `in-progress` | Execution agent has picked it up | clawrium-exec |
| `in-review` | PR is open | clawrium-exec |

**Transitions:**

```
needs-triage
  → [clawrium-triage] → planned
  → [human] → ready          (human upgrades after reviewing plan)
  → [clawrium-exec] → in-progress → in-review
  → [human merges PR] → closed
```

`needs-review` is a stop state — the issue sits here until the reporter adds
the missing information, at which point a human re-adds `needs-triage`.

---

## Agent Labels

| Label | Meaning | Set by |
|---|---|---|
| `agent-created` | Issue was filed by an agent (Maurice) | clawrium-maurice |
| `agent-ready` | Cleared for fully autonomous agent execution | clawrium-triage (xs/s only), or human |
| `agent-blocked` | Agent tried to execute and is stuck; see comment for reason | clawrium-exec |

`agent-ready` signals that an issue is safe for autonomous execution by `clawrium-exec`.
`clawrium-triage` may set this label **only** when it assigns `complexity:xs` or `complexity:s`.
For all other complexity levels (`m`, `l`, `xl`) this label must be set by a human after reviewing the triage plan.

---

## Type Labels

Every issue must have exactly one `type:*` label. Apply it during triage.

| Label | Use for |
|---|---|
| `type:bug` | Something broken that worked before |
| `type:question` | Clarification or design question (no code change expected) |
| `type:security` | Security vulnerability or hardening |
| `type:process` | Changes to the SDLC, release, or triage workflows |
| `type:blog` | Blog post or marketing content task |
| `type:test` | Smoke test, integration test, or test-infrastructure issue |
| `type:chore` | Maintenance: deps bump, rename, cleanup, refactor |
| `enhancement` | New feature or improvement (legacy GitHub label — keep as-is) |
| `documentation` | Docs-only change (legacy GitHub label — keep as-is) |

> `enhancement` and `documentation` are legacy GitHub defaults. They are kept
> without the `type:` prefix to avoid migrating hundreds of existing issues.
> New issues from agents use `enhancement` (not `type:enhancement`).

---

## Complexity Labels

Every issue must have exactly one `complexity:*` label. Apply during triage.

| Label | Meaning |
|---|---|
| `complexity:xs` | < 1 hour; trivial one-liner or config change |
| `complexity:s` | 1–4 hours; single file, clear change |
| `complexity:m` | 4–8 hours; a few files, moderate coordination |
| `complexity:l` | 1–3 days; multiple components, non-trivial design |
| `complexity:xl` | 3+ days; architectural or cross-cutting change |

---

## Area Labels

Every issue should have at least one `area:*` label. Apply during triage.
Multiple area labels are allowed.

| Label | What it covers |
|---|---|
| `area:cli` | `clawctl` commands and CLI output |
| `area:gui` | Browser-based fleet UI |
| `area:core` | Core library: render, lifecycle, ssh, ansible runner |
| `area:agent` | Agent type implementations (hermes, zeroclaw, openclaw, nemoclaw) |
| `area:docs` | Documentation and website |
| `area:infra` | CI/CD, packaging, release, test infrastructure |
| `area:skills` | Skill registry and skill templates |

---

## Source Labels

Applied by Maurice when surfacing work from external signals. An issue can have
multiple `source:*` labels if it was surfaced from multiple places.

| Label | Source |
|---|---|
| `source:upstream-deps` | Upstream *claw release notes |
| `source:community` | GitHub Discussions or Discord intake |
| `source:research` | HN agentic-capability scan |

---

## Priority Labels

Applied manually by the maintainer to elevate urgency. At most one `priority:*`
label per issue. Absence means normal priority.

| Label | Meaning |
|---|---|
| `priority:p1` | Critical — blocks a release or affects all users; address immediately |
| `priority:p2` | High — important but not release-blocking; address this sprint |
| `priority:p3` | Low — nice to have; schedule when capacity allows |

---

## Other Labels

| Label | Use for |
|---|---|
| `duplicate` | Already tracked in another issue (close, link the original) |
| `invalid` | Not a valid issue for this repo |
| `wontfix` | Acknowledged but out of scope |
| `help wanted` | Community contribution welcome |
| `good first issue` | Suitable for a first-time contributor |

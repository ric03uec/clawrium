# Implementation Plan — Issue #737

## User Outcome

An operator running `clawctl agent create ... --host <docker-or-unprepared-host>`
gets a **clear, actionable error** instead of a wall of manifest requirements
matched against sentinel values:

- **Before:** either `"Host is incompatible: Requires ubuntu 24.04, host has
  ubuntu unknown, ..."` (partial facts) or a generic `"Cannot determine
  compatible version ... hardware information is not available"` (empty facts).
  Neither mentions Docker.
- **After:** one message that (1) names exactly which facts are missing
  (`os`, `os_version`, `memtotal_mb`), (2) tells the operator how to recover
  (`clawctl host create` re-run or `--version` override), and (3) explicitly
  flags **Docker containers as not-yet-supported** with a pointer to #738.

Net effect: the operator decides in one read whether to re-gather facts,
override with `--version`, or track #738 — instead of filing a duplicate of
#737.

## Overview

Issue #737 reports that `clawctl agent create ... --host docker-worker` on a
freshly-added Docker host fails with a confusing multi-line "Host is
incompatible" message full of literal `unknown unknown` and `0MB` tokens.

The owner's triage comment (2026-07-07) is authoritative: **Docker containers
are not a supported host type yet** (a first-class Docker runtime is tracked
in #738). The fix in this issue is scoped to **error-message clarity** — when
the host record is missing the facts we need (`os`, `os_version`,
`memtotal_mb`), we should say so plainly, name Docker as a known unsupported
case, and point at #738 — instead of formatting the manifest's requirements
against sentinel values (`"unknown"` / `0`) and producing an accidental "wall
of requirements" error.

### Drift check vs. current `main` (fd9e72f)

The reporter was on `26.6.1`. Current `main` is `26.7.2` and already has
partial mitigation from PR #720:

- `src/clawrium/core/registry.py:1082-1091` — `check_compatibility` has a
  `hardware_known` short-circuit that returns `compatible=True,
  matched_entry=None` when `os` is falsy/`"unknown"` **or** `memtotal_mb`
  is `0`.
- `src/clawrium/core/install.py:359-368` — when `matched_entry is None`
  and no `--version` override is set, install refuses with:
  `"Cannot determine compatible version for '<agent>': host hardware
  information is not available. Run 'clawctl host create' with SSH access
  first to gather hardware facts, then retry the install."`

So the **exact** "unknown unknown, ... 0MB, ... unknown unknown, ..."
string reported in the issue is unreachable on current `main` for the
fully-empty case. Two failure modes still produce a poor UX and are what
this plan addresses:

1. **Partial facts** — if fact gathering populated `os` correctly but not
   `os_version` (or vice versa), the short-circuit gate does not trip
   (it only checks `os` and `memtotal_mb`), and the loop at
   `registry.py:1105-1109` still emits `"host has ubuntu unknown"`-style
   strings against every manifest platform entry. This can happen on a
   host where fact gathering succeeds partially (some ansible facts
   present, others missing).
2. **Fully-empty facts** — the `install.py:363-368` message is
   accurate but generic. It does not mention Docker containers, which
   per owner's comment is the specific known-unsupported case that
   generated this bug report; operators hitting the same wall on a
   Docker host today have no signpost to #738.

Both of these are pure error-message improvements. No behavior change
for compatible hosts. Low blast radius.

## Files to Modify

- `src/clawrium/core/registry.py` — tighten `hardware_known` to also
  require `os_version != "unknown"` and non-empty. When the gate trips,
  return `compatible=True, matched_entry=None, reasons=[]` as today
  (so the install.py refusal path takes over — single source of truth
  for the operator-facing message).
- `src/clawrium/core/install.py` — expand the refusal message at
  lines 363-368 to:
  - Enumerate exactly which facts are missing (from
    `host.get("hardware", {})`).
  - Include a one-line note that Docker containers are not yet a
    supported host type, with a `see #738` pointer.
  - Keep the existing remediation hint (`clawctl host create`).
- `tests/test_install.py` — extend the existing
  `test_install_hardware_...` cases (near line 2510) to assert the new
  message shape: mentions the missing fact names, mentions Docker/#738.
- `tests/test_registry.py` — add a case for the partial-facts path
  (`os` set, `os_version="unknown"`) confirming the short-circuit
  now returns `compatible=True, matched_entry=None` instead of
  falling into the loop that would produce `"host has ubuntu unknown"`.

Non-goals (out of scope, tracked elsewhere):

- No changes to fact gathering (`src/clawrium/core/hardware.py`).
- No new Docker host type or runtime (that is #738).
- No changes to manifest schema.

## Steps

1. **Tighten the short-circuit** in `check_compatibility`
   (`registry.py:1082-1091`): compute `hardware_known` from all three
   fields the loop later consumes — `os`, `os_version`, `memtotal_mb`
   — so that any of them being unknown/empty routes through the
   install.py refusal path instead of the requirements loop. Preserve
   the current `compatible=True, matched_entry=None` return shape so
   the install.py contract is unchanged.
2. **Improve the install refusal message** in
   `run_installation` (`install.py:363-368`): inspect
   `host.get("hardware", {})`, build a comma-separated list of the
   missing/unknown facts (`os`, `os_version`, `memtotal_mb`), and
   compose a message of the form:
   ```
   Cannot determine compatible version for '<agent>': host '<hostname>'
   is missing required facts (<list>). Run 'clawctl host create' (or
   re-run it) to gather facts over SSH, or pass '--version <X>' to
   override. Note: Docker containers are not yet a supported host type
   — see https://github.com/ric03uec/clawrium/issues/738.
   ```
   Wording is illustrative; final copy should stay under ~3 lines
   and end with the #738 pointer.
3. **Preserve the `--version` override escape hatch**
   (`install.py:353-355`) — the tighter gate must not fire when the
   operator has explicitly supplied a version. This is already the
   existing behavior; the test at
   `test_install_hardware_unknown_with_version_override_bypasses_check`
   (`tests/test_install.py:2555`) must continue to pass unchanged.
4. **Extend `tests/test_install.py`** with (a) a
   `test_install_hardware_missing_message_mentions_docker` case that
   asserts the refusal string contains `"Docker"` and `"#738"` (or the
   full URL), and (b) a `test_install_partial_facts_missing_os_version`
   case that constructs a host with `os="ubuntu"`, `memtotal_mb=8192`,
   `os_version="unknown"` and asserts the same clean refusal path
   fires (rather than a `Host is incompatible: Requires ubuntu 24.04
   ...` string).
5. **Extend `tests/test_registry.py`** with a unit test on
   `check_compatibility` for the partial-facts input above, asserting
   `compatible=True, matched_entry=None, reasons=[]`.
6. **Changelog entry** — add a bullet under `## [Unreleased]` →
   `### Fixed` in the root `CHANGELOG.md`:
   `- Clearer error when installing an agent onto a host whose facts
   have not been gathered (or a Docker container). References #737,
   #738.`
7. **Run** `make lint && make test` locally.

## Test Strategy

- Unit: `tests/test_registry.py::test_check_compatibility_partial_facts_*`
  covers the tightened gate.
- Unit: `tests/test_install.py::test_install_hardware_*` covers the
  refusal-message copy (mentions missing fact names + Docker + #738)
  and the partial-facts path (`os` set, `os_version="unknown"`).
- Regression: the existing
  `test_install_hardware_unknown_with_version_override_bypasses_check`
  must remain green — proves the `--version` escape hatch still works.
- Real-host UAT (per `feedback_no_pr_without_real_host_uat`): easiest
  reproduction is exactly the reporter's setup — spin the Dockerfile
  in the issue body under `docker compose up -d`, `clawctl host create
  127.0.0.1 --port 2222 --user xclm --alias docker-worker`, then
  `clawctl agent create foo --type openclaw --host docker-worker
  --provider openai`. Capture: before-fix error string vs. after-fix
  error string. Record the host + command in the PR body.
- No changes to happy-path install flow → no additional integration
  coverage needed for compatible hosts.

## Real-host UAT (MUST run before opening PR)

Per `feedback_no_pr_without_real_host_uat`: **lint + unit tests are necessary
but not sufficient.** The following UAT MUST run against **wolf-i** before
the PR is opened, and the PR body MUST record host + observed behavior.

### Target host

- **wolf-i** — the standing multi-agent test host. Fleet snapshot at plan
  time (`clawctl agent get | grep wolf-i`): 10+ agents live, including
  `e2e-openclaw`, `e2e-hermes`, `e2e-zeroclaw` (the three purpose-built
  end-to-end test agents), plus production-adjacent agents `espresso`,
  `clawrium-triage`, `clawrium-gtm`, `clawrium-exec`, `clawrium-maurice`,
  `clawrium-d01`, `ep6-hermes`.

### Integrations attached (from `clawctl agent integration get --agent <name>`)

The change touches `clawctl agent create`'s host-compatibility path — no
runtime path on the daemon side. Enumerated so no integration silently
regresses if we accidentally trip a sync/restart during UAT:

| Agent | Type | Integrations attached |
|-------|------|-----------------------|
| e2e-openclaw | openclaw | (none) |
| e2e-hermes | hermes | (none) |
| e2e-zeroclaw | zeroclaw | (none) |
| espresso | hermes | (none) |
| clawrium-triage | hermes | `clawrium-github` |
| clawrium-gtm | hermes | `clawrium-github` |
| clawrium-exec | hermes | (none) |
| clawrium-maurice | hermes | (none) |
| clawrium-d01 | zeroclaw | `clawrium-d01-github` |
| ep6-hermes | hermes | (none) |

Any agent NOT in the e2e-* trio MUST NOT be touched by the UAT run (they
are shared/production-adjacent). Regression check is limited to
`clawctl agent get` output being unchanged post-UAT (all agents still
`ready`) and the three github-attached agents still reporting the
integration via `clawctl agent integration get --agent <name>`.

### UAT steps

Run from the operator workstation with `clawctl` built from this branch
(`uv tool install -e .` or `uv run clawctl ...`). All commands target
wolf-i-attached agents; nothing new is installed on wolf-i.

**Phase 1 — Negative path (the actual #737 fix)**

The changed code fires when the target host's `hardware` block is
missing/partial. Reproduce cleanly WITHOUT mutating a real host record:

1. `cp ~/.config/clawrium/hosts.json ~/.config/clawrium/hosts.json.bak`
   (safety net; restore verbatim after Phase 1).
2. Add a synthetic host record to `hosts.json` named
   `uat-737-empty-facts` with `hostname: 127.0.0.1`, `port: 22`,
   `hardware: {}`, `agents: {}`. Do NOT run `clawctl host create` — the
   whole point is a fact-less record.
3. Run: `clawctl agent create uat737a --type openclaw --host uat-737-empty-facts --provider openai`.
4. **Expect**: `InstallationError` containing all four assertions from
   the unit test —
   - `"missing required facts (os, os_version, memtotal_mb)"`
   - `"Re-run 'clawctl host create'"`
   - `"Docker containers are not yet a supported host type"`
   - `"github.com/ric03uec/clawrium/issues/738"`
5. Add a second synthetic entry `uat-737-partial-facts` with
   `hardware: {"os": "ubuntu", "os_version": "unknown", "architecture":
   "x86_64", "memtotal_mb": 8192}`. Repeat step 3 against it.
6. **Expect**: same shape as step 4 but the parenthetical reads
   `(os_version)` only.
7. Delete both synthetic entries from `hosts.json` (or restore from
   the `.bak`).

**Phase 2 — Positive-path regression check on wolf-i**

Confirm the change does not affect real hosts whose facts ARE gathered.

8. `clawctl host get wolf-i --show-hardware` — record `os`,
   `os_version`, `architecture`, `memtotal_mb`. All four MUST be
   populated with real values (not `"unknown"` / `0`).
9. `clawctl agent get e2e-openclaw` — MUST show `ready`.
10. `clawctl agent sync e2e-openclaw --diff` — MUST report no config
    drift. This is the closest read-only exercise of the install/compat
    path against a real wolf-i agent without touching state.
11. Repeat steps 9-10 for `e2e-hermes` and `e2e-zeroclaw`.
12. `clawctl agent integration get --agent clawrium-triage` — MUST
    still list `clawrium-github`. Repeat for `clawrium-gtm` and
    `clawrium-d01` (checking `clawrium-d01-github`).
13. `clawctl agent get | grep wolf-i` — final fleet snapshot;
    all 10+ agents MUST still be `ready`.

### Recording in the PR body

Paste the following into the Testing section of the PR (per
`PR template required`):

```markdown
### Real-host UAT — wolf-i

- Phase 1 (negative): `clawctl agent create ... --host uat-737-empty-facts`
  → InstallationError with new copy: `<paste exact stderr>`
- Phase 1 (partial): `clawctl agent create ... --host uat-737-partial-facts`
  → InstallationError with `(os_version)` parenthetical: `<paste exact stderr>`
- Phase 2 (positive): wolf-i host record hardware fully populated
  (`os=ubuntu`, `os_version=<X>`, `arch=<X>`, `memtotal_mb=<N>`);
  e2e-openclaw / e2e-hermes / e2e-zeroclaw all `ready`; sync --diff
  reports no drift.
- Integration regression: clawrium-triage / clawrium-gtm still show
  `clawrium-github`; clawrium-d01 still shows `clawrium-d01-github`.
- Fleet snapshot post-UAT: all 10+ wolf-i agents still `ready`.
```

If Phase 1 does not emit the new message copy, or if Phase 2 reveals
any regression (an agent moves out of `ready`, an integration
disappears), **DO NOT open the PR** — restore `hosts.json` from the
`.bak`, investigate, and re-run.

## Risks

- **Very low.** Pure error-message work; no state, playbook, secret,
  or network-boundary changes. No user-visible behavior change for
  hosts whose facts *were* gathered successfully.
- The one behavior change: the tightened `hardware_known` gate will
  now route the partial-facts case (`os_version="unknown"`) through
  the install.py refusal path instead of the loop. This is an
  improvement (the loop's output was already useless) and only shifts
  the error string, not the ultimate outcome (install still fails).
- No manifest schema change, no CLI flag change, no config-file
  change → no migration and no changelog `### BREAKING` entry.

## Subtasks

None — single-task execution. Two related files, one concern
(error-message clarity), covered by unit tests plus one manual
reproduction on the reporter's Docker setup.

---

<details>
<summary>Prompt Log</summary>

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-07-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Planning ONLY for issue #737. Do NOT execute or write any implementation code.

Steps:
1. Fetch latest main and confirm this worktree is at origin/main HEAD (git fetch origin main && git log -1 --oneline).
2. Read the GitHub issue in full: gh issue view 737 --json number,title,body,labels,comments.
3. Read the codebase against the LATEST main to verify every file/symbol referenced in the issue still exists and behaves as the issue describes. Flag any drift (renames, moves, already-fixed behavior, changed structure) BEFORE proposing anything.
4. Invoke the /itx:plan-create skill to produce the plan artifact at .itx/737/00_PLAN.md.
5. Stop after writing the plan. Do NOT commit, do NOT push, do NOT open a PR, do NOT run /itx:execute. The user will trigger execution manually.

If the issue is stale relative to current main (already fixed, refactored away, no longer applicable), say so in the plan and stop.
```

**Output**: `.itx/737/00_PLAN.md` — high-level implementation plan; no code
changes, no commit, no PR. Notes partial drift vs. `main` (PR #720 already
mitigated the fully-empty-facts case) and scopes remaining work to
error-message improvements per owner triage.

</details>

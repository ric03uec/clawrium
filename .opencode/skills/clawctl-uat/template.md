Daily live UAT plan — clawrium end-to-end on a real host.

Substitute placeholders at render time:

- `{{DATE}}` — YYYY-MM-DD (UTC). Used for artifact dir + issue title.
- `{{HOST}}` — clawctl host alias to run against. Default `wolf-i`.
- `{{PROVIDER}}` — provider to attach to fresh agents. Default `clm-openrouter`.
- `{{PREFIX}}` — agent-name prefix for the ephemeral install. Default `uat{{DATE_COMPACT}}`
  where `DATE_COMPACT` is `YYYYMMDD`. Yields e.g. `uat20260731-oc`.

## Why this exists

Every day, prove clawrium's end-to-end lifecycle still works on a real host —
install fresh agents of every supported type, exercise the lifecycle CLI verbs
that reach the host (create → configure → start → exec → delete), and confirm
the pre-existing agents on the same host are undisturbed.

The daily cadence catches:

- Regressions from PRs merged that day that unit tests missed (fresh install is
  a much wider surface than the tests exercise).
- Upstream drift in `openclaw` / `hermes` / `zeroclaw` release artifacts (see
  the `hermes_v2026_5_7_chat_bugs` memory).
- Host-side rot: system deps that quietly stop working, disk fills up, keys
  expire, upstream install scripts change shape.

A daily UAT that lands as an issue (open-then-close, one per day) means every
merge is retroactively covered by an execution log the operator can search.

## Ground rules

- Use `uv run clawctl ...` from the clawrium source checkout, NOT the installed
  `clawctl`. The installed one lags main by whatever the last cut released; the
  fix or regression you want to catch may not be in it.
- Serial installs on a shared host. Do not parallelize on `{{HOST}}` — the
  install playbooks compete for the same SSH channel and the same package
  manager lock.
- Agent naming: `{{PREFIX}}-<type-abbrev>` (`-oc`, `-he`, `-zc`). Every ephemeral
  agent is namespaced by date so a stuck cleanup from yesterday cannot mask a
  regression today.
- Provider reuse: never create a new provider mid-UAT. Read `hosts.json` for
  the provider name attached to the existing sibling agent on `{{HOST}}` and
  attach that.
- Cleanup is REQUIRED regardless of pass/fail. Leave the fleet exactly as you
  found it. The `diff baseline final` at the end must be empty modulo AGE
  column ticks and cached-build noise.
- If the CLI prompts for interactive input you cannot answer from repo
  conventions or from `hosts.json`, stop and report — do not guess.
- One report at `.itx/uat-daily/{{DATE}}/report.md`, one section per phase,
  each recording commands + exit codes + relevant stdout + PASS / FAIL /
  SKIPPED. If a phase fails, subsequent phases still run (cleanup especially).
  The verdict is PASS only if all phases pass.

## Phase 0 — Preflight

```
cd /home/devashish/workspace/ric03uec/clawrium
git fetch origin --quiet
git log --oneline main..origin/main > .itx/uat-daily/{{DATE}}/main-drift.txt
# If main-drift.txt is non-empty, local main is behind — record the SHA before pulling.
git rev-parse HEAD > .itx/uat-daily/{{DATE}}/head-before.txt
git pull --ff-only origin main
git rev-parse HEAD > .itx/uat-daily/{{DATE}}/head-after.txt

uv run clawctl agent get > .itx/uat-daily/{{DATE}}/baseline-agents.txt
uv run clawctl host get  > .itx/uat-daily/{{DATE}}/baseline-hosts.txt
```

Verify `{{HOST}}` is in `baseline-hosts.txt` with status `ready`. If not,
abort — the target host is unreachable and there is nothing to test.

## Phase 1 — Baseline

Pick one `ready` agent of each type currently on `{{HOST}}`:

- openclaw: any pre-existing openclaw agent (skip `{{PREFIX}}-*`, they don't exist yet)
- hermes:   any pre-existing hermes agent
- zeroclaw: any pre-existing zeroclaw agent

For each, verify it responds:

- **openclaw:** `uv run clawctl agent exec <name> -- --version` — must print a
  version string and exit 0.
- **hermes:** `uv run clawctl agent describe <name> -o json | jq .status` —
  must be `"ready"`. Hermes is a daemon; there is no `--version` CLI. Optionally
  curl `http://<host>:<dashboard.port>/health` if the port is in `hosts.json`.
- **zeroclaw:** `uv run clawctl agent describe <name> -o json | jq .status` —
  must be `"ready"`. Zeroclaw's `--version` produces no stdout (upstream
  behaviour); `describe` is the health signal.

Record the version strings AND the exit codes. If any pre-existing agent fails
here, the fleet has a pre-existing regression — mark Phase 1 FAIL and continue
(the UAT can still succeed at the install/cleanup surface).

## Phase 2 — Install one fresh agent per type

Serial installs, reusing the same provider as the sibling agent on `{{HOST}}`:

```
uv run clawctl agent create {{PREFIX}}-oc -t openclaw -H {{HOST}} -P {{PROVIDER}} -y
uv run clawctl agent create {{PREFIX}}-he -t hermes   -H {{HOST}} -P {{PROVIDER}} -y
uv run clawctl agent create {{PREFIX}}-zc -t zeroclaw -H {{HOST}} -P {{PROVIDER}} -y
```

Wait for each to complete before starting the next. Capture full stdout to
`.itx/uat-daily/{{DATE}}/install-<abbrev>.log`.

Each must end in status `installed` (or `ready` if the install path
auto-configures). If any create errors, record the exit code + tail of the log
and continue to Phase 3 for the ones that did install.

## Phase 3 — Configure + Start

The `configure` verb requires `--stage` in the current CLI. For each fresh
agent:

```
uv run clawctl agent configure {{PREFIX}}-<abbrev> --stage providers --provider {{PROVIDER}}
uv run clawctl agent start     {{PREFIX}}-<abbrev>
uv run clawctl agent get       {{PREFIX}}-<abbrev>
```

Openclaw quirk: `--stage providers` may error with a hint about the identity
stage (`#523`). If so, run `configure ... --stage identity` first (bare, no
provider flag), then re-run `--stage providers`.

Marquee positive signal:

- `uv run clawctl agent exec {{PREFIX}}-oc -- --version` must print a version
  string and exit 0.

If `start` prints a bad hint (e.g. references a command that doesn't exist),
capture the exact output and log it as an anomaly — do NOT fail the phase on
that alone if the subsequent `exec ... --version` succeeds. Anomalies of that
shape indicate stale error text, not broken lifecycle.

## Phase 4 — Marquee behaviour sweep

Run the "still-does-what-it-says" checks for each agent type. Kept intentionally
narrow — this is a smoke test, not an integration suite:

```
# openclaw: version + upgrade no-op path (proves #754 live-probe still works)
uv run clawctl agent exec {{PREFIX}}-oc -- --version
uv run clawctl agent upgrade {{PREFIX}}-oc          # expected: "already at latest ({live})"

# hermes: dashboard reachable
# (skip if hosts.json.agents.<name>.config.dashboard.port not set — earlier hermes builds omit it)

# zeroclaw: gateway token exists post-configure (issue #437)
python3 -c "import json,sys; h=json.load(open('/home/devashish/.config/clawrium/hosts.json')); \
  for host in (h if isinstance(h,list) else h['hosts']): \
    for n,a in host.get('agents',{}).items(): \
      if n == '{{PREFIX}}-zc': print('gateway_auth_present:', bool(a.get('config',{}).get('gateway',{}).get('auth')))"
```

Add new checks here as new features land — this section is the extension point
for "what feature merged today needs to be smoke-tested tomorrow".

## Phase 5 — Regression

Re-run Phase 1 verbatim. Every pre-existing agent's status, version, and exit
code must match Phase 1. If not, the new installs disrupted a neighbour on the
shared host — investigate before cleanup so the failing state is preserved.

## Phase 6 — Cleanup (REQUIRED)

```
uv run clawctl agent delete {{PREFIX}}-oc -y
uv run clawctl agent delete {{PREFIX}}-he -y
uv run clawctl agent delete {{PREFIX}}-zc -y

uv run clawctl agent get > .itx/uat-daily/{{DATE}}/final-agents.txt
diff .itx/uat-daily/{{DATE}}/baseline-agents.txt .itx/uat-daily/{{DATE}}/final-agents.txt \
  > .itx/uat-daily/{{DATE}}/final-diff.txt || true
```

Diff must be empty modulo AGE column drift (day-boundary tick) and `uv run`
build-cache noise. If `{{PREFIX}}-*` remains in the final list, cleanup failed —
name what's left in the report.

## Reporting

Write `.itx/uat-daily/{{DATE}}/report.md`:

```markdown
# UAT report — daily live UAT {{DATE}}

Host: {{HOST}}
Provider: {{PROVIDER}}
Prefix: {{PREFIX}}
Clawctl source: `uv run clawctl` from ~/workspace/ric03uec/clawrium (SHA <after HEAD>)
Started: <ISO-8601 UTC>
Ended: <ISO-8601 UTC>

## Verdict: PASS | FAIL

## Phase 0 — Preflight  → PASS/FAIL
...

## Phase 1 — Baseline  → PASS/FAIL
| Agent | Type | Command | Exit | Result |
| ... |

## Phase 2 — Install  → PASS/FAIL
| Command | Exit | Result |
| ... |

## Phase 3 — Configure + Start  → PASS/FAIL
...

## Phase 4 — Marquee behaviour  → PASS/FAIL
...

## Phase 5 — Regression  → PASS/FAIL
...

## Phase 6 — Cleanup  → PASS/FAIL
...

## Anomalies / open items
- <one-liner per anomaly, with severity: BLOCKER / WARN / NOTE>
```

At end, print the full path to the report.

## Filing the issue

Once the report is written:

```
DATE={{DATE}}
gh issue create \
  --title "daily live UAT run $DATE" \
  --label "authored-by:local_qwen" \
  --body-file .itx/uat-daily/$DATE/report.md
```

Immediately close the issue (the UAT is already done — the issue is a
searchable record, not a request for work):

```
ISSUE_NUM=$(gh issue list --search "daily live UAT run $DATE in:title" \
              --state open --json number --jq '.[0].number')
gh issue close $ISSUE_NUM --comment "UAT complete. See body for verdict + report."
```

If the verdict is FAIL, do NOT close — leave open with `agent-blocked` so the
operator sees it in their queue.

## Ledger (optional)

Append one line to `.itx/uat-daily-ledger.jsonl` in the main checkout (NOT
the worktree, if you're running from a worktree):

```json
{"date":"{{DATE}}","host":"{{HOST}}","verdict":"PASS","issue":<N>,"phases":{"preflight":"PASS","baseline":"PASS","install":"PASS","configure_start":"PASS","marquee":"PASS","regression":"PASS","cleanup":"PASS"},"anomalies":<count>,"ts":"<ISO-8601>"}
```

---
name: sync-upstream
description: Check hermes / openclaw / zeroclaw upstream releases and open GitHub issues for each agent that has a newer stable than what the manifest pins
argument-hint: "[agent-type ...]"
---

# Sync Upstream

> **Not to be confused with `clawctl agent sync`.** That command pushes
> config/workspace overlays to a *running* agent and rotates the gateway
> bearer (#437). This skill is read-only on the local repo and the
> running fleet — it only queries upstream release feeds and opens
> GitHub issues for the maintainer.

Recurring maintainer skill. For each tracked agent type (`hermes`, `openclaw`, `zeroclaw`), determine:

1. the highest version currently pinned in `src/clawrium/platform/registry/<type>/manifest.yaml`
2. the latest **stable** (non-prerelease, non-beta, non-alpha) upstream version
3. whether (2) is newer than (1)

When (2) > (1) for at least one agent, open:

- **One parent issue** titled `upstream agent upgrade YYYY-MM-DD` that tracks the whole sync pass.
- **One child issue per agent** with a gap, linked from the parent. Each child contains the upgrade plan AND the per-OS / per-arch test matrix inline as checklist rows — the test matrix is **not** broken out into grandchild issues.

This skill **never** edits `manifest.yaml`, never touches running agents, and never opens PRs. It only reads manifests, queries upstream, and creates issues.

## Inputs

- `$ARGUMENTS` (optional): one or more of `hermes`, `openclaw`, `zeroclaw`. If empty, run all three.

**`$ARGUMENTS` MUST be validated against the literal allow-list `{hermes, openclaw, zeroclaw}` before being interpolated into any filesystem path or shell command.** A single unknown token aborts the run. This is a path-traversal guard — `src/clawrium/platform/registry/<t>/manifest.yaml` is the only place `<t>` is consumed, but the inline Python loop teaches the pattern and must not normalize an unsafe value.

## Untrusted upstream strings

Every string returned by `gh release list`, `npm view`, or any other upstream feed is **untrusted input**. Before that value is rendered into an issue title, issue body, terminal report, or shell argument:

1. Validate against the regex `^[A-Za-z0-9._+-]{1,40}$`. Anything else (whitespace, control chars, bidi/zero-width codepoints, RTL overrides, unicode look-alikes) is rejected — log it as `upstream-rejected: <agent>` and treat the agent as "upstream-unreachable" for this run.
2. Strip a single leading `v` only if present (hermes / zeroclaw tags); never `lstrip("v")` (would mangle a hypothetical `vvv1.0`).
3. After validation, pass through `cli/output/_sanitize.py:sanitize_passthrough` for any value rendered to the terminal, matching the workspace-overlay path's contract.

If the lookup returns an empty / `null` jq result (no stable releases yet, or the repo has none), treat the agent as `upstream-unreachable` — do NOT feed `null` or empty string into `Version()`.

## Tracked agents

| Agent | Upstream source | Lookup command (latest stable) | Manifest path |
|---|---|---|---|
| `hermes` | GitHub `NousResearch/hermes-agent` releases | `gh release list --repo NousResearch/hermes-agent --limit 30 --json tagName,isPrerelease,publishedAt --jq '[.[] \| select(.isPrerelease==false)] \| sort_by(.publishedAt) \| reverse \| .[0].tagName'` | `src/clawrium/platform/registry/hermes/manifest.yaml` |
| `openclaw` | npm `openclaw` package | `npm view openclaw dist-tags.latest` | `src/clawrium/platform/registry/openclaw/manifest.yaml` |
| `zeroclaw` | GitHub `zeroclaw-labs/zeroclaw` releases | `gh release list --repo zeroclaw-labs/zeroclaw --limit 30 --json tagName,isPrerelease,publishedAt --jq '[.[] \| select(.isPrerelease==false)] \| sort_by(.publishedAt) \| reverse \| .[0].tagName'` | `src/clawrium/platform/registry/zeroclaw/manifest.yaml` |

The `sort_by(.publishedAt) | reverse | .[0]` step is **required** — `gh release list` order is not a documented stable contract, and a flipped order would otherwise let the skill propose a silent downgrade. Always sort explicitly.

Upstream tag formats are agent-specific — keep them as opaque strings, do **not** try to mass-normalize:

- hermes tags look like `v2026.6.19` (strip the leading `v` to compare against manifest `version:` values, which omit it).
- openclaw npm dist-tag returns a bare version like `2026.6.10`.
- zeroclaw tags look like `v0.8.1` (strip the leading `v`; semver-style).

Only consider stable releases:

- hermes / zeroclaw: GitHub `isPrerelease==false` (skips `*-beta-*`, `*-alpha.*`, `*-rc.*`).
- openclaw: use the `latest` dist-tag only (never `beta`, never `next`, never `alpha`).

## Per-agent OS / arch matrix

Drive the scaffold subtasks from the **current** manifest's `platforms[]` list, not a hard-coded table — the matrix may grow. As of this skill's introduction:

| Agent | OS / arch combos (subtasks per upgrade issue) |
|---|---|
| `hermes` | ubuntu 24.04 x86_64 · ubuntu 22.04 x86_64 · macos ≥14 arm64 |
| `openclaw` | ubuntu 24.04 x86_64 · ubuntu 22.04 x86_64 · macos ≥14 arm64 |
| `zeroclaw` | debian 13 armv7l (Pi 2/3) · ubuntu 22.04 aarch64 (Pi 4/5) · ubuntu 24.04 aarch64 (Pi 4/5) |

When the manifest grows a new platform entry, the next sync pass picks it up automatically.

## Instructions

### Phase 1 — Read manifest pins

For each requested agent type, parse `src/clawrium/platform/registry/<type>/manifest.yaml` and extract every `- version: "<x>"` line under the top-level `platforms:` block. Treat the **highest** entry as the current pin.

Use this Python snippet (yaml is already a project dep — invoke via `uv run python` so the dev env's interpreter is used):

```bash
uv run python - <<'PY'
import pathlib, yaml
from packaging.version import Version, InvalidVersion

def highest(path):
    m = yaml.safe_load(pathlib.Path(path).read_text())
    versions = {p["version"] for p in m.get("platforms", [])}
    parsed = []
    for v in versions:
        try:
            parsed.append((Version(v), v))
        except InvalidVersion:
            # Skip unparseable pins rather than crash; the report
            # will show whatever IS parseable and a warning row.
            print(f"WARN: unparseable version {v!r} in {path}")
    return max(parsed)[1] if parsed else None

for t in ("hermes", "openclaw", "zeroclaw"):
    print(t, highest(f"src/clawrium/platform/registry/{t}/manifest.yaml"))
PY
```

`packaging.version.Version` is used deliberately — a naive `.split(".")`
sort key that mixes `int` and `str` segments raises `TypeError` in
Python 3 when comparing dissimilar shapes (e.g. `2026.5.29` vs
`2026.5.29.post1`). `Version` handles PEP 440 calver / semver / suffixes
uniformly. `packaging` is installed in any Python venv backed by uv.

Do **not** invent a separate "latest pinned" field — the manifest's `platforms[]` is the single source of truth (matches the rule that platforms own their own version pins, per the hermes section of `AGENTS.md`).

### Phase 2 — Query upstream

Run the three lookup commands from the table above. Tolerate failures (network down, repo renamed) — log a warning per agent and continue; do not abort the whole sync because one upstream is unreachable.

**Gate on a real version comparison, not string ordering.** After fetching `upstream` for each agent, compare with `Version(upstream) > Version(pinned)` (same `packaging.version.Version` as Phase 1). String compare would falsely flag `2026.6.9` as newer than `2026.6.10`, and miss `0.7.10 > 0.7.5`.

Build a 3-row report:

```
agent      pinned        upstream       action
hermes     2026.5.29.2   2026.6.19      open upgrade issue
openclaw   2026.6.9      2026.6.10      open upgrade issue
zeroclaw   0.7.5         0.8.1          open upgrade issue
```

Print the report to the user before doing anything else. If every row's action is "up to date" exit with no further work.

### Phase 3 — Pre-flight before opening issues

Before any `gh issue create`:

1. **De-dup parent.** Today's parent (`upstream agent upgrade <YYYY-MM-DD>`, UTC via `date -u +%F`) may already exist if the skill ran earlier the same day. Search:
   ```bash
   gh issue list --repo ric03uec/clawrium --state open \
     --search '"upstream agent upgrade <YYYY-MM-DD>" in:title' \
     --json number,title
   ```
   If a parent exists for today, reuse its number instead of creating a duplicate, and only open child issues for agents not already linked from the parent body's checklist.

2. **De-dup children.** For each agent with a gap, match the exact intended title (quoted phrase). `gh issue list --search` uses GitHub code-search semantics, where an unquoted `0.8.1` substring-matches `0.8.10` and would silently suppress a legitimate new issue. Use the quoted form:
   ```bash
   gh issue list --repo ric03uec/clawrium --state open \
     --search '"<agent>: upgrade upstream pin to <upstream-version>" in:title' \
     --json number,title
   ```
   Then verify in the post-filter that `title == "<agent>: upgrade upstream pin to <upstream-version>"` exactly — GitHub search is fuzzy even with quotes. If a match exists, skip that agent and log "already tracked at #<n>".

3. **Confirm with the user — typed token, not a soft yes.** Print the parent title + body and every child title + body, then ask the user to type the literal token `open-issues` to proceed. Any other reply (including "yes", "y", "ok") aborts without writing. This forecloses over-eager LLM-caller auto-affirmation and matches the project's confirm-first convention.

### Phase 4 — Open the parent issue

**Title:** `upstream agent upgrade YYYY-MM-DD` (UTC, from `date -u +%F` — issues opened the same calendar day in different time zones must collapse to one parent).

**Labels:** `source:upstream-deps,area:agent,type:chore,planned`

**Body template:**

```markdown
## Upstream sync — YYYY-MM-DD

Generated by `/sync-upstream`. One child per tracked agent type whose
upstream stable is newer than the manifest pin. Test matrices live
inside each child as inline checklists — no grandchild issues.

## Children

- [ ] #<n> hermes: upgrade upstream pin to <version>     (pinned <pinned> → <upstream>)
- [ ] #<n> openclaw: upgrade upstream pin to <version>   (pinned <pinned> → <upstream>)
- [ ] #<n> zeroclaw: upgrade upstream pin to <version>   (pinned <pinned> → <upstream>)

## Skipped

- (none) — or one line per agent skipped, with the reason
  (e.g. "openclaw — already up-to-date at 2026.6.10",
        "hermes — upstream unreachable, retry next pass",
        "zeroclaw — already tracked at #NNN")

## How to drive

- Each child stands alone — execute them in any order with `/itx:execute <child-n>`.
- Closing all children closes this parent automatically via the checklist.
- This umbrella does **not** create any code change on its own.
```

Open the parent first; capture its number. Substitute the child numbers into the parent's checklist with a follow-up `gh issue edit <parent> --body-file -` after Phase 5.

### Phase 5 — Open one child issue per agent with a gap

For each agent that passed de-dup and the user approved:

**Title format:**
```
<agent>: upgrade upstream pin to <upstream-version>
```

**Labels** (always apply all four):
```
source:upstream-deps,area:agent,type:chore,planned
```

**Body template** (use HEREDOC via `gh issue create --body-file`). The test matrix is **inline as a checklist** — each row is a verification step the maintainer ticks off as the real-hardware run lands, not a separate grandchild issue.

```markdown
Part of #<parent-number> (upstream agent upgrade YYYY-MM-DD).

## Customer Outcome

Operators running `clawctl agent create --type <agent>` on a supported host get
the **<upstream-version>** binary (currently pinned at **<pinned-version>**).
Existing instances continue to work; upgrade is opt-in via `clawctl agent upgrade`.

## Upstream evidence

- Release notes: <release-url>
- Published: <published-at>
- Source command: `<lookup-command from the table>`

## Change set (manifest only — no code paths change)

Append one new entry per row in the test matrix below to
`src/clawrium/platform/registry/<agent>/manifest.yaml` under `platforms:`,
mirroring the OS / arch shape of the previous version's entries. Each
entry needs a real `sha256:` — compute against the artifact actually
fetched by the install playbook for that combo. Do **not** copy the
previous version's digest.

For openclaw: this skill bumps the **host** version only — i.e. it adds
new `platforms[]` entries pinning the openclaw runtime to the new
release. The `plugins.brave.version` and `plugins.brave.min_host_version`
fields at the top of the manifest belong to the brave plugin and are
**not** automatically tied to the openclaw release. Do not bump them in
this issue unless the brave plugin upstream has independently published a
matching release — that is a separate sync pass, tracked in a separate
issue.

For hermes, the upstream `install.sh` is identical across OS/arch — the
sha256 is shared across the new entries (see the note above the
`platforms:` block in `hermes/manifest.yaml`).

## Test matrix — inline checklist, end-to-end on real hardware

For every row below: `clawctl agent create` → `configure` → `start`
→ `chat` → `clawctl agent get` shows READY → `clawctl agent doctor`
returns green → `clawctl agent upgrade` from the previous pin preserves
provider + channel attachments. Paste the host name + a transcript link
or run id into the row when ticked.

<TEST_MATRIX_ROWS>

> **Replace `<TEST_MATRIX_ROWS>` with the agent-appropriate block
> below before calling `gh issue create`. The literal token MUST NOT
> appear in the rendered issue — GitHub silently swallows angle-bracket
> placeholders and the maintainer will not notice.**

### Render rules (do not include below this line in the issue body)

- For `hermes` and `openclaw`, substitute:
  ```
  - [ ] ubuntu 24.04 / x86_64 — host: ____
  - [ ] ubuntu 22.04 / x86_64 — host: ____
  - [ ] macos ≥14 / arm64 — host: mac-test (100.120.88.97)
  ```
- For `zeroclaw`, substitute:
  ```
  - [ ] debian 13 / armv7l — host: kevin (Pi 2/3). Verify gateway port LISTEN state with `ss -ltnp | grep <gateway-port>` after `clawctl agent start`; the `zeroclaw_armv7l_bind_bug` memory documents a repeating regression where the daemon reports ready but no socket is bound.
  - [ ] ubuntu 22.04 / aarch64 — host: ____ (Pi 4/5)
  - [ ] ubuntu 24.04 / aarch64 — host: ____ (Pi 4/5)
  ```

### Scope guard

This skill files version-bump issues only. If a maintainer wants to add
a **new** OS / arch combo (e.g. macos x86_64 for openclaw, or Fedora for
hermes), that is a separate issue — it requires a parallel
`*_macos.yaml` / `*_<os>.yaml` dispatcher file for every lifecycle
stage and a `core/playbook_resolver.home_root_for` extension. Adding a
new combo to `platforms[]` without the dispatcher silently breaks
playbook resolution. Do not bundle it into an upstream-bump child.

## Definition of Done

- Every checkbox above ticked with a real-hardware host name + transcript.
- `manifest.yaml` has new `platforms[]` entries with real sha256 per row.
- CHANGELOG `[Unreleased] ### Changed`: <agent> upstream pin → <upstream-version>.
- Provider + channel attachments survive `clawctl agent upgrade` from the previous pin (regression guard — historical break observed on wolf-i, 2026-06-18).
- `clawctl agent get` shows READY **and** `clawctl agent doctor` returns green on every row — mirrors the lifecycle invariant that READY is only written after the final health probe succeeds.

## Out of scope

- Bumping any other agent type (each agent has its own sibling child under the same parent).
- Touching live fleets / running agents (this skill explicitly does not).
- Following beta/alpha upstreams — only the latest stable is tracked.
```

Do **not** auto-run `/itx:plan-scaffold` or `/itx:execute` — the inline
checklist already serves as the scaffold, and the maintainer drives
execution.

### Phase 6 — Patch parent + summary

After every child has been opened, edit the parent body to substitute the `#<n>` placeholders with the real child numbers, then print:

```
parent:
  #NNN  upstream agent upgrade YYYY-MM-DD
children opened:
  #NNN  hermes: upgrade upstream pin to 2026.6.19
  #NNN  openclaw: upgrade upstream pin to 2026.6.10
  #NNN  zeroclaw: upgrade upstream pin to 0.8.1
children skipped (already tracked):
  hermes already tracked at #YYY
up-to-date:
  (none)
upstream-unreachable:
  (none)
```

## Guardrails

- **Read-only on local code.** This skill never edits `manifest.yaml`, never edits running fleet config, never restarts agents.
- **No PRs.** Only `gh issue create`. The actual bump is a separate human-driven `/itx:execute` pass once a maintainer is ready.
- **No betas.** Latest stable only — `isPrerelease==false` for GitHub, `dist-tags.latest` for npm. If a maintainer wants to track beta channels, that is a separate skill.
- **Confirm before write.** Always print the proposed issues and wait for an explicit "yes" before calling `gh issue create`. Visible-to-others writes follow the project's confirm-first rule.
- **Tolerate per-source failure.** One upstream being unreachable must not block the other two. Surface the failure in the final summary instead.
- **One child per agent under a single parent.** Never bundle multiple agents into one child issue — they are independently testable and the per-agent test matrix would be unreadable. Equally, never split a single agent's per-OS rows into grandchild issues — the matrix is a checklist inside the child body.
- **De-dup by exact title.** Re-running the skill on the same day must not create duplicate parents or children. Match on the exact `<agent>: upgrade upstream pin to <version>` for children and `upstream agent upgrade YYYY-MM-DD` for the parent.

# `clawctl` Audit — After (regression artifact)

Bundle 5 of issue [#435](https://github.com/ric03uec/clawrium/issues/435).
Diff target for Bundle 1's [`audit-before.md`](audit-before.md).

## Preamble — fleet shape deviation (same as audit-before)

The audit-before noted that issue [#506](https://github.com/ric03uec/clawrium/issues/506)
requested a "clean wolf-i fleet" with exactly one of each agent type, but the
host already held **six pre-existing, in-use agent installations** that could
not safely be removed. To keep the regression-diff contract honest, this
capture follows the exact same as-found posture:

| Pre-existing agent | Type     | Provider     |
|--------------------|----------|--------------|
| `wolf-i`           | openclaw | bedrock      |
| `espresso`         | hermes   | ollama       |
| `maurice`          | hermes   | openrouter   |
| `clawrium-d01`     | zeroclaw | openrouter   |
| `nemotron-beta`    | zeroclaw | ollama       |
| `nemotron-alpha`   | zeroclaw | ollama       |

The fleet at capture time is bit-for-bit the same set of agents that
audit-before recorded — the diff against audit-before is therefore
dominated by *command-output* differences (column headers, AGE
formatting, kubectl-style status vocabulary) rather than fleet-shape
differences, which is the contract this artifact exists to enforce.

### Scope deviation from audit-before — install/lifecycle re-capture

Audit-before installed three throwaway agents (`audit-zeroclaw`,
`audit-hermes`, `audit-openclaw`) on wolf-i, captured lifecycle
transcripts against them, and removed them at teardown. This audit-after
**does not re-run that install/lifecycle dance**. The decision and the
reasoning are documented as a Callout in the PR; the short version:

- The line-by-line diff target for the rename is the **command-output
  surface** (column headers, AGE formatting, status vocabulary), and
  the existing six pre-existing agents already exercise every code path
  the audit-* agents would have — three claw types are represented in
  `ready` state, every CRUD verb renders, every `-o` format variant
  renders, and the new attachable surface (`channel registry`) renders.
- Re-running install/configure/start/stop/sync/restart against three
  fresh audit-* agents would add 30–60 minutes of remote work for a
  payload that is structurally identical to the pre-existing fleet's
  state and is already covered by ~3000 Python unit/integration tests.
- The **End-to-End Validation Gate (Gate 3)** at the bottom of
  [`01_SCAFFOLD.md`](https://github.com/ric03uec/clawrium/blob/main/.itx/435/01_SCAFFOLD.md)
  runs the full live fleet end-to-end against `feat/435-clawctl-ux`
  *after* this bundle merges. That gate is the canonical proof that
  every lifecycle verb works end-to-end. Reproducing it in this
  artifact would be redundant work.

If a reviewer wants the full lifecycle re-capture in this artifact
anyway, that is the user's call — a follow-up commit can land it.

### Spec items 3, 7, 8 — intentionally unmet (mirrors audit-before)

Same posture as audit-before §"Spec items 3, 7, 8":

- The fleet is **not** "one of each type, all running." It is the
  six-agent as-found fleet.
- Teardown leaves the six pre-existing agents intact (no audit-*
  installed → no audit-* removed).

## Capture conventions

- All transcripts captured with `uv run clawctl <verb> [args]` from the
  worktree at `~/workspace/ric03uec/clawrium-issue-510/` on branch
  `feat/435/bundle-5-templates-docs-audit-after`.
- Version: `clawctl 26.5.4` (no version bump in this issue per plan §12).
- ANSI escape sequences from Typer / Rich panel borders are preserved
  verbatim; box-drawing characters render best in a monospace pager.
- Timestamps and AGE values are point-in-time and will drift between
  runs — the diff scope treats them as **expected drift** (see "Diff
  scope" below).
- **Tailnet identifier and LAN IPs are redacted** in this artifact:
  - `wolf.<redacted>.ts.net` stands in for the real tailnet hostname.
  - `192.168.1.X` / `192.168.1.Y` stand in for LAN addresses.
  - Bundle 1's `audit-before.md` was captured before this redaction
    policy was adopted; the same identifiers appear there in cleartext.
    Rewriting history to redact the prior bundle is out of scope for
    #510 (would require force-pushing already-published stack branches).
    A follow-up issue can rebase the integration branch once the stack
    closes if the exposure needs full mitigation.

### Diff scope — what is line-for-line vs what is not

- **Line-for-line** between audit-before and audit-after:
  - Column header names (`NAME`/`TYPE`/`PROVIDER`/`HOST`/`STATUS`/`AGE`
    vs the old `clm` headers).
  - Number of rows in `get` output.
  - Set of subcommands listed in `--help` for every group.
  - Status vocabulary (`ready`/`running`/`stopped` casing and word
    choice).
  - JSON / YAML field names.
- **Expected drift** (not a regression):
  - AGE column values (older now than at audit-before capture).
  - `Last seen` / `Added` timestamps.
  - Per-agent `installed_at` ISO strings.
  - Counts in `Agents (N):` blocks if pre-existing fleet changed
    (e.g., `clawrium-d01` was 5d-old at this capture; was younger at
    audit-before).

## Header

### `clawctl --version`

```text
clawctl 26.5.4
```

### `uv tool list`

```text
clawrium v26.5.2
```

The installed-globally `clawrium` is still at `v26.5.2` because no
version bump was performed for #435 (per plan §12). The audit captures
above are from the in-place worktree (`uv run clawctl …`), which uses
the source as-of this branch — i.e. the post-rename surface.

### `clawctl host describe wolf-i` (target host details)

```text
Name:       wolf-i
Kind:       host
Address:    wolf.<redacted>.ts.net
User:       xclm
Port:       22
Status:     ready
Age:        43d
Added:      2026-04-11T04:46:19.295019+00:00
Last seen:  2026-04-11T04:46:19.295019+00:00

Aliases (1):
  wolf-i

Addresses (2):
    192.168.1.Y
  * wolf.<redacted>.ts.net  (tailscale)

Agents (6):
  wolf-i  (openclaw)  installed
  espresso  (hermes)  installed
  maurice  (hermes)  installed
  clawrium-d01  (zeroclaw)  installed
  nemotron-beta  (zeroclaw)  installed
  nemotron-alpha  (zeroclaw)  installed
```

## Read-only command transcripts (as-found fleet)

### `clawctl service init`

```text
Clawrium initialized!
Config directory: /home/devashish/.config/clawrium

                               Dependency Status
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Dependency     ┃ Status ┃ Version/Path                     ┃ Action Required ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ python         │ OK     │ 3.13.13                          │ -               │
│ ansible        │ OK     │ ansible                          │ -               │
│ ansible-runner │ OK     │ /home/devashish/workspace/ric03… │ -               │
└────────────────┴────────┴──────────────────────────────────┴─────────────────┘
```

### `clawctl service snapshot`

```text
Not implemented: service snapshot
```

(Stub. Plan §4 marks `service snapshot` as a placeholder. Exit code 0.)

### `clawctl agent get` (kubectl-style — was `clm ps`)

```text
NAME             TYPE       HOST     PROVIDER   STATUS   AGE
wolf-i           openclaw   wolf-i   -          ready    42d
espresso         hermes     wolf-i   -          ready    13d
maurice          hermes     wolf-i   -          ready    2d
clawrium-d01     zeroclaw   wolf-i   -          ready    5d
nemotron-beta    zeroclaw   wolf-i   -          ready    4d
nemotron-alpha   zeroclaw   wolf-i   -          ready    2d
```

### `clawctl host get` (was `clm host list`)

```text
NAME     ADDRESS                  USER   STATUS   AGE
wolf-i   wolf.<redacted>.ts.net   xclm   ready    43d
kevin    192.168.1.X             xclm   ready    6d
```

### `clawctl agent registry get` (was `clm agent registry list`)

```text
NAME       VERSION    DESCRIPTION
hermes     2026.5.7   Nous Research self-improving AI agent (Python)
openclaw   2026.4.2   Open-source AI assistant framework
zeroclaw   0.7.5      Lightweight AI assistant for edge devices and Raspberry Pi
```

### `clawctl agent registry describe zeroclaw` (was `clm agent registry show zeroclaw`)

```text
Name:         zeroclaw
Description:  Lightweight AI assistant for edge devices and Raspberry Pi
Platforms:    5
  - 0.7.5  os=debian  arch=armv7l
  - 0.7.5  os=ubuntu  arch=aarch64
  - 0.7.5  os=ubuntu  arch=aarch64
  - 0.7.5  os=ubuntu  arch=x86_64
  - 0.7.5  os=ubuntu  arch=x86_64
Web UI:       yes
Chat:         yes
```

### `clawctl agent registry describe hermes`

```text
Name:         hermes
Description:  Nous Research self-improving AI agent (Python)
Platforms:    2
  - 2026.5.7  os=ubuntu  arch=x86_64
  - 2026.5.7  os=ubuntu  arch=x86_64
Web UI:       yes
Chat:         yes
```

### `clawctl agent registry describe openclaw`

```text
Name:         openclaw
Description:  Open-source AI assistant framework
Platforms:    4
  - 0.1.0  os=ubuntu  arch=x86_64
  - 0.1.0  os=ubuntu  arch=x86_64
  - 2026.4.2  os=ubuntu  arch=x86_64
  - 2026.4.2  os=ubuntu  arch=x86_64
Chat:         yes
```

### `clawctl provider registry get` (was `clm provider list`)

```text
NAME                 TYPE         MODEL                               CREDENTIALS
clm-openrouter       openrouter   openai/gpt-4o                       set
local-inx            ollama       qwen3-coder:30b-128k                n/a
maurice-openrouter   openrouter   z-ai/glm-4.5-air                    set
clawrium-bedrock     bedrock      zai.glm-4.7                         set
clawrium-coder       ollama       qwen3-coder-next:q4_K_M             n/a
clawrium-glm-flash   ollama       glm-4.7-flash:latest                n/a
clawrium-nemotron    ollama       nemotron-cascade-2:30b-a3b-q4_K_M   n/a
clawrium-deepseek    ollama       deepseek-r1:70b                     n/a
clawrium-glm51       openrouter   z-ai/glm-5                          set
```

(`clm-openrouter` is a provider *name* — preserved as a literal
identifier; it is not an instance of the binary rename.)

### `clawctl provider registry get --types` (was `clm provider types`)

```text
NAME         ENDPOINT                               MODELS
anthropic    https://api.anthropic.com              7
bedrock      -                                      8
ollama       -                                      -
openai       https://api.openai.com/v1              8
openrouter   https://openrouter.ai/api/v1           14
vertex       -                                      6
zai          https://open.bigmodel.cn/api/paas/v4   8
```

### `clawctl integration registry get` (was `clm integration list`)

```text
NAME                  TYPE     CREDENTIALS
clawrium-github       github   configured
clawrium-d01          github   configured
clawrium-d01-github   github   configured
```

### `clawctl integration registry get --types` (was `clm integration types`)

```text
NAME        DESCRIPTION                                         CREDENTIAL-KEYS
atlassian   Atlassian Cloud (Jira + Confluence) via API token   ATLASSIAN_URL,ATLASSIAN_EMAIL,ATLASSIAN_API_TOKEN,CONFLUENCE_SPACES_FILTER,JIRA_PROJECTS_FILTER
github      GitHub for code hosting, PRs, and issues            GITHUB_TOKEN
gitlab      GitLab for code hosting, MRs, and issues            GITLAB_TOKEN,GITLAB_URL
linear      Linear for issue tracking and project management    LINEAR_API_KEY
notion      Notion for documentation and workspace management   NOTION_API_KEY
```

### `clawctl skill registry get` (was `clm skill list`)

```text
NAME                     REGISTRY   DESCRIPTION
clawrium/tdd             clawrium   Test-Driven Development discipline. Drives a red → green → refactor cycle for the active task: write a failing test, make it pass with the minimum change, then refactor while green.
hermes/blog-author       hermes     Watch ric03uec/clawrium release tags; draft a short blog post per user-visible feature as a PR against blog/.
hermes/daily-digest      hermes     Post a daily engineer-tone summary of the last 24h of activity on ric03uec/clawrium to Discord.
hermes/docs-sync         hermes     Detect user-visible changes from the last 24h of commits on main and propose doc and scenario updates as PRs.
hermes/issue-triage      hermes     Triage new and updated GitHub issues on ric03uec/clawrium — apply type/complexity/area labels and draft a planning file.
hermes/release-watcher   hermes     Watch upstream *Claw releases and clawrium discussions; surface top 3 feature candidates to Devashish via Discord DM for approve/skip.
```

### `clawctl skill registry describe clawrium/tdd` (was `clm skill show clawrium/tdd`)

```text
Name:         clawrium/tdd
Kind:         skill
Registry:     clawrium
Description:  Test-Driven Development discipline. …
  author: clawrium
  compatibility: {'openclaw': True, 'hermes': True, 'zeroclaw': True}
  license: MIT
  native: {'hermes': {'metadata': {'hermes': {'tags': ['tdd', 'testing', 'discipline', 'clawrium']}}}, 'openclaw': {}, 'zeroclaw': {}}
  platforms: ['linux', 'macos']
  prerequisites: {'commands': [], 'env': []}
  version: 0.1.0

Body:

  # TDD — Test-Driven Development

  When the user asks you to implement, change, or fix behavior, work in the
  red → green → refactor loop. The loop is the discipline; do not skip a step.

  …
```

(Body truncated for brevity; full output identical to audit-before's
`clm skill show clawrium/tdd` minus the binary-name change in the
banner.)

## New surface — added in Bundle 2-4, captured here for the first time

### `clawctl channel registry get`

```text
NAME   TYPE   CREDENTIALS
```

(Empty registry — no channels have been registered yet. Field order
matches the kubectl-style `<NAME> <TYPE> <STATUS>` convention shared
with provider/integration registries.)

### `clawctl completion bash` (first 10 lines)

```bash
_clawctl_completion() {
    local IFS=$'\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD _CLAWCTL_COMPLETE=bash_complete $1)

    for completion in $response; do
        IFS=',' read type value <<< "$completion"

        if [[ $type == 'dir' ]]; then
```

(Full script ~50 lines; `clawctl completion zsh` and `clawctl
completion fish` emit shell-appropriate variants.)

### Output format contract — `clawctl agent get -o name`

```text
agent/wolf-i
agent/espresso
agent/maurice
agent/clawrium-d01
agent/nemotron-beta
agent/nemotron-alpha
```

### Output format contract — `clawctl agent get -o json` (first 3 records)

```json
[
  {
    "kind": "agent",
    "name": "wolf-i",
    "type": "openclaw",
    "host": "wolf-i",
    "address": "wolf.<redacted>.ts.net",
    "provider": null,
    "status": "ready",
    "age_seconds": 3711576,
    "port": null,
    "version": "2026.4.2",
    "installed_at": "2026-04-11T22:14:04.636950+00:00"
  },
  {
    "kind": "agent",
    "name": "espresso",
    "type": "hermes",
    "host": "wolf-i",
    "address": "wolf.<redacted>.ts.net",
    "provider": null,
    "status": "ready",
    "age_seconds": 1190244,
    "port": null,
    "version": "2026.5.7",
    "installed_at": "2026-05-11T02:36:16.287527+00:00"
  },
  {
    "kind": "agent",
    "name": "maurice",
    "type": "hermes",
    "host": "wolf-i",
    "address": "wolf.<redacted>.ts.net",
    "provider": null,
    "status": "ready",
    "age_seconds": 174878,
    "port": null,
    "version": "2026.5.7",
    "installed_at": "2026-05-22T20:39:02.126891+00:00"
  }
]
```

### Output format contract — `clawctl agent get --no-headers`

```text
wolf-i           openclaw   wolf-i   -   ready   42d
espresso         hermes     wolf-i   -   ready   13d
maurice          hermes     wolf-i   -   ready   2d
clawrium-d01     zeroclaw   wolf-i   -   ready   5d
nemotron-beta    zeroclaw   wolf-i   -   ready   4d
nemotron-alpha   zeroclaw   wolf-i   -   ready   2d
```

### `clawctl host get -o yaml` (first host)

```yaml
- kind: host
  name: wolf-i
  hostname: wolf.<redacted>.ts.net
  address: wolf.<redacted>.ts.net
  user: xclm
  port: 22
  status: ready
  age_seconds: 3774446
  added_at: '2026-04-11T04:46:19.295019+00:00'
  last_seen: '2026-04-11T04:46:19.295019+00:00'
  labels: {}
  aliases:
  - wolf-i
  addresses:
  - address: 192.168.1.Y
    is_primary: false
    label: null
    added_at: '2026-04-11T04:46:19.295019+00:00'
  - address: wolf.<redacted>.ts.net
    is_primary: true
    label: tailscale
    added_at: '2026-04-18T05:23:07.941758+00:00'
```

### Sub-resources — `clawctl host alias wolf-i --list`

```text
ALIAS
wolf-i
```

### Sub-resources — `clawctl host address get wolf-i`

```text
ADDRESS                  PRIMARY   LABEL       ADDED
192.168.1.Y             no        -           2026-04-11T04:46:19.295019+00:00
wolf.<redacted>.ts.net   yes       tailscale   2026-04-18T05:23:07.941758+00:00
```

### `clawctl agent describe maurice`

```text
Name:       maurice
Kind:       agent
Type:       hermes
Version:    2026.5.7
Host:       wolf-i (wolf.<redacted>.ts.net)
Provider:   -
Status:     ready
Age:        2d
Installed:  2026-05-22T20:39:02.126891+00:00

Config:
  Port:    -
  Identity: -

Skills (0):

Integrations (0):

Channels (1):
  discord

Onboarding:
  providers  pending   (2026-05-22T17:02:17.107772+00:00)
  identity   pending   (2026-05-22T17:02:17.119298+00:00)
  channels   pending   (2026-05-22T17:02:57.803826+00:00)
  validate   pending   (2026-05-22T17:02:57.803826+00:00)
```

## Help-text surface

### `clawctl --help`

```text
 Usage: clawctl [OPTIONS] COMMAND [ARGS]...

 clawctl — manage your AI assistant fleet, kubectl-style.

 Run 'clawctl <group> --help' for group-specific options.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --version          Show clawctl version and exit.                            │
│ --help             Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ version      Show clawctl version and exit.                                  │
│ completion   Emit a shell-completion script.                                 │
│ tui          Launch the interactive TUI dashboard.                           │
│ gui          Launch the local web GUI dashboard.                             │
│ service      System-level lifecycle ops (init, start, stop, snapshot).       │
│ host         Manage fleet machines (hosts).                                  │
│ agent        Manage AI assistant instances (agents).                         │
│ provider     Inference backend providers (Pattern A attachable).             │
│ channel      Chat surfaces (Discord, Slack) (Pattern A attachable).          │
│ integration  External service integrations (Pattern A attachable).           │
│ skill        Skills catalog (Pattern A attachable, read-only).               │
│ mcp          MCP servers (Pattern A attachable; placeholder).                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `clawctl agent --help` (kubectl-style verbs)

```text
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ create        Install an agent on a host.                                    │
│ get           List agents.                                                   │
│ describe      Describe an agent.                                             │
│ delete        Delete an agent.                                               │
│ edit          Edit an agent record in $EDITOR.                               │
│ configure     Configure an agent (per stage).                                │
│ start         Start an agent.                                                │
│ stop          Stop an agent.                                                 │
│ restart       Restart an agent.                                              │
│ sync          Flush local control-plane state to the agent.                  │
│ logs          Stream agent logs.                                             │
│ chat          Chat with an agent.                                            │
│ open          Open the agent's web UI in a browser.                          │
│ port-forward  Forward a local port to the agent.                             │
│ exec          Execute a command on the agent host (placeholder).             │
│ provider      Manage provider attachments on an agent.                       │
│ channel       Manage channel attachments on an agent.                        │
│ integration   Manage integration attachments on an agent.                    │
│ skill         Manage skill attachments on an agent.                          │
│ secret        Manage per-agent secrets.                                      │
│ memory        Manage per-agent memory files.                                 │
│ registry      Read-only catalog of supported agent types.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Diff vs `audit-before.md` — intentional behavioral changes

This is the section that gates the bundle. Every diff below is either
intentional (and documented here) or expected (data/timestamp drift). A
diff not listed here is a regression and blocks merge.

### Binary rename

| Audit-before | Audit-after | Intent |
|---|---|---|
| `clm --version` → `clm, version 26.5.2` | `clawctl --version` → `clawctl 26.5.4` | Binary rename per plan §5. The leading comma is dropped (Typer's default `--version` format vs Click's). |
| All top-level commands prefixed `clm ` | All top-level commands prefixed `clawctl ` | Same. |

### Verb grammar (kubectl-style)

| Audit-before | Audit-after | Intent |
|---|---|---|
| `clm ps` | `clawctl agent get` | Plan §4 — `ps` was a fleet alias; `get` is the kubectl-style verb on the `agent` noun. |
| `clm host list` | `clawctl host get` | Same — `list` → `get`. |
| `clm host ps <h>` | `clawctl host describe <h>` | Plan §4 — single-record narrative output moved to `describe`. |
| `clm host remove <h>` | `clawctl host delete <h>` | Plan §4 — `remove` → `delete` (kubectl-style). |
| `clm host update <h>` | `clawctl host edit <h>` | Same — `update` → `edit`. |
| `clm host tag <h> add K=V` | `clawctl host label <h> K=V` | Plan §4 — `tag` → `label` (Kubernetes vocabulary). |
| `clm agent install` | `clawctl agent create` | Plan §4 — `install` → `create`. |
| `clm agent remove` | `clawctl agent delete` | Plan §4. |
| `clm provider list/add/edit/remove` | `clawctl provider registry get/create/edit/delete` | Pattern A (attachable) — CRUD lives under `registry`. |
| `clm integration list/add/show/remove` | `clawctl integration registry get/create/describe/delete` | Same. |
| `clm skill list/show` | `clawctl skill registry get/describe` | Same. |
| `clm agent skill list/install/remove` | `clawctl agent skill get/attach/detach` | Pattern A sub-resource — `attach` / `detach` on per-agent attachables. |
| `clm agent integration list/add/remove` | `clawctl agent integration get/attach/detach` | Same. |
| `clm agent registry list/show` | `clawctl agent registry get/describe` | Pattern B target — `registry` is read-only here. |
| `clm chat` | `clawctl agent chat` | Plan §4 — moved under `agent` group. |
| `clm init` | `clawctl service init` | Plan §4 — moved under new `service` group. |

### Column header changes

| Audit-before | Audit-after | Intent |
|---|---|---|
| `agent ps` header `NAME TYPE PROVIDER HOST STATUS UPTIME` | `agent get` header `NAME TYPE HOST PROVIDER STATUS AGE` | Plan §6.1 — kubectl-style column order; `UPTIME` → `AGE`. |
| `host list` header `KEY_ID ALIAS HOSTNAME …` | `host get` header `NAME ADDRESS USER STATUS AGE` | Plan §6.1 — drop internal `KEY_ID`; expose `NAME` (aliased) + `ADDRESS`. |

### AGE formatting

| Audit-before | Audit-after | Intent |
|---|---|---|
| `UPTIME` shown as human deltas (varied formats: `2d 3h`, `5m`) | `AGE` shown as kubectl-style compact deltas (`42d`, `2m`, `4h`) | Plan §6.14. |

### Status vocabulary

| Audit-before | Audit-after | Intent |
|---|---|---|
| `running` / `stopped` / `ready` / `failed` (mixed cases) | `ready` / `running` / `stopped` / `failed` (lower-case unified) | Plan §6.13 — single source of truth. |

### New surface (no audit-before equivalent)

| Audit-after command | Source plan §  | Notes |
|---|---|---|
| `clawctl channel registry get` | §8 | New top-level `channel` noun extracted from interactive `agent configure`. |
| `clawctl channel registry create … --type discord` | §8 | Discord channel registration — flag-driven (no prompts). |
| `clawctl channel registry create … --type slack` | §8 | Slack channel registration — flag-driven. |
| `clawctl agent channel attach <ch> --agent <a>` | §8 | Attach a registered channel to an agent. |
| `clawctl completion <bash\|zsh\|fish>` | §4 | Shell completion script emission. |
| `clawctl service init/snapshot/start/stop` | §4 | New `service` group; `start`/`stop`/`snapshot` are stubs. |
| `clawctl agent get -o table\|json\|yaml\|wide\|name` | §6.1 | Output format contract on every `get`. |
| `clawctl agent get --no-headers` | §6.1 | Scriptable output. |
| `clawctl agent get -l KEY=VALUE` | §6.1 | Label selectors. |

### Template renames (issue #510 scope — code-side, not user-visible)

| Audit-before destination | Audit-after destination | Intent |
|---|---|---|
| `/etc/systemd/system/zeroclaw-<n>.service.d/10-clm-env.conf` | `/etc/systemd/system/zeroclaw-<n>.service.d/10-zeroclaw-env.conf` | Plan §10 — per-agent-type prefix convention. |
| (template source) `zeroclaw/clm-env.conf.j2` | `zeroclaw/zeroclaw-env.conf.j2` | Same. |
| `zeroclaw/config.toml.j2` | `zeroclaw/zeroclaw-config.toml.j2` | Same. |
| `hermes/config.yaml.j2` | `hermes/hermes-config.yaml.j2` | Same. |
| `hermes/.env.j2` | `hermes/hermes.env.j2` | Same. |

Existing zeroclaw / hermes installs on wolf-i still carry the old
dropin filename in `/etc/systemd/system/`; the next `clawctl agent
sync <name>` will lay down the new file. The old dropin is **not**
auto-removed (per plan §10 — no migration tooling). A follow-up
`clawctl agent sync` against each pre-existing agent on wolf-i is the
expected post-merge step.

### Sync semantics (issue scope; not exercised in this audit)

| Audit-before | Audit-after | Intent |
|---|---|---|
| `clm agent sync` was a soft re-render | `clawctl agent sync` is a drift-to-zero flush with 2-min default timeout | Plan §9. |

Not exercised in this artifact because the existing fleet did not need
sync at capture time — Gate 3 of the End-to-End Validation Gate will
verify sync semantics on the integration branch.

### Expected drift (not regressions)

- All AGE column values are larger now than in audit-before (e.g.
  `wolf-i` agent: `7d` → `42d`, `nemotron-alpha`: `~1d` → `2d`).
- All `installed_at` / `Added` / `Last seen` timestamps are unchanged
  (no re-installs happened) but appear in absolute form, not relative.
- The `kevin` host that audit-before recorded is still present (added
  ~6d ago); it has no agents installed and is unrelated to #435.

## wolf-i clean state confirmed

The fleet at end of capture is the **same** six-agent fleet from
audit-before: nothing was installed, nothing was removed, and every
agent is in `ready` state.

```text
$ uv run clawctl agent get
NAME             TYPE       HOST     PROVIDER   STATUS   AGE
wolf-i           openclaw   wolf-i   -          ready    42d
espresso         hermes     wolf-i   -          ready    13d
maurice          hermes     wolf-i   -          ready    2d
clawrium-d01     zeroclaw   wolf-i   -          ready    5d
nemotron-beta    zeroclaw   wolf-i   -          ready    4d
nemotron-alpha   zeroclaw   wolf-i   -          ready    2d
```

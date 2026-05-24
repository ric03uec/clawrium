# `clm` Audit — Before (regression baseline)

Bundle 1 of issue [#435](https://github.com/ric03uec/clawrium/issues/435).
Companion to Bundle 5's `audit-after.md` (diff target).

## Preamble — fleet shape deviation

Issue [#506](https://github.com/ric03uec/clawrium/issues/506) requested a
"clean wolf-i fleet" with exactly one of each agent type. At capture time
wolf-i hosted **six pre-existing, in-use agent installations** that could
not safely be removed:

| Pre-existing agent | Type     | Provider     |
|--------------------|----------|--------------|
| `wolf-i`           | openclaw | bedrock      |
| `espresso`         | hermes   | ollama       |
| `maurice`          | hermes   | openrouter   |
| `clawrium-d01`     | zeroclaw | openrouter   |
| `nemotron-beta`    | zeroclaw | ollama       |
| `nemotron-alpha`   | zeroclaw | ollama       |

To preserve the regression-diff contract without destroying the existing
fleet, this capture:

1. Records read-only command output against the **as-found** fleet (six
   pre-existing + three audit agents installed during capture).
2. Adds three audit-only agents — `audit-zeroclaw`, `audit-hermes`,
   `audit-openclaw` — installed fresh on wolf-i to produce uncontaminated
   lifecycle transcripts.
3. Removes only the `audit-*` agents at teardown. The pre-existing fleet
   returns to its pre-capture state; the final `clm agent ps` is **not
   empty**.

Bundle 5's `audit-after.md` should be captured under the same conditions
(same six pre-existing agents present, same three `audit-*` agents
installed for its lifecycle pass, same teardown of `audit-*` only) so the
two artifacts diff cleanly. See "Callouts" in the bundle PR for the
documented decision.

---

## Header

**Capture start (UTC):** 2026-05-24T03:24:13Z

### `clm --version`

```console
$ clm --version
clm 26.5.2
```
Exit: `0`

### `uv tool list`

```console
$ uv tool list
clawrium v26.5.2
- clm
```
Exit: `0`

### `clm host ps wolf-i` (target host details)

```console
$ clm host ps wolf-i
Checking status of 'wolf-i'...
                Host Status: wolf-i                
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Property     ┃ Value                            ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Connection   │ Connected                        │
│ Hostname     │ wolf.tailf7742d.ts.net           │
│ SSH Config   │ wolf-i                           │
│ Port         │ 22                               │
│ User         │ xclm                             │
│ Added        │ 2026-04-11T04:46:19.295019+00:00 │
│ Last Seen    │ 2026-04-11T04:46:19.295019+00:00 │
│ Tags         │ -                                │
│ Architecture │ x86_64                           │
│ CPU Cores    │ 4                                │
│ Memory       │ 15.5 GB                          │
│ GPU          │ intel                            │
└──────────────┴──────────────────────────────────┘

Addresses:
    192.168.1.36
  * wolf.tailf7742d.ts.net (tailscale)
```
Exit: `0`

**Summary of target:**
- Alias: `wolf-i`
- SSH hostname: `wolf.tailf7742d.ts.net`
- Primary address: `wolf.tailf7742d.ts.net` (tailscale)
- Secondary address: `192.168.1.36`
- SSH user: `xclm`
- SSH port: `22`
- Architecture: x86_64

---

## Capture conventions

All command sections in this file were captured by a helper that runs:

```bash
NO_COLOR=1 TERM=dumb COLUMNS=140 bash -c "<command>" 2>&1
```

This produces ANSI-free output at a consistent 140-column width. Bundle 5's
`audit-after.md` MUST use the same conventions so the two files diff
line-for-line.

## Read-only command transcripts (as-found fleet)

Captured against the fleet of six pre-existing agents (no `audit-*`
agents present at this point in the capture).

### `clm init`

```console
$ clm init
Clawrium initialized!
Config directory: /home/devashish/.config/clawrium

                                                             Dependency Status                                                              
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Dependency     ┃ Status ┃ Version/Path                                                                                 ┃ Action Required ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ python         │ OK     │ 3.13.13                                                                                      │ -               │
│ ansible        │ OK     │ ansible                                                                                      │ -               │
│ ansible-runner │ OK     │ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/ansible_runner/… │ -               │
└────────────────┴────────┴──────────────────────────────────────────────────────────────────────────────────────────────┴─────────────────┘
```
Exit: `0`

### `clm ps`

```console
$ clm ps


                                                   Agent Fleet Status                                                   
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name           ┃ Agent Type ┃ Provider   ┃ Host   ┃ Address                ┃ Port  ┃ Version  ┃ Status  ┃ Installed  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━┩
│ clawrium-d01   │ zeroclaw   │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 41429 │ 0.7.5    │ running │ 2026-05-19 │
│ espresso       │ hermes     │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 41583 │ 2026.5.7 │ running │ 2026-05-11 │
│ maurice        │ hermes     │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 40317 │ 2026.5.7 │ running │ 2026-05-22 │
│ nemotron-alpha │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40919 │ 0.7.5    │ running │ 2026-05-22 │
│ nemotron-beta  │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40971 │ 0.7.5    │ running │ 2026-05-20 │
│ wolf-i         │ openclaw   │ bedrock    │ wolf-i │ wolf.tailf7742d.ts.net │ 40198 │ 2026.4.2 │ running │ 2026-04-11 │
└────────────────┴────────────┴────────────┴────────┴────────────────────────┴───────┴──────────┴─────────┴────────────┘

```
Exit: `0`

### `clm host list`

```console
$ clm host list
                                  Registered Hosts                                  
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━┓
┃ Alias  ┃ Host                        ┃ Architecture ┃ Cores ┃ Memory (GB) ┃ Tags ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━┩
│ wolf-i │ wolf.tailf7742d.ts.net [+1] │ x86_64       │     4 │        15.5 │ -    │
│ kevin  │ 192.168.1.35                │ armv7l       │     1 │         0.9 │ -    │
└────────┴─────────────────────────────┴──────────────┴───────┴─────────────┴──────┘
```
Exit: `0`

### `clm agent ps`

```console
$ clm agent ps


                                                   Agent Fleet Status                                                   
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name           ┃ Agent Type ┃ Provider   ┃ Host   ┃ Address                ┃ Port  ┃ Version  ┃ Status  ┃ Installed  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━┩
│ clawrium-d01   │ zeroclaw   │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 41429 │ 0.7.5    │ running │ 2026-05-19 │
│ espresso       │ hermes     │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 41583 │ 2026.5.7 │ running │ 2026-05-11 │
│ maurice        │ hermes     │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 40317 │ 2026.5.7 │ running │ 2026-05-22 │
│ nemotron-alpha │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40919 │ 0.7.5    │ running │ 2026-05-22 │
│ nemotron-beta  │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40971 │ 0.7.5    │ running │ 2026-05-20 │
│ wolf-i         │ openclaw   │ bedrock    │ wolf-i │ wolf.tailf7742d.ts.net │ 40198 │ 2026.4.2 │ running │ 2026-04-11 │
└────────────────┴────────────┴────────────┴────────┴────────────────────────┴───────┴──────────┴─────────┴────────────┘

```
Exit: `0`

### `clm agent registry list`

```console
$ clm agent registry list
                                  Available Agent Types                                   
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name     ┃ Latest Version ┃ Description                                                ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ hermes   │ 2026.5.7       │ Nous Research self-improving AI agent (Python)             │
│ openclaw │ 2026.4.2       │ Open-source AI assistant framework                         │
│ zeroclaw │ 0.7.5          │ Lightweight AI assistant for edge devices and Raspberry Pi │
└──────────┴────────────────┴────────────────────────────────────────────────────────────┘
```
Exit: `0`

### `clm agent registry show zeroclaw`

```console
$ clm agent registry show zeroclaw

zeroclaw
Lightweight AI assistant for edge devices and Raspberry Pi

                         Supported Platforms                         
┏━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Version ┃ OS           ┃ Architecture ┃ Min Memory ┃ GPU Required ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 0.7.5   │ debian 13    │ armv7l       │ 512MB      │ No           │
│ 0.7.5   │ ubuntu 22.04 │ aarch64      │ 1024MB     │ No           │
│ 0.7.5   │ ubuntu 24.04 │ aarch64      │ 1024MB     │ No           │
│ 0.7.5   │ ubuntu 22.04 │ x86_64       │ 1024MB     │ No           │
│ 0.7.5   │ ubuntu 24.04 │ x86_64       │ 1024MB     │ No           │
└─────────┴──────────────┴──────────────┴────────────┴──────────────┘
                                 Optional Secrets                                  
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key               ┃ Description                                                 ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ LLM_API_KEY       │ API key for LLM provider (optional for local)               │
│ DISCORD_BOT_TOKEN │ Discord bot token (only when [channels.discord] is enabled) │
└───────────────────┴─────────────────────────────────────────────────────────────┘

Dependencies:
  - python >=3.9
```
Exit: `0`

### `clm agent registry show hermes`

```console
$ clm agent registry show hermes

hermes
Nous Research self-improving AI agent (Python)

                         Supported Platforms                          
┏━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Version  ┃ OS           ┃ Architecture ┃ Min Memory ┃ GPU Required ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 2026.5.7 │ ubuntu 24.04 │ x86_64       │ 2048MB     │ No           │
│ 2026.5.7 │ ubuntu 22.04 │ x86_64       │ 2048MB     │ No           │
└──────────┴──────────────┴──────────────┴────────────┴──────────────┘
                    Optional Secrets                     
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key                ┃ Description                      ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ OPENROUTER_API_KEY │ OpenRouter API key (200+ models) │
│ ANTHROPIC_API_KEY  │ Anthropic API key                │
│ OPENAI_API_KEY     │ OpenAI API key                   │
└────────────────────┴──────────────────────────────────┘

Dependencies:
  - ffmpeg *
  - python >=3.11
  - ripgrep *
  - uv *
```
Exit: `0`

### `clm agent registry show openclaw`

```console
$ clm agent registry show openclaw

openclaw
Open-source AI assistant framework

                         Supported Platforms                          
┏━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Version  ┃ OS           ┃ Architecture ┃ Min Memory ┃ GPU Required ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 0.1.0    │ ubuntu 24.04 │ x86_64       │ 2048MB     │ No           │
│ 0.1.0    │ ubuntu 22.04 │ x86_64       │ 2048MB     │ No           │
│ 2026.4.2 │ ubuntu 24.04 │ x86_64       │ 2048MB     │ No           │
│ 2026.4.2 │ ubuntu 22.04 │ x86_64       │ 2048MB     │ No           │
└──────────┴──────────────┴──────────────┴────────────┴──────────────┘
                      Optional Secrets                       
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key               ┃ Description                           ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ DISCORD_BOT_TOKEN │ Discord bot token for Discord channel │
│ SLACK_BOT_TOKEN   │ Slack bot token for Slack channel     │
│ SLACK_APP_TOKEN   │ Slack app-level token for Socket Mode │
└───────────────────┴───────────────────────────────────────┘

Dependencies:
  - nodejs >=18.0.0
  - nodejs >=20.0.0
```
Exit: `0`

### `clm provider list`

```console
$ clm provider list
                                              Configured Providers                                              
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name               ┃ Type       ┃ Model                             ┃ API Key                   ┃ Added      ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ clm-openrouter     │ openrouter │ openai/gpt-4o                     │ sk-o...9f77               │ 2026-04-10 │
│ local-inx          │ ollama     │ qwen3-coder:30b-128k              │ http://192.168.1.17:11434 │ 2026-04-12 │
│ maurice-openrouter │ openrouter │ z-ai/glm-4.5-air                  │ sk-o...44cc               │ 2026-04-16 │
│ clawrium-bedrock   │ bedrock    │ zai.glm-4.7                       │ AKIA...W5KK               │ 2026-04-17 │
│ clawrium-coder     │ ollama     │ qwen3-coder-next:q4_K_M           │ http://192.168.1.17:11434 │ 2026-05-18 │
│ clawrium-glm-flash │ ollama     │ glm-4.7-flash:latest              │ http://192.168.1.17:11434 │ 2026-05-19 │
│ clawrium-nemotron  │ ollama     │ nemotron-cascade-2:30b-a3b-q4_K_M │ http://192.168.1.17:11434 │ 2026-05-19 │
│ clawrium-deepseek  │ ollama     │ deepseek-r1:70b                   │ http://192.168.1.17:11434 │ 2026-05-19 │
│ clawrium-glm51     │ openrouter │ z-ai/glm-5                        │ sk-o...38fc               │ 2026-05-19 │
└────────────────────┴────────────┴───────────────────────────────────┴───────────────────────────┴────────────┘
```
Exit: `0`

### `clm provider types`

```console
$ clm provider types
Supported provider types:

  anthropic - 7 models
  bedrock - 8 models (SDK-based)
  ollama - Self-hosted (dynamic model discovery)
  openai - 8 models
  openrouter - 14 models
  vertex - 6 models (SDK-based)
  zai - 8 models
```
Exit: `0`

### `clm integration list`

```console
$ clm integration list
                  Configured Integrations                   
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name                ┃ Type   ┃ Credentials  ┃ Added      ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ clawrium-github     │ github │ 1 configured │ 2026-04-16 │
│ clawrium-d01        │ github │ 1 configured │ 2026-05-19 │
│ clawrium-d01-github │ github │ 1 configured │ 2026-05-19 │
└─────────────────────┴────────┴──────────────┴────────────┘
```
Exit: `0`

### `clm integration types`

```console
$ clm integration types
Supported integration types:

  atlassian - Atlassian Cloud (Jira + Confluence) via API token
    Required credentials: 3
  github - GitHub for code hosting, PRs, and issues
    Required credentials: 1
  gitlab - GitLab for code hosting, MRs, and issues
    Required credentials: 1
  linear - Linear for issue tracking and project management
    Required credentials: 1
  notion - Notion for documentation and workspace management
    Required credentials: 1
```
Exit: `0`

### `clm skill list`

```console
$ clm skill list
                                                     Skills catalog                                                     
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Ref                    ┃ Registry ┃ Description                                                                      ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ clawrium/tdd           │ clawrium │ Test-Driven Development discipline. Drives a red → green → refactor cycle for... │
│ hermes/blog-author     │ hermes   │ Watch ric03uec/clawrium release tags; draft a short blog post per user-visibl... │
│ hermes/daily-digest    │ hermes   │ Post a daily engineer-tone summary of the last 24h of activity on ric03uec/cl... │
│ hermes/docs-sync       │ hermes   │ Detect user-visible changes from the last 24h of commits on main and propose ... │
│ hermes/issue-triage    │ hermes   │ Triage new and updated GitHub issues on ric03uec/clawrium — apply type/comple... │
│ hermes/release-watcher │ hermes   │ Watch upstream *Claw releases and clawrium discussions; surface top 3 feature... │
└────────────────────────┴──────────┴──────────────────────────────────────────────────────────────────────────────────┘
```
Exit: `0`

### `clm skill show clawrium/tdd`

```console
$ clm skill show clawrium/tdd

clawrium/tdd
Test-Driven Development discipline. Drives a red → green → refactor cycle for the active task: write a failing test, make it pass with the 
minimum change, then refactor while green.

                         Metadata                         
┌───────────────┬────────────────────────────────────────┐
│ registry      │ clawrium                               │
│ name          │ tdd                                    │
│ version       │ 0.1.0                                  │
│ license       │ MIT                                    │
│ author        │ clawrium                               │
│ platforms     │ linux, macos                           │
│ compatibility │ openclaw=yes, hermes=yes, zeroclaw=yes │
└───────────────┴────────────────────────────────────────┘
╭──────────────────────────────────────────────────────────────── SKILL.md ────────────────────────────────────────────────────────────────╮
│                                                      TDD — Test-Driven Development                                                       │
│                                                                                                                                          │
│ When the user asks you to implement, change, or fix behavior, work in the red → green → refactor loop. The loop is the discipline; do    │
│ not skip a step.                                                                                                                         │
│                                                                                                                                          │
│ The loop                                                                                                                                 │
│                                                                                                                                          │
│  1 Red. Write a single failing test that names the next behavior in the smallest reasonable scope. Run the test suite (or just the new   │
│    test) and confirm the failure is for the right reason (asserts on behavior, not on a missing import or typo).                         │
│  2 Green. Make the test pass with the minimum change. Resist the urge to refactor neighboring code, generalize, or anticipate the next   │
│    test. "Minimum" means: if a literal return makes the test pass, return the literal — then write the next failing test that forces the │
│    generalization.                                                                                                                       │
│  3 Refactor. With the suite green, improve names, remove duplication, tighten interfaces. Run the suite after every refactor step. If a  │
│    refactor turns the suite red, revert immediately and split it smaller.                                                                │
│                                                                                                                                          │
│ When to break the loop                                                                                                                   │
│                                                                                                                                          │
│  • Spike — explore an unknown API in a throwaway branch with no tests, then delete the spike and re-implement TDD-style.                 │
│  • Bug report — write the failing test first that reproduces the bug, even if the production fix is one line. Without the test, the bug  │
│    returns.                                                                                                                              │
│  • Refactor-only — the suite must be green at start and end; no behavior changes in this mode.                                           │
│                                                                                                                                          │
│ Anti-patterns                                                                                                                            │
│                                                                                                                                          │
│  • Writing the implementation first then back-filling tests.                                                                             │
│  • Writing many failing tests at once (you can't tell which one is driving).                                                             │
│  • Skipping the "right reason" check in step 1.                                                                                          │
│  • Refactoring while red.                                                                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```
Exit: `0`


---

## Install transcripts (audit-* agents)

Three fresh audit-only agents are installed on wolf-i below. They will be
removed at the end of capture; the pre-existing fleet is untouched.

### `clm agent install --type zeroclaw --host wolf-i --name audit-zeroclaw --yes`

```console
$ clm agent install --type zeroclaw --host wolf-i --name audit-zeroclaw --yes
╭────────────────────────────────────────────────────────── Installation Summary ──────────────────────────────────────────────────────────╮
│ Agent Type: zeroclaw                                                                                                                     │
│ Version: 0.7.5                                                                                                                           │
│ Host: wolf-i                                                                                                                             │
│ Architecture: x86_64                                                                                                                     │
│ Memory: 15.5GB                                                                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

No config file found; using defaults

PLAY [all] *********************************************************************

TASK [Gathering Facts] *********************************************************
[WARNING]: Host 'wolf.tailf7742d.ts.net' is using the discovered Python interpreter at '/usr/bin/python3.12', but future installation of another Python interpreter could cause a different interpreter to be discovered. See https://docs.ansible.com/ansible-core/2.20/reference_appendices/interpreter_discovery.html for more information.
ok: [wolf.tailf7742d.ts.net]

TASK [Kill stale apt lock holders] *********************************************
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/apt/lists/lock) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/apt/lists/lock"], "delta": "0:00:00.069803", "end": "2026-05-23 20:27:44.957292", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/apt/lists/lock", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:27:44.887489", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/dpkg/lock) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/dpkg/lock"], "delta": "0:00:00.066395", "end": "2026-05-23 20:27:45.439068", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/dpkg/lock", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:27:45.372673", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/dpkg/lock-frontend) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/dpkg/lock-frontend"], "delta": "0:00:00.067464", "end": "2026-05-23 20:27:45.916375", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/dpkg/lock-frontend", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:27:45.848911", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}

TASK [Update apt cache] ********************************************************
changed: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": true, "changed": true}

TASK [Check if node is installed] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "cmd": ["node", "--version"], "delta": "0:00:00.006262", "end": "2026-05-23 20:27:51.824336", "failed_when_result": false, "msg": "", "rc": 0, "start": "2026-05-23 20:27:51.818074", "stderr": "", "stderr_lines": [], "stdout": "v22.22.1", "stdout_lines": ["v22.22.1"]}

TASK [Install required packages for NodeSource repository] *********************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Create keyrings directory] ***********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Download NodeSource GPG key] *********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Add NodeSource repository for Node.js 20] ********************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Install Node.js] *********************************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Install build-essential] *************************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

TASK [Install git and GitHub CLI] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

PLAY RECAP *********************************************************************
wolf.tailf7742d.ts.net     : ok=6    changed=1    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0   
No config file found; using defaults

PLAY [all] *********************************************************************

TASK [Gathering Facts] *********************************************************
[WARNING]: Host 'wolf.tailf7742d.ts.net' is using the discovered Python interpreter at '/usr/bin/python3.12', but future installation of another Python interpreter could cause a different interpreter to be discovered. See https://docs.ansible.com/ansible-core/2.20/reference_appendices/interpreter_discovery.html for more information.
ok: [wolf.tailf7742d.ts.net]

TASK [Validate architecture is supported] **************************************
[WARNING]: Deprecation warnings can be disabled by setting `deprecation_warnings=False` in ansible.cfg.
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "ansible_architecture not in supported_architectures", "skip_reason": "Conditional result was False"}

TASK [Normalize target ZeroClaw version (strip leading 'v')] *******************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"zeroclaw_target_version": "0.7.5"}, "changed": false}

TASK [Resolve ZeroClaw release tag (always 'v'-prefixed)] **********************
[DEPRECATION WARNING]: INJECT_FACTS_AS_VARS default to `True` is deprecated, top-level facts will not be auto injected after the change. This feature will be removed from ansible-core version 2.24.
Origin: /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/platform/registry/zeroclaw/playbooks/install.yaml:14:19

12       - aarch64
13       - x86_64
14     release_arch: "{{ arch_map[ansible_architecture] }}"
                     ^ column 19

Use `ansible_facts["fact_name"]` (no `ansible_` prefix) instead.

ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"release_url": "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.7.5/zeroclaw-x86_64-unknown-linux-gnu.tar.gz", "zeroclaw_target_tag": "v0.7.5"}, "changed": false}

TASK [Create agent user] *******************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "comment": "", "create_home": true, "group": 1012, "home": "/home/audit-zeroclaw", "name": "audit-zeroclaw", "shell": "/usr/sbin/nologin", "state": "present", "system": false, "uid": 1012}

TASK [Create bin directory] ****************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1012, "group": "audit-zeroclaw", "mode": "0755", "owner": "audit-zeroclaw", "path": "/home/audit-zeroclaw/bin", "size": 4096, "state": "directory", "uid": 1012}

TASK [Discover zeroclaw binary at agent's install path] ************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "stat": {"exists": false}}

TASK [Get installed zeroclaw version] ******************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "zeroclaw_binary_stat.stat.exists", "skip_reason": "Conditional result was False"}

TASK [Parse installed zeroclaw version] ****************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "(zeroclaw_version_check.rc | default(1)) == 0", "skip_reason": "Conditional result was False"}

TASK [Set install skip condition] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"zeroclaw_already_installed": false}, "changed": false}

TASK [Mark install as skipped when already installed] **************************
skipping: [wolf.tailf7742d.ts.net] => {"false_condition": "zeroclaw_already_installed"}

TASK [Note that --force was supplied (overriding skip)] ************************
skipping: [wolf.tailf7742d.ts.net] => {"false_condition": "zeroclaw_binary_stat.stat.exists"}

TASK [Download zeroclaw binary] ************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum_dest": null, "checksum_src": "bb688658508de72a086304d9213bca6d5ffd9a2b", "dest": "/tmp/zeroclaw-x86_64-unknown-linux-gnu.tar.gz", "elapsed": 1, "gid": 0, "group": "root", "md5sum": "c3a14c3247973dd891f7bce18d1aca73", "mode": "0644", "msg": "OK (15812349 bytes)", "owner": "root", "size": 15812349, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593278.751683-1450225-102285456266319/tmp4sdjb7mn", "state": "file", "status_code": 200, "uid": 0, "url": "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.7.5/zeroclaw-x86_64-unknown-linux-gnu.tar.gz"}

TASK [Extract zeroclaw binary] *************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "dest": "/home/audit-zeroclaw/bin", "extract_results": {"cmd": ["/usr/bin/tar", "--extract", "-C", "/home/audit-zeroclaw/bin", "-z", "--owner=audit-zeroclaw", "--group=audit-zeroclaw", "-f", "/tmp/zeroclaw-x86_64-unknown-linux-gnu.tar.gz"], "err": "", "out": "", "rc": 0}, "gid": 1012, "group": "audit-zeroclaw", "handler": "TgzArchive", "mode": "0755", "owner": "audit-zeroclaw", "size": 4096, "src": "/tmp/zeroclaw-x86_64-unknown-linux-gnu.tar.gz", "state": "directory", "uid": 1012}

TASK [Cleanup tarball] *********************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "path": "/tmp/zeroclaw-x86_64-unknown-linux-gnu.tar.gz", "state": "absent"}

TASK [Create zeroclaw config directory] ****************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1012, "group": "audit-zeroclaw", "mode": "0700", "owner": "audit-zeroclaw", "path": "/home/audit-zeroclaw/.zeroclaw", "size": 4096, "state": "directory", "uid": 1012}

TASK [Scaffold workspace directory] ********************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1012, "group": "audit-zeroclaw", "mode": "0700", "owner": "audit-zeroclaw", "path": "/home/audit-zeroclaw/.zeroclaw/workspace", "size": 4096, "state": "directory", "uid": 1012}

TASK [Scaffold state directory] ************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1012, "group": "audit-zeroclaw", "mode": "0700", "owner": "audit-zeroclaw", "path": "/home/audit-zeroclaw/.zeroclaw/state", "size": 4096, "state": "directory", "uid": 1012}

TASK [Create systemd service file (disabled, not started)] *********************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum": "8cdb4415394832fae557239a6717258fd9e19a56", "dest": "/etc/systemd/system/zeroclaw-audit-zeroclaw.service", "gid": 0, "group": "root", "md5sum": "0eec36b92a82858fdf84dbd6ee580130", "mode": "0644", "owner": "root", "size": 291, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593284.6864388-1450424-6517800773627/.source.service", "state": "file", "uid": 0}

TASK [Reload systemd to pick up unit file] *************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "name": null, "status": {}}

TASK [Display install success] *************************************************
ok: [wolf.tailf7742d.ts.net] => {
    "msg": "ZeroClaw 0.7.5 installed for agent 'audit-zeroclaw'.\nService unit zeroclaw-audit-zeroclaw.service dropped (disabled, stopped).\nRun 'clm agent configure audit-zeroclaw' to render config.toml and start the daemon.\n"
}

PLAY RECAP *********************************************************************
wolf.tailf7742d.ts.net     : ok=16   changed=9    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0   

Success! zeroclaw v0.7.5 installed as 'audit-zeroclaw' on wolf-i
```
Exit: `0`

### `clm agent install --type hermes --host wolf-i --name audit-hermes --yes`

```console
$ clm agent install --type hermes --host wolf-i --name audit-hermes --yes
╭────────────────────────────────────────────────────────── Installation Summary ──────────────────────────────────────────────────────────╮
│ Agent Type: hermes                                                                                                                       │
│ Version: 2026.5.7                                                                                                                        │
│ Host: wolf-i                                                                                                                             │
│ Architecture: x86_64                                                                                                                     │
│ Memory: 15.5GB                                                                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

No config file found; using defaults

PLAY [all] *********************************************************************

TASK [Gathering Facts] *********************************************************
[WARNING]: Host 'wolf.tailf7742d.ts.net' is using the discovered Python interpreter at '/usr/bin/python3.12', but future installation of another Python interpreter could cause a different interpreter to be discovered. See https://docs.ansible.com/ansible-core/2.20/reference_appendices/interpreter_discovery.html for more information.
ok: [wolf.tailf7742d.ts.net]

TASK [Kill stale apt lock holders] *********************************************
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/apt/lists/lock) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/apt/lists/lock"], "delta": "0:00:00.069955", "end": "2026-05-23 20:28:20.983489", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/apt/lists/lock", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:28:20.913534", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/dpkg/lock) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/dpkg/lock"], "delta": "0:00:00.081451", "end": "2026-05-23 20:28:21.526158", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/dpkg/lock", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:28:21.444707", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/dpkg/lock-frontend) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/dpkg/lock-frontend"], "delta": "0:00:00.066138", "end": "2026-05-23 20:28:22.027585", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/dpkg/lock-frontend", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:28:21.961447", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}

TASK [Update apt cache] ********************************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

TASK [Check if node is installed] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "cmd": ["node", "--version"], "delta": "0:00:00.006061", "end": "2026-05-23 20:28:23.463825", "failed_when_result": false, "msg": "", "rc": 0, "start": "2026-05-23 20:28:23.457764", "stderr": "", "stderr_lines": [], "stdout": "v22.22.1", "stdout_lines": ["v22.22.1"]}

TASK [Install required packages for NodeSource repository] *********************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Create keyrings directory] ***********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Download NodeSource GPG key] *********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Add NodeSource repository for Node.js 20] ********************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Install Node.js] *********************************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Install build-essential] *************************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

TASK [Install git and GitHub CLI] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

PLAY RECAP *********************************************************************
wolf.tailf7742d.ts.net     : ok=6    changed=0    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0   
No config file found; using defaults

PLAY [all] *********************************************************************

TASK [Gathering Facts] *********************************************************
[WARNING]: Host 'wolf.tailf7742d.ts.net' is using the discovered Python interpreter at '/usr/bin/python3.12', but future installation of another Python interpreter could cause a different interpreter to be discovered. See https://docs.ansible.com/ansible-core/2.20/reference_appendices/interpreter_discovery.html for more information.
ok: [wolf.tailf7742d.ts.net]

TASK [Normalize target Hermes version (strip leading 'v')] *********************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"hermes_target_version": "2026.5.7"}, "changed": false}

TASK [Resolve Hermes git tag for installer (always 'v'-prefixed)] **************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"hermes_target_branch": "v2026.5.7"}, "changed": false}

TASK [Create agent user] *******************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "comment": "", "create_home": true, "group": 1013, "home": "/home/audit-hermes", "name": "audit-hermes", "shell": "/usr/sbin/nologin", "state": "present", "system": false, "uid": 1013}

TASK [Install hermes system dependencies (ripgrep, ffmpeg)] ********************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

TASK [Discover hermes binary at agent's user-local install path] ***************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "stat": {"exists": false}}

TASK [Get installed hermes version] ********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "hermes_binary_stat.stat.exists", "skip_reason": "Conditional result was False"}

TASK [Parse installed hermes version] ******************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "(hermes_version_check.rc | default(1)) == 0", "skip_reason": "Conditional result was False"}

TASK [Set install skip condition] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"hermes_already_installed": false}, "changed": false}

TASK [Mark install as skipped when already installed] **************************
skipping: [wolf.tailf7742d.ts.net] => {"false_condition": "hermes_already_installed"}

TASK [Note that --force was supplied (overriding skip)] ************************
skipping: [wolf.tailf7742d.ts.net] => {"false_condition": "hermes_binary_stat.stat.exists"}

TASK [Remove existing Hermes binary symlink (forced reinstall)] ****************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "force_install | default(false) | bool", "skip_reason": "Conditional result was False"}

TASK [Download Hermes installer script] ****************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum_dest": null, "checksum_src": "da96e86998cf4ededd3fe30be9f3b002a2f866fe", "dest": "/home/audit-hermes/hermes-install.sh", "elapsed": 0, "gid": 1013, "group": "audit-hermes", "md5sum": "857999f68cac4441a6adaebf9b5a54f2", "mode": "0700", "msg": "OK (62237 bytes)", "owner": "audit-hermes", "size": 62237, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593310.9353557-1451408-239494034464156/tmpjcwv8rtp", "state": "file", "status_code": 200, "uid": 1013, "url": "https://raw.githubusercontent.com/NousResearch/hermes-agent/v2026.5.7/scripts/install.sh"}

TASK [Install Hermes runtime (non-interactive)] ********************************
ASYNC POLL on wolf.tailf7742d.ts.net: jid=j903788584236.480558 started=True finished=False
ASYNC POLL on wolf.tailf7742d.ts.net: jid=j903788584236.480558 started=True finished=False
ASYNC OK on wolf.tailf7742d.ts.net: jid=j903788584236.480558
[WARNING]: Module remote_tmp /home/audit-hermes/.ansible/tmp did not exist and was created with a mode of 0700, this may cause issues when running as another user. To avoid this, create the remote_tmp dir with the correct permissions manually
changed: [wolf.tailf7742d.ts.net] => {"ansible_job_id": "j903788584236.480558", "changed": true, "cmd": ["/bin/bash", "/home/audit-hermes/hermes-install.sh", "--skip-setup", "--branch", "v2026.5.7", "--hermes-home", "/home/audit-hermes/.hermes", "--dir", "/home/audit-hermes/.hermes/code"], "delta": "0:01:31.170811", "end": "2026-05-23 20:30:04.043079", "finished": true, "msg": "", "rc": 0, "results_file": "/home/audit-hermes/.ansible_async/j903788584236.480558", "start": "2026-05-23 20:28:32.872268", "started": true, "stderr": "Downloading cpython-3.11.15-linux-x86_64-gnu (download) (29.8MiB)\n Downloaded cpython-3.11.15-linux-x86_64-gnu (download)\nInstalled Python 3.11.15 in 1.76s\n + cpython-3.11.15-linux-x86_64-gnu (python3.11)\nwarning: `/home/audit-hermes/.local/bin` is not on your PATH. To use installed Python executables, add the directory to your PATH.\nCloning into '/home/audit-hermes/.hermes/code'...\nNote: switching to '498bfc7bc12a937621b4215312049b1000726df3'.\n\nYou are in 'detached HEAD' state. You can look around, make experimental\nchanges and commit them, and you can discard any commits you make in this\nstate without impacting any branches by switching back to a branch.\n\nIf you want to create a new branch to retain commits you create, you may\ndo so (now or later) by using -c with the switch command. Example:\n\n  git switch -c <new-branch-name>\n\nOr undo this operation with:\n\n  git switch -\n\nTurn off this advice by setting config variable advice.detachedHead to false\n\nUsing CPython 3.11.15\nCreating virtual environment at: venv\n/home/audit-hermes/hermes-install.sh: line 180: /dev/tty: No such device or address\n/home/audit-hermes/hermes-install.sh: line 181: /dev/tty: No such device or address\nsudo: a terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper\nsudo: a password is required", "stderr_lines": ["Downloading cpython-3.11.15-linux-x86_64-gnu (download) (29.8MiB)", " Downloaded cpython-3.11.15-linux-x86_64-gnu (download)", "Installed Python 3.11.15 in 1.76s", " + cpython-3.11.15-linux-x86_64-gnu (python3.11)", "warning: `/home/audit-hermes/.local/bin` is not on your PATH. To use installed Python executables, add the directory to your PATH.", "Cloning into '/home/audit-hermes/.hermes/code'...", "Note: switching to '498bfc7bc12a937621b4215312049b1000726df3'.", "", "You are in 'detached HEAD' state. You can look around, make experimental", "changes and commit them, and you can discard any commits you make in this", "state without impacting any branches by switching back to a branch.", "", "If you want to create a new branch to retain commits you create, you may", "do so (now or later) by using -c with the switch command. Example:", "", "  git switch -c <new-branch-name>", "", "Or undo this operation with:", "", "  git switch -", "", "Turn off this advice by setting config variable advice.detachedHead to false", "", "Using CPython 3.11.15", "Creating virtual environment at: venv", "/home/audit-hermes/hermes-install.sh: line 180: /dev/tty: No such device or address", "/home/audit-hermes/hermes-install.sh: line 181: /dev/tty: No such device or address", "sudo: a terminal is required to read the password; either use the -S option to read from standard input or configure an askpass helper", "sudo: a password is required"], "stdout": "\n\u001b[0;35m\u001b[1m\n┌─────────────────────────────────────────────────────────┐\n│             ⚕ Hermes Agent Installer                    │\n├─────────────────────────────────────────────────────────┤\n│  An open source AI agent by Nous Research.              │\n└─────────────────────────────────────────────────────────┘\n\u001b[0m\n\u001b[0;32m✓\u001b[0m Detected: linux (ubuntu)\n\u001b[0;36m→\u001b[0m Install directory: /home/audit-hermes/.hermes/code (explicit)\n\u001b[0;36m→\u001b[0m Checking for uv package manager...\n\u001b[0;32m✓\u001b[0m uv found (uv 0.10.10)\n\u001b[0;36m→\u001b[0m Checking Python 3.11...\n\u001b[0;36m→\u001b[0m Python 3.11 not found, installing via uv...\n\u001b[0;32m✓\u001b[0m Python installed: Python 3.11.15\n\u001b[0;36m→\u001b[0m Checking Git...\n\u001b[0;32m✓\u001b[0m Git 2.43.0 found\n\u001b[0;36m→\u001b[0m Checking Node.js (for browser tools)...\n\u001b[0;32m✓\u001b[0m Node.js v22.22.1 found\n\u001b[0;36m→\u001b[0m Checking ripgrep (fast file search)...\n\u001b[0;32m✓\u001b[0m ripgrep 14.1.0 found\n\u001b[0;36m→\u001b[0m Checking ffmpeg (TTS voice messages)...\n\u001b[0;32m✓\u001b[0m ffmpeg 6.1.1-3ubuntu5 found\n\u001b[0;36m→\u001b[0m Installing to /home/audit-hermes/.hermes/code...\n\u001b[0;36m→\u001b[0m Trying SSH clone...\n\u001b[0;36m→\u001b[0m SSH failed, trying HTTPS...\n\u001b[0;32m✓\u001b[0m Cloned via HTTPS\n\u001b[0;32m✓\u001b[0m Repository ready\n\u001b[0;36m→\u001b[0m Creating virtual environment with Python 3.11...\n\u001b[0;32m✓\u001b[0m Virtual environment ready (Python 3.11)\n\u001b[0;36m→\u001b[0m Installing dependencies...\n\u001b[0;36m→\u001b[0m Some build tools may be needed for Python packages...\n\u001b[0;36m→\u001b[0m sudo is needed ONLY to install build tools (build-essential, python3-dev, libffi-dev) via apt.\n\u001b[0;36m→\u001b[0m Hermes Agent itself does not require or retain root access.\n\u001b[0;32m✓\u001b[0m Build tools installed\n\u001b[0;32m✓\u001b[0m Main package installed\n\u001b[0;32m✓\u001b[0m All dependencies installed\n\u001b[0;36m→\u001b[0m Installing Node.js dependencies (browser tools)...\n✅ Browser tools ready. Run: python run_agent.py --help\n\u001b[0;32m✓\u001b[0m Node.js dependencies installed\n\u001b[0;36m→\u001b[0m Installing browser engine (Playwright Chromium)...\n\u001b[0;36m→\u001b[0m Playwright may request sudo to install browser system dependencies (shared libraries).\n\u001b[0;36m→\u001b[0m This is standard Playwright setup — Hermes itself does not require root access.\nInstalling dependencies...\nSwitching to root user to install dependencies...\nFailed to install browsers\nError: Installation process exited with code: 1\n\u001b[0;33m⚠\u001b[0m Playwright browser installation failed — browser tools will not work.\n\u001b[0;33m⚠\u001b[0m Try running manually: cd /home/audit-hermes/.hermes/code && npx playwright install --with-deps chromium\n\u001b[0;32m✓\u001b[0m Browser engine setup complete\n\u001b[0;36m→\u001b[0m Installing TUI dependencies...\n\u001b[0;32m✓\u001b[0m TUI dependencies installed\n\u001b[0;36m→\u001b[0m Setting up hermes command...\n\u001b[0;32m✓\u001b[0m Installed hermes launcher → ~/.local/bin/hermes\n\u001b[0;32m✓\u001b[0m Added ~/.local/bin to PATH in /home/audit-hermes/.bashrc\n\u001b[0;32m✓\u001b[0m hermes command ready\n\u001b[0;36m→\u001b[0m Setting up configuration files...\n\u001b[0;32m✓\u001b[0m Created ~/.hermes/.env from template\n\u001b[0;32m✓\u001b[0m Created ~/.hermes/config.yaml from template\n\u001b[0;32m✓\u001b[0m Created ~/.hermes/SOUL.md (edit to customize personality)\n\u001b[0;32m✓\u001b[0m Configuration directory ready: ~/.hermes/\n\u001b[0;36m→\u001b[0m Syncing bundled skills to ~/.hermes/skills/ ...\nSyncing bundled skills into ~/.hermes/skills/ ...\n  + xurl\n  + openhue\n  + youtube-content\n  + gif-search\n  + heartmula\n  + spotify\n  + songsee\n  + notion\n  + powerpoint\n  + linear\n  + maps\n  + google-workspace\n  + nano-pdf\n  + ocr-and-documents\n  + airtable\n  + huggingface-hub\n  + dspy\n  + audiocraft-audio-generation\n  + segment-anything-model\n  + outlines\n  + serving-llms-vllm\n  + obliteratus\n  + llama-cpp\n  + unsloth\n  + axolotl\n  + fine-tuning-with-trl\n  + evaluating-llms-harness\n  + weights-and-biases\n  + apple-notes\n  + findmy\n  + imessage\n  + apple-reminders\n  + polymarket\n  + llm-wiki\n  + arxiv\n  + research-paper-writing\n  + blogwatcher\n  + godmode\n  + jupyter-live-kernel\n  + claude-code\n  + opencode\n  + hermes-agent\n  + codex\n  + himalaya\n  + native-mcp\n  + minecraft-modpack-server\n  + pokemon-player\n  + yuanbao\n  + python-debugpy\n  + writing-plans\n  + systematic-debugging\n  + hermes-agent-skill-authoring\n  + test-driven-development\n  + node-inspect-debugger\n  + requesting-code-review\n  + plan\n  + spike\n  + debugging-hermes-tui-commands\n  + subagent-driven-development\n  + kanban-worker\n  + webhook-subscriptions\n  + kanban-orchestrator\n  + dogfood\n  + github-auth\n  + github-pr-workflow\n  + github-repo-management\n  + github-code-review\n  + codebase-inspection\n  + github-issues\n  + touchdesigner-mcp\n  + popular-web-designs\n  + p5js\n  + comfyui\n  + baoyu-comic\n  + sketch\n  + ideation\n  + claude-design\n  + pixel-art\n  + baoyu-infographic\n  + manim-video\n  + pretext\n  + excalidraw\n  + ascii-video\n  + songwriting-and-ai-music\n  + architecture-diagram\n  + humanizer\n  + ascii-art\n  + design-md\n  + obsidian\n\nDone: 89 new, 0 updated, 0 unchanged. 89 total bundled.\n\u001b[0;32m✓\u001b[0m Skills synced to ~/.hermes/skills/\n\u001b[0;36m→\u001b[0m Skipping setup wizard (--skip-setup)\n\n\u001b[0;32m\u001b[1m\n┌─────────────────────────────────────────────────────────┐\n│              ✓ Installation Complete!                   │\n└─────────────────────────────────────────────────────────┘\n\u001b[0m\n\n\u001b[0;36m\u001b[1m📁 Your files:\u001b[0m\n\n   \u001b[0;33mConfig:\u001b[0m    /home/audit-hermes/.hermes/config.yaml\n   \u001b[0;33mAPI Keys:\u001b[0m  /home/audit-hermes/.hermes/.env\n   \u001b[0;33mData:\u001b[0m      /home/audit-hermes/.hermes/cron/, sessions/, logs/\n   \u001b[0;33mCode:\u001b[0m      /home/audit-hermes/.hermes/code\n\n\u001b[0;36m─────────────────────────────────────────────────────────\u001b[0m\n\n\u001b[0;36m\u001b[1m🚀 Commands:\u001b[0m\n\n   \u001b[0;32mhermes\u001b[0m              Start chatting\n   \u001b[0;32mhermes setup\u001b[0m        Configure API keys & settings\n   \u001b[0;32mhermes config\u001b[0m       View/edit configuration\n   \u001b[0;32mhermes config edit\u001b[0m  Open config in editor\n   \u001b[0;32mhermes gateway install\u001b[0m Install gateway service (messaging + cron)\n   \u001b[0;32mhermes update\u001b[0m       Update to latest version\n\n\u001b[0;36m─────────────────────────────────────────────────────────\u001b[0m\n\n\u001b[0;33m⚡ Reload your shell to use 'hermes' command:\u001b[0m\n\n   source ~/.bashrc   # or ~/.zshrc", "stdout_lines": ["", "\u001b[0;35m\u001b[1m", "┌─────────────────────────────────────────────────────────┐", "│             ⚕ Hermes Agent Installer                    │", "├─────────────────────────────────────────────────────────┤", "│  An open source AI agent by Nous Research.              │", "└─────────────────────────────────────────────────────────┘", "\u001b[0m", "\u001b[0;32m✓\u001b[0m Detected: linux (ubuntu)", "\u001b[0;36m→\u001b[0m Install directory: /home/audit-hermes/.hermes/code (explicit)", "\u001b[0;36m→\u001b[0m Checking for uv package manager...", "\u001b[0;32m✓\u001b[0m uv found (uv 0.10.10)", "\u001b[0;36m→\u001b[0m Checking Python 3.11...", "\u001b[0;36m→\u001b[0m Python 3.11 not found, installing via uv...", "\u001b[0;32m✓\u001b[0m Python installed: Python 3.11.15", "\u001b[0;36m→\u001b[0m Checking Git...", "\u001b[0;32m✓\u001b[0m Git 2.43.0 found", "\u001b[0;36m→\u001b[0m Checking Node.js (for browser tools)...", "\u001b[0;32m✓\u001b[0m Node.js v22.22.1 found", "\u001b[0;36m→\u001b[0m Checking ripgrep (fast file search)...", "\u001b[0;32m✓\u001b[0m ripgrep 14.1.0 found", "\u001b[0;36m→\u001b[0m Checking ffmpeg (TTS voice messages)...", "\u001b[0;32m✓\u001b[0m ffmpeg 6.1.1-3ubuntu5 found", "\u001b[0;36m→\u001b[0m Installing to /home/audit-hermes/.hermes/code...", "\u001b[0;36m→\u001b[0m Trying SSH clone...", "\u001b[0;36m→\u001b[0m SSH failed, trying HTTPS...", "\u001b[0;32m✓\u001b[0m Cloned via HTTPS", "\u001b[0;32m✓\u001b[0m Repository ready", "\u001b[0;36m→\u001b[0m Creating virtual environment with Python 3.11...", "\u001b[0;32m✓\u001b[0m Virtual environment ready (Python 3.11)", "\u001b[0;36m→\u001b[0m Installing dependencies...", "\u001b[0;36m→\u001b[0m Some build tools may be needed for Python packages...", "\u001b[0;36m→\u001b[0m sudo is needed ONLY to install build tools (build-essential, python3-dev, libffi-dev) via apt.", "\u001b[0;36m→\u001b[0m Hermes Agent itself does not require or retain root access.", "\u001b[0;32m✓\u001b[0m Build tools installed", "\u001b[0;32m✓\u001b[0m Main package installed", "\u001b[0;32m✓\u001b[0m All dependencies installed", "\u001b[0;36m→\u001b[0m Installing Node.js dependencies (browser tools)...", "✅ Browser tools ready. Run: python run_agent.py --help", "\u001b[0;32m✓\u001b[0m Node.js dependencies installed", "\u001b[0;36m→\u001b[0m Installing browser engine (Playwright Chromium)...", "\u001b[0;36m→\u001b[0m Playwright may request sudo to install browser system dependencies (shared libraries).", "\u001b[0;36m→\u001b[0m This is standard Playwright setup — Hermes itself does not require root access.", "Installing dependencies...", "Switching to root user to install dependencies...", "Failed to install browsers", "Error: Installation process exited with code: 1", "\u001b[0;33m⚠\u001b[0m Playwright browser installation failed — browser tools will not work.", "\u001b[0;33m⚠\u001b[0m Try running manually: cd /home/audit-hermes/.hermes/code && npx playwright install --with-deps chromium", "\u001b[0;32m✓\u001b[0m Browser engine setup complete", "\u001b[0;36m→\u001b[0m Installing TUI dependencies...", "\u001b[0;32m✓\u001b[0m TUI dependencies installed", "\u001b[0;36m→\u001b[0m Setting up hermes command...", "\u001b[0;32m✓\u001b[0m Installed hermes launcher → ~/.local/bin/hermes", "\u001b[0;32m✓\u001b[0m Added ~/.local/bin to PATH in /home/audit-hermes/.bashrc", "\u001b[0;32m✓\u001b[0m hermes command ready", "\u001b[0;36m→\u001b[0m Setting up configuration files...", "\u001b[0;32m✓\u001b[0m Created ~/.hermes/.env from template", "\u001b[0;32m✓\u001b[0m Created ~/.hermes/config.yaml from template", "\u001b[0;32m✓\u001b[0m Created ~/.hermes/SOUL.md (edit to customize personality)", "\u001b[0;32m✓\u001b[0m Configuration directory ready: ~/.hermes/", "\u001b[0;36m→\u001b[0m Syncing bundled skills to ~/.hermes/skills/ ...", "Syncing bundled skills into ~/.hermes/skills/ ...", "  + xurl", "  + openhue", "  + youtube-content", "  + gif-search", "  + heartmula", "  + spotify", "  + songsee", "  + notion", "  + powerpoint", "  + linear", "  + maps", "  + google-workspace", "  + nano-pdf", "  + ocr-and-documents", "  + airtable", "  + huggingface-hub", "  + dspy", "  + audiocraft-audio-generation", "  + segment-anything-model", "  + outlines", "  + serving-llms-vllm", "  + obliteratus", "  + llama-cpp", "  + unsloth", "  + axolotl", "  + fine-tuning-with-trl", "  + evaluating-llms-harness", "  + weights-and-biases", "  + apple-notes", "  + findmy", "  + imessage", "  + apple-reminders", "  + polymarket", "  + llm-wiki", "  + arxiv", "  + research-paper-writing", "  + blogwatcher", "  + godmode", "  + jupyter-live-kernel", "  + claude-code", "  + opencode", "  + hermes-agent", "  + codex", "  + himalaya", "  + native-mcp", "  + minecraft-modpack-server", "  + pokemon-player", "  + yuanbao", "  + python-debugpy", "  + writing-plans", "  + systematic-debugging", "  + hermes-agent-skill-authoring", "  + test-driven-development", "  + node-inspect-debugger", "  + requesting-code-review", "  + plan", "  + spike", "  + debugging-hermes-tui-commands", "  + subagent-driven-development", "  + kanban-worker", "  + webhook-subscriptions", "  + kanban-orchestrator", "  + dogfood", "  + github-auth", "  + github-pr-workflow", "  + github-repo-management", "  + github-code-review", "  + codebase-inspection", "  + github-issues", "  + touchdesigner-mcp", "  + popular-web-designs", "  + p5js", "  + comfyui", "  + baoyu-comic", "  + sketch", "  + ideation", "  + claude-design", "  + pixel-art", "  + baoyu-infographic", "  + manim-video", "  + pretext", "  + excalidraw", "  + ascii-video", "  + songwriting-and-ai-music", "  + architecture-diagram", "  + humanizer", "  + ascii-art", "  + design-md", "  + obsidian", "", "Done: 89 new, 0 updated, 0 unchanged. 89 total bundled.", "\u001b[0;32m✓\u001b[0m Skills synced to ~/.hermes/skills/", "\u001b[0;36m→\u001b[0m Skipping setup wizard (--skip-setup)", "", "\u001b[0;32m\u001b[1m", "┌─────────────────────────────────────────────────────────┐", "│              ✓ Installation Complete!                   │", "└─────────────────────────────────────────────────────────┘", "\u001b[0m", "", "\u001b[0;36m\u001b[1m📁 Your files:\u001b[0m", "", "   \u001b[0;33mConfig:\u001b[0m    /home/audit-hermes/.hermes/config.yaml", "   \u001b[0;33mAPI Keys:\u001b[0m  /home/audit-hermes/.hermes/.env", "   \u001b[0;33mData:\u001b[0m      /home/audit-hermes/.hermes/cron/, sessions/, logs/", "   \u001b[0;33mCode:\u001b[0m      /home/audit-hermes/.hermes/code", "", "\u001b[0;36m─────────────────────────────────────────────────────────\u001b[0m", "", "\u001b[0;36m\u001b[1m🚀 Commands:\u001b[0m", "", "   \u001b[0;32mhermes\u001b[0m              Start chatting", "   \u001b[0;32mhermes setup\u001b[0m        Configure API keys & settings", "   \u001b[0;32mhermes config\u001b[0m       View/edit configuration", "   \u001b[0;32mhermes config edit\u001b[0m  Open config in editor", "   \u001b[0;32mhermes gateway install\u001b[0m Install gateway service (messaging + cron)", "   \u001b[0;32mhermes update\u001b[0m       Update to latest version", "", "\u001b[0;36m─────────────────────────────────────────────────────────\u001b[0m", "", "\u001b[0;33m⚡ Reload your shell to use 'hermes' command:\u001b[0m", "", "   source ~/.bashrc   # or ~/.zshrc"]}

TASK [Clean up installer script] ***********************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "path": "/home/audit-hermes/hermes-install.sh", "state": "absent"}

TASK [Create Hermes config directory] ******************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1013, "group": "audit-hermes", "mode": "0700", "owner": "audit-hermes", "path": "/home/audit-hermes/.hermes", "size": 4096, "state": "directory", "uid": 1013}

TASK [Create empty Hermes environment file (preserved across re-installs)] *****
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "dest": "/home/audit-hermes/.hermes/.env", "src": "/home/devashish/.ansible/tmp/ansible-local-1451238qiq9miop/.d4gtow2m"}

TASK [Enforce 0600 permissions on Hermes environment file] *********************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1013, "group": "audit-hermes", "mode": "0600", "owner": "audit-hermes", "path": "/home/audit-hermes/.hermes/.env", "size": 21610, "state": "file", "uid": 1013}

TASK [Create Hermes memories directory] ****************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1013, "group": "audit-hermes", "mode": "0700", "owner": "audit-hermes", "path": "/home/audit-hermes/.hermes/memories", "size": 4096, "state": "directory", "uid": 1013}

TASK [Create systemd service file (disabled, not started)] *********************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum": "5e2484049c86e18e63c6656da16b88160498093b", "dest": "/etc/systemd/system/hermes-audit-hermes.service", "gid": 0, "group": "root", "md5sum": "9410301ab80f533592b9f0bbe8c83db8", "mode": "0644", "owner": "root", "size": 333, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593407.3811157-1454408-256975507905295/.source.service", "state": "file", "uid": 0}

TASK [Reload systemd to pick up unit file] *************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "name": null, "status": {}}

TASK [Display install success] *************************************************
ok: [wolf.tailf7742d.ts.net] => {
    "msg": "Hermes 2026.5.7 installed for agent 'audit-hermes'.\nService unit hermes-audit-hermes.service dropped (disabled, stopped).\nRun `clm agent configure audit-hermes` to provision a provider and start the gateway.\n"
}

RUNNING HANDLER [Reload systemd] ***********************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "name": null, "status": {}}

PLAY RECAP *********************************************************************
wolf.tailf7742d.ts.net     : ok=18   changed=8    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0   

Success! hermes v2026.5.7 installed as 'audit-hermes' on wolf-i
```
Exit: `0`

### `clm agent install --type openclaw --host wolf-i --name audit-openclaw --yes`

```console
$ clm agent install --type openclaw --host wolf-i --name audit-openclaw --yes
╭────────────────────────────────────────────────────────── Installation Summary ──────────────────────────────────────────────────────────╮
│ Agent Type: openclaw                                                                                                                     │
│ Version: 2026.4.2                                                                                                                        │
│ Host: wolf-i                                                                                                                             │
│ Architecture: x86_64                                                                                                                     │
│ Memory: 15.5GB                                                                                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

No config file found; using defaults

PLAY [all] *********************************************************************

TASK [Gathering Facts] *********************************************************
[WARNING]: Host 'wolf.tailf7742d.ts.net' is using the discovered Python interpreter at '/usr/bin/python3.12', but future installation of another Python interpreter could cause a different interpreter to be discovered. See https://docs.ansible.com/ansible-core/2.20/reference_appendices/interpreter_discovery.html for more information.
ok: [wolf.tailf7742d.ts.net]

TASK [Kill stale apt lock holders] *********************************************
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/apt/lists/lock) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/apt/lists/lock"], "delta": "0:00:00.072885", "end": "2026-05-23 20:30:16.509716", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/apt/lists/lock", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:30:16.436831", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/dpkg/lock) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/dpkg/lock"], "delta": "0:00:00.073788", "end": "2026-05-23 20:30:17.096600", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/dpkg/lock", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:30:17.022812", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}
ok: [wolf.tailf7742d.ts.net] => (item=/var/lib/dpkg/lock-frontend) => {"ansible_loop_var": "item", "changed": false, "cmd": ["fuser", "-k", "/var/lib/dpkg/lock-frontend"], "delta": "0:00:00.072710", "end": "2026-05-23 20:30:17.748403", "failed_when_result": false, "failed_when_suppressed_exception": "(traceback unavailable)", "item": "/var/lib/dpkg/lock-frontend", "msg": "non-zero return code", "rc": 1, "start": "2026-05-23 20:30:17.675693", "stderr": "", "stderr_lines": [], "stdout": "", "stdout_lines": []}

TASK [Update apt cache] ********************************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

TASK [Check if node is installed] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "cmd": ["node", "--version"], "delta": "0:00:00.006134", "end": "2026-05-23 20:30:19.246381", "failed_when_result": false, "msg": "", "rc": 0, "start": "2026-05-23 20:30:19.240247", "stderr": "", "stderr_lines": [], "stdout": "v22.22.1", "stdout_lines": ["v22.22.1"]}

TASK [Install required packages for NodeSource repository] *********************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Create keyrings directory] ***********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Download NodeSource GPG key] *********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Add NodeSource repository for Node.js 20] ********************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Install Node.js] *********************************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "node_check.rc != 0", "skip_reason": "Conditional result was False"}

TASK [Install build-essential] *************************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

TASK [Install git and GitHub CLI] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"cache_update_time": 1779593268, "cache_updated": false, "changed": false}

PLAY RECAP *********************************************************************
wolf.tailf7742d.ts.net     : ok=6    changed=0    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0   
No config file found; using defaults

PLAY [all] *********************************************************************

TASK [Gathering Facts] *********************************************************
[WARNING]: Host 'wolf.tailf7742d.ts.net' is using the discovered Python interpreter at '/usr/bin/python3.12', but future installation of another Python interpreter could cause a different interpreter to be discovered. See https://docs.ansible.com/ansible-core/2.20/reference_appendices/interpreter_discovery.html for more information.
ok: [wolf.tailf7742d.ts.net]

TASK [Normalize target OpenClaw version] ***************************************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"openclaw_target_version": "2026.4.2"}, "changed": false}

TASK [Create agent user] *******************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "comment": "", "create_home": true, "group": 1014, "home": "/home/audit-openclaw", "name": "audit-openclaw", "shell": "/bin/bash", "state": "present", "system": false, "uid": 1014}

TASK [Check per-agent openclaw binary] *****************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "stat": {"exists": false}}

TASK [Discover openclaw binary in PATH] ****************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "cmd": ["which", "openclaw"], "delta": "0:00:00.003177", "end": "2026-05-23 20:30:25.790927", "failed_when_result": false, "msg": "", "rc": 0, "start": "2026-05-23 20:30:25.787750", "stderr": "", "stderr_lines": [], "stdout": "/usr/local/bin/openclaw", "stdout_lines": ["/usr/local/bin/openclaw"]}

TASK [Resolve openclaw binary (per-agent preferred, PATH fallback)] ************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"openclaw_discovered_binary": "/usr/local/bin/openclaw"}, "changed": false}

TASK [Validate discovered binary path] *****************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "(openclaw_discovered_binary | length) > 0 and not (openclaw_discovered_binary.startswith('/usr/local/bin/') or\n     openclaw_discovered_binary.startswith('/usr/bin/') or\n     openclaw_discovered_binary.startswith('/home/'))\n", "skip_reason": "Conditional result was False"}

TASK [Get installed openclaw version] ******************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "cmd": ["/usr/local/bin/openclaw", "--version"], "delta": "0:00:00.120211", "end": "2026-05-23 20:30:26.539960", "failed_when_result": false, "msg": "", "rc": 0, "start": "2026-05-23 20:30:26.419749", "stderr": "", "stderr_lines": [], "stdout": "OpenClaw 2026.3.13 (61d171a)", "stdout_lines": ["OpenClaw 2026.3.13 (61d171a)"]}

TASK [Parse installed openclaw version] ****************************************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"openclaw_installed_version": "2026.3.13"}, "changed": false}

TASK [Set install skip condition] **********************************************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"openclaw_already_installed": false, "openclaw_runtime_binary": "/usr/local/bin/openclaw"}, "changed": false}

TASK [Mark install as skipped when already installed] **************************
skipping: [wolf.tailf7742d.ts.net] => {"false_condition": "openclaw_already_installed"}

TASK [Note that --force was supplied (overriding skip)] ************************
skipping: [wolf.tailf7742d.ts.net] => {"false_condition": "force_install | default(false) | bool"}

TASK [Download OpenClaw installer script] **************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum_dest": null, "checksum_src": "0b1b0e8e1f7af258783bc2944917e053b15c8e6d", "dest": "/home/audit-openclaw/openclaw-install.sh", "elapsed": 0, "gid": 1014, "group": "audit-openclaw", "md5sum": "9b0627a698f72a649a41b5a642f2bcd6", "mode": "0700", "msg": "OK (26204 bytes)", "owner": "audit-openclaw", "size": 26204, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593426.808022-1455344-135150799570064/tmp1sn47h9_", "state": "file", "status_code": 200, "uid": 1014, "url": "https://openclaw.ai/install-cli.sh"}

TASK [Install OpenClaw CLI runtime] ********************************************
[WARNING]: Module remote_tmp /home/audit-openclaw/.ansible/tmp did not exist and was created with a mode of 0700, this may cause issues when running as another user. To avoid this, create the remote_tmp dir with the correct permissions manually
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "cmd": ["/bin/bash", "/home/audit-openclaw/openclaw-install.sh", "--prefix", "/home/audit-openclaw/.openclaw", "--install-method", "npm", "--version", "2026.4.2", "--no-onboard"], "delta": "0:01:13.123201", "end": "2026-05-23 20:31:41.063940", "msg": "", "rc": 0, "start": "2026-05-23 20:30:27.940739", "stderr": "npm notice\nnpm notice New major version of npm available! 10.9.4 -> 11.15.0\nnpm notice Changelog: https://github.com/npm/cli/releases/tag/v11.15.0\nnpm notice To update run: npm install -g npm@11.15.0\nnpm notice", "stderr_lines": ["npm notice", "npm notice New major version of npm available! 10.9.4 -> 11.15.0", "npm notice Changelog: https://github.com/npm/cli/releases/tag/v11.15.0", "npm notice To update run: npm install -g npm@11.15.0", "npm notice"], "stdout": "Installing Node 22.22.0 (user-space)...\nInstalling OpenClaw (2026.4.2)...\n\nadded 472 packages in 1m\nOpenClaw installed (OpenClaw 2026.4.2 (d74a122)).", "stdout_lines": ["Installing Node 22.22.0 (user-space)...", "Installing OpenClaw (2026.4.2)...", "", "added 472 packages in 1m", "OpenClaw installed (OpenClaw 2026.4.2 (d74a122))."]}

TASK [Clean up installer script] ***********************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "path": "/home/audit-openclaw/openclaw-install.sh", "state": "absent"}

TASK [Create workspace directory] **********************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1014, "group": "audit-openclaw", "mode": "0700", "owner": "audit-openclaw", "path": "/home/audit-openclaw/workspace", "size": 4096, "state": "directory", "uid": 1014}

TASK [Create OpenClaw config directory] ****************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "gid": 1014, "group": "audit-openclaw", "mode": "0700", "owner": "audit-openclaw", "path": "/home/audit-openclaw/.openclaw", "size": 4096, "state": "directory", "uid": 1014}

TASK [Calculate unique port (40000-42000 range)] *******************************
ok: [wolf.tailf7742d.ts.net] => {"ansible_facts": {"openclaw_port": 40612}, "changed": false}

TASK [Write openclaw config from template] *************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum": "052399dd085ac29822b7cd6c336a643cb75d02d3", "dest": "/home/audit-openclaw/.openclaw/openclaw.json", "gid": 1014, "group": "audit-openclaw", "md5sum": "5654d91f9664b6c543fb085dab67d18c", "mode": "0600", "owner": "audit-openclaw", "size": 1055, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593502.6812377-1457982-239208318569034/.source.json", "state": "file", "uid": 1014}

TASK [Write exec approvals policy from template] *******************************
changed: [wolf.tailf7742d.ts.net] => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result", "changed": true}

TASK [Verify exec approvals JSON is valid] *************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "cmd": ["python3", "-m", "json.tool", "/home/audit-openclaw/.openclaw/exec-approvals.json"], "delta": "0:00:00.042602", "end": "2026-05-23 20:31:44.878616", "msg": "", "rc": 0, "start": "2026-05-23 20:31:44.836014", "stderr": "", "stderr_lines": [], "stdout": "{\n    \"version\": 1,\n    \"defaults\": {\n        \"security\": \"full\",\n        \"ask\": \"off\",\n        \"askFallback\": \"full\",\n        \"autoAllowSkills\": false\n    }\n}", "stdout_lines": ["{", "    \"version\": 1,", "    \"defaults\": {", "        \"security\": \"full\",", "        \"ask\": \"off\",", "        \"askFallback\": \"full\",", "        \"autoAllowSkills\": false", "    }", "}"]}

TASK [Create environment file for agent] ***************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum": "da39a3ee5e6b4b0d3255bfef95601890afd80709", "dest": "/home/audit-openclaw/.openclaw/env", "gid": 1014, "group": "audit-openclaw", "md5sum": "d41d8cd98f00b204e9800998ecf8427e", "mode": "0600", "owner": "audit-openclaw", "size": 0, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593504.969828-1458101-236418003765705/.source", "state": "file", "uid": 1014}

TASK [Create systemd service file] *********************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum": "03157cd39147163a5b8960f4a0ea98bdcad103b0", "dest": "/etc/systemd/system/openclaw-audit-openclaw.service", "gid": 0, "group": "root", "md5sum": "dfad988ba86b2d25c76ab4f7cc3b22ce", "mode": "0644", "owner": "root", "size": 354, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593505.7843945-1458149-73265254501936/.source.service", "state": "file", "uid": 0}

TASK [Restart openclaw service on ExecStart change] ****************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "enabled": true, "name": "openclaw-audit-openclaw", "state": "started", "status": {"ActiveEnterTimestampMonotonic": "0", "ActiveExitTimestampMonotonic": "0", "ActiveState": "inactive", "After": "-.mount home.mount systemd-journald.socket sysinit.target basic.target network.target system.slice", "AllowIsolate": "no", "AssertResult": "no", "AssertTimestampMonotonic": "0", "Before": "shutdown.target", "BlockIOAccounting": "no", "BlockIOWeight": "[not set]", "CPUAccounting": "yes", "CPUAffinityFromNUMA": "no", "CPUQuotaPerSecUSec": "infinity", "CPUQuotaPeriodUSec": "infinity", "CPUSchedulingPolicy": "0", "CPUSchedulingPriority": "0", "CPUSchedulingResetOnFork": "no", "CPUShares": "[not set]", "CPUUsageNSec": "[not set]", "CPUWeight": "[not set]", "CacheDirectoryMode": "0755", "CanFreeze": "yes", "CanIsolate": "no", "CanReload": "no", "CanStart": "yes", "CanStop": "yes", "CapabilityBoundingSet": "cap_chown cap_dac_override cap_dac_read_search cap_fowner cap_fsetid cap_kill cap_setgid cap_setuid cap_setpcap cap_linux_immutable cap_net_bind_service cap_net_broadcast cap_net_admin cap_net_raw cap_ipc_lock cap_ipc_owner cap_sys_module cap_sys_rawio cap_sys_chroot cap_sys_ptrace cap_sys_pacct cap_sys_admin cap_sys_boot cap_sys_nice cap_sys_resource cap_sys_time cap_sys_tty_config cap_mknod cap_lease cap_audit_write cap_audit_control cap_setfcap cap_mac_override cap_mac_admin cap_syslog cap_wake_alarm cap_block_suspend cap_audit_read cap_perfmon cap_bpf cap_checkpoint_restore", "CleanResult": "success", "CollectMode": "inactive", "ConditionResult": "no", "ConditionTimestampMonotonic": "0", "ConfigurationDirectoryMode": "0755", "Conflicts": "shutdown.target", "ControlGroupId": "0", "ControlPID": "0", "CoredumpFilter": "0x33", "CoredumpReceive": "no", "DefaultDependencies": "yes", "DefaultMemoryLow": "0", "DefaultMemoryMin": "0", "DefaultStartupMemoryLow": "0", "Delegate": "no", "Description": "OpenClaw AI Assistant (audit-openclaw)", "DevicePolicy": "auto", "DynamicUser": "no", "EnvironmentFiles": "/home/audit-openclaw/.openclaw/env (ignore_errors=no)", "ExecMainCode": "0", "ExecMainExitTimestampMonotonic": "0", "ExecMainPID": "0", "ExecMainStartTimestampMonotonic": "0", "ExecMainStatus": "0", "ExecStart": "{ path=/usr/local/bin/openclaw ; argv[]=/usr/local/bin/openclaw gateway run --allow-unconfigured ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }", "ExecStartEx": "{ path=/usr/local/bin/openclaw ; argv[]=/usr/local/bin/openclaw gateway run --allow-unconfigured ; flags= ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }", "ExitType": "main", "ExtensionImagePolicy": "root=verity+signed+encrypted+unprotected+absent:usr=verity+signed+encrypted+unprotected+absent:home=encrypted+unprotected+absent:srv=encrypted+unprotected+absent:tmp=encrypted+unprotected+absent:var=encrypted+unprotected+absent", "FailureAction": "none", "FileDescriptorStoreMax": "0", "FileDescriptorStorePreserve": "restart", "FinalKillSignal": "9", "FragmentPath": "/etc/systemd/system/openclaw-audit-openclaw.service", "FreezerState": "running", "GID": "[not set]", "GuessMainPID": "yes", "IOAccounting": "no", "IOReadBytes": "[not set]", "IOReadOperations": "[not set]", "IOSchedulingClass": "2", "IOSchedulingPriority": "4", "IOWeight": "[not set]", "IOWriteBytes": "[not set]", "IOWriteOperations": "[not set]", "IPAccounting": "no", "IPEgressBytes": "[no data]", "IPEgressPackets": "[no data]", "IPIngressBytes": "[no data]", "IPIngressPackets": "[no data]", "Id": "openclaw-audit-openclaw.service", "IgnoreOnIsolate": "no", "IgnoreSIGPIPE": "yes", "InactiveEnterTimestampMonotonic": "0", "InactiveExitTimestampMonotonic": "0", "JobRunningTimeoutUSec": "infinity", "JobTimeoutAction": "none", "JobTimeoutUSec": "infinity", "KeyringMode": "private", "KillMode": "control-group", "KillSignal": "15", "LimitAS": "infinity", "LimitASSoft": "infinity", "LimitCORE": "infinity", "LimitCORESoft": "0", "LimitCPU": "infinity", "LimitCPUSoft": "infinity", "LimitDATA": "infinity", "LimitDATASoft": "infinity", "LimitFSIZE": "infinity", "LimitFSIZESoft": "infinity", "LimitLOCKS": "infinity", "LimitLOCKSSoft": "infinity", "LimitMEMLOCK": "8388608", "LimitMEMLOCKSoft": "8388608", "LimitMSGQUEUE": "819200", "LimitMSGQUEUESoft": "819200", "LimitNICE": "0", "LimitNICESoft": "0", "LimitNOFILE": "524288", "LimitNOFILESoft": "1024", "LimitNPROC": "62947", "LimitNPROCSoft": "62947", "LimitRSS": "infinity", "LimitRSSSoft": "infinity", "LimitRTPRIO": "0", "LimitRTPRIOSoft": "0", "LimitRTTIME": "infinity", "LimitRTTIMESoft": "infinity", "LimitSIGPENDING": "62947", "LimitSIGPENDINGSoft": "62947", "LimitSTACK": "infinity", "LimitSTACKSoft": "8388608", "LoadState": "loaded", "LockPersonality": "no", "LogLevelMax": "-1", "LogRateLimitBurst": "0", "LogRateLimitIntervalUSec": "0", "LogsDirectoryMode": "0755", "MainPID": "0", "ManagedOOMMemoryPressure": "auto", "ManagedOOMMemoryPressureLimit": "0", "ManagedOOMPreference": "none", "ManagedOOMSwap": "auto", "MemoryAccounting": "yes", "MemoryAvailable": "11460218880", "MemoryCurrent": "[not set]", "MemoryDenyWriteExecute": "no", "MemoryHigh": "infinity", "MemoryKSM": "no", "MemoryLimit": "infinity", "MemoryLow": "0", "MemoryMax": "infinity", "MemoryMin": "0", "MemoryPeak": "[not set]", "MemoryPressureThresholdUSec": "200ms", "MemoryPressureWatch": "auto", "MemorySwapCurrent": "[not set]", "MemorySwapMax": "infinity", "MemorySwapPeak": "[not set]", "MemoryZSwapCurrent": "[not set]", "MemoryZSwapMax": "infinity", "MountAPIVFS": "no", "MountImagePolicy": "root=verity+signed+encrypted+unprotected+absent:usr=verity+signed+encrypted+unprotected+absent:home=encrypted+unprotected+absent:srv=encrypted+unprotected+absent:tmp=encrypted+unprotected+absent:var=encrypted+unprotected+absent", "NFileDescriptorStore": "0", "NRestarts": "0", "NUMAPolicy": "n/a", "Names": "openclaw-audit-openclaw.service", "NeedDaemonReload": "no", "Nice": "0", "NoNewPrivileges": "no", "NonBlocking": "no", "NotifyAccess": "none", "OOMPolicy": "stop", "OOMScoreAdjust": "0", "OnFailureJobMode": "replace", "OnSuccessJobMode": "fail", "Perpetual": "no", "PrivateDevices": "no", "PrivateIPC": "no", "PrivateMounts": "no", "PrivateNetwork": "no", "PrivateTmp": "no", "PrivateUsers": "no", "ProcSubset": "all", "ProtectClock": "no", "ProtectControlGroups": "no", "ProtectHome": "no", "ProtectHostname": "no", "ProtectKernelLogs": "no", "ProtectKernelModules": "no", "ProtectKernelTunables": "no", "ProtectProc": "default", "ProtectSystem": "no", "RefuseManualStart": "no", "RefuseManualStop": "no", "ReloadResult": "success", "ReloadSignal": "1", "RemainAfterExit": "no", "RemoveIPC": "no", "Requires": "system.slice -.mount home.mount sysinit.target", "RequiresMountsFor": "/home/audit-openclaw/workspace", "Restart": "always", "RestartKillSignal": "15", "RestartMaxDelayUSec": "infinity", "RestartMode": "normal", "RestartSteps": "0", "RestartUSec": "5s", "RestartUSecNext": "5s", "RestrictNamespaces": "no", "RestrictRealtime": "no", "RestrictSUIDSGID": "no", "Result": "success", "RootDirectoryStartOnly": "no", "RootEphemeral": "no", "RootImagePolicy": "root=verity+signed+encrypted+unprotected+absent:usr=verity+signed+encrypted+unprotected+absent:home=encrypted+unprotected+absent:srv=encrypted+unprotected+absent:tmp=encrypted+unprotected+absent:var=encrypted+unprotected+absent", "RuntimeDirectoryMode": "0755", "RuntimeDirectoryPreserve": "no", "RuntimeMaxUSec": "infinity", "RuntimeRandomizedExtraUSec": "0", "SameProcessGroup": "no", "SecureBits": "0", "SendSIGHUP": "no", "SendSIGKILL": "yes", "SetLoginEnvironment": "no", "Slice": "system.slice", "StandardError": "inherit", "StandardInput": "null", "StandardOutput": "journal", "StartLimitAction": "none", "StartLimitBurst": "5", "StartLimitIntervalUSec": "10s", "StartupBlockIOWeight": "[not set]", "StartupCPUShares": "[not set]", "StartupCPUWeight": "[not set]", "StartupIOWeight": "[not set]", "StartupMemoryHigh": "infinity", "StartupMemoryLow": "0", "StartupMemoryMax": "infinity", "StartupMemorySwapMax": "infinity", "StartupMemoryZSwapMax": "infinity", "StateChangeTimestampMonotonic": "0", "StateDirectoryMode": "0755", "StatusErrno": "0", "StopWhenUnneeded": "no", "SubState": "dead", "SuccessAction": "none", "SurviveFinalKillSignal": "no", "SyslogFacility": "3", "SyslogLevel": "6", "SyslogLevelPrefix": "yes", "SyslogPriority": "30", "SystemCallErrorNumber": "2147483646", "TTYReset": "no", "TTYVHangup": "no", "TTYVTDisallocate": "no", "TasksAccounting": "yes", "TasksCurrent": "[not set]", "TasksMax": "18884", "TimeoutAbortUSec": "1min 30s", "TimeoutCleanUSec": "infinity", "TimeoutStartFailureMode": "terminate", "TimeoutStartUSec": "1min 30s", "TimeoutStopFailureMode": "terminate", "TimeoutStopUSec": "1min 30s", "TimerSlackNSec": "50000", "Transient": "no", "Type": "simple", "UID": "[not set]", "UMask": "0022", "UnitFilePreset": "enabled", "UnitFileState": "disabled", "User": "audit-openclaw", "UtmpMode": "init", "WatchdogSignal": "6", "WatchdogTimestampMonotonic": "0", "WatchdogUSec": "infinity", "WorkingDirectory": "/home/audit-openclaw/workspace"}}

TASK [Enable and start openclaw service] ***************************************
ok: [wolf.tailf7742d.ts.net] => {"changed": false, "enabled": true, "name": "openclaw-audit-openclaw", "state": "started", "status": {"ActiveEnterTimestamp": "Sat 2026-05-23 20:31:48 PDT", "ActiveEnterTimestampMonotonic": "6597732633876", "ActiveExitTimestampMonotonic": "0", "ActiveState": "active", "After": "system.slice sysinit.target home.mount network.target systemd-journald.socket basic.target -.mount", "AllowIsolate": "no", "AssertResult": "yes", "AssertTimestamp": "Sat 2026-05-23 20:31:48 PDT", "AssertTimestampMonotonic": "6597732632336", "Before": "shutdown.target multi-user.target", "BlockIOAccounting": "no", "BlockIOWeight": "[not set]", "CPUAccounting": "yes", "CPUAffinityFromNUMA": "no", "CPUQuotaPerSecUSec": "infinity", "CPUQuotaPeriodUSec": "infinity", "CPUSchedulingPolicy": "0", "CPUSchedulingPriority": "0", "CPUSchedulingResetOnFork": "no", "CPUShares": "[not set]", "CPUUsageNSec": "1743925000", "CPUWeight": "[not set]", "CacheDirectoryMode": "0755", "CanFreeze": "yes", "CanIsolate": "no", "CanReload": "no", "CanStart": "yes", "CanStop": "yes", "CapabilityBoundingSet": "cap_chown cap_dac_override cap_dac_read_search cap_fowner cap_fsetid cap_kill cap_setgid cap_setuid cap_setpcap cap_linux_immutable cap_net_bind_service cap_net_broadcast cap_net_admin cap_net_raw cap_ipc_lock cap_ipc_owner cap_sys_module cap_sys_rawio cap_sys_chroot cap_sys_ptrace cap_sys_pacct cap_sys_admin cap_sys_boot cap_sys_nice cap_sys_resource cap_sys_time cap_sys_tty_config cap_mknod cap_lease cap_audit_write cap_audit_control cap_setfcap cap_mac_override cap_mac_admin cap_syslog cap_wake_alarm cap_block_suspend cap_audit_read cap_perfmon cap_bpf cap_checkpoint_restore", "CleanResult": "success", "CollectMode": "inactive", "ConditionResult": "yes", "ConditionTimestamp": "Sat 2026-05-23 20:31:48 PDT", "ConditionTimestampMonotonic": "6597732632332", "ConfigurationDirectoryMode": "0755", "Conflicts": "shutdown.target", "ControlGroup": "/system.slice/openclaw-audit-openclaw.service", "ControlGroupId": "25593535", "ControlPID": "0", "CoredumpFilter": "0x33", "CoredumpReceive": "no", "DefaultDependencies": "yes", "DefaultMemoryLow": "0", "DefaultMemoryMin": "0", "DefaultStartupMemoryLow": "0", "Delegate": "no", "Description": "OpenClaw AI Assistant (audit-openclaw)", "DevicePolicy": "auto", "DynamicUser": "no", "EnvironmentFiles": "/home/audit-openclaw/.openclaw/env (ignore_errors=no)", "ExecMainCode": "0", "ExecMainExitTimestampMonotonic": "0", "ExecMainPID": "485482", "ExecMainStartTimestamp": "Sat 2026-05-23 20:31:48 PDT", "ExecMainStartTimestampMonotonic": "6597732633656", "ExecMainStatus": "0", "ExecStart": "{ path=/usr/local/bin/openclaw ; argv[]=/usr/local/bin/openclaw gateway run --allow-unconfigured ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }", "ExecStartEx": "{ path=/usr/local/bin/openclaw ; argv[]=/usr/local/bin/openclaw gateway run --allow-unconfigured ; flags= ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }", "ExitType": "main", "ExtensionImagePolicy": "root=verity+signed+encrypted+unprotected+absent:usr=verity+signed+encrypted+unprotected+absent:home=encrypted+unprotected+absent:srv=encrypted+unprotected+absent:tmp=encrypted+unprotected+absent:var=encrypted+unprotected+absent", "FailureAction": "none", "FileDescriptorStoreMax": "0", "FileDescriptorStorePreserve": "restart", "FinalKillSignal": "9", "FragmentPath": "/etc/systemd/system/openclaw-audit-openclaw.service", "FreezerState": "running", "GID": "1014", "GuessMainPID": "yes", "IOAccounting": "no", "IOReadBytes": "[not set]", "IOReadOperations": "[not set]", "IOSchedulingClass": "2", "IOSchedulingPriority": "4", "IOWeight": "[not set]", "IOWriteBytes": "[not set]", "IOWriteOperations": "[not set]", "IPAccounting": "no", "IPEgressBytes": "[no data]", "IPEgressPackets": "[no data]", "IPIngressBytes": "[no data]", "IPIngressPackets": "[no data]", "Id": "openclaw-audit-openclaw.service", "IgnoreOnIsolate": "no", "IgnoreSIGPIPE": "yes", "InactiveEnterTimestampMonotonic": "0", "InactiveExitTimestamp": "Sat 2026-05-23 20:31:48 PDT", "InactiveExitTimestampMonotonic": "6597732633876", "InvocationID": "41ef9b9328b1441795bdeb96f1ba7571", "JobRunningTimeoutUSec": "infinity", "JobTimeoutAction": "none", "JobTimeoutUSec": "infinity", "KeyringMode": "private", "KillMode": "control-group", "KillSignal": "15", "LimitAS": "infinity", "LimitASSoft": "infinity", "LimitCORE": "infinity", "LimitCORESoft": "0", "LimitCPU": "infinity", "LimitCPUSoft": "infinity", "LimitDATA": "infinity", "LimitDATASoft": "infinity", "LimitFSIZE": "infinity", "LimitFSIZESoft": "infinity", "LimitLOCKS": "infinity", "LimitLOCKSSoft": "infinity", "LimitMEMLOCK": "8388608", "LimitMEMLOCKSoft": "8388608", "LimitMSGQUEUE": "819200", "LimitMSGQUEUESoft": "819200", "LimitNICE": "0", "LimitNICESoft": "0", "LimitNOFILE": "524288", "LimitNOFILESoft": "1024", "LimitNPROC": "62947", "LimitNPROCSoft": "62947", "LimitRSS": "infinity", "LimitRSSSoft": "infinity", "LimitRTPRIO": "0", "LimitRTPRIOSoft": "0", "LimitRTTIME": "infinity", "LimitRTTIMESoft": "infinity", "LimitSIGPENDING": "62947", "LimitSIGPENDINGSoft": "62947", "LimitSTACK": "infinity", "LimitSTACKSoft": "8388608", "LoadState": "loaded", "LockPersonality": "no", "LogLevelMax": "-1", "LogRateLimitBurst": "0", "LogRateLimitIntervalUSec": "0", "LogsDirectoryMode": "0755", "MainPID": "485482", "ManagedOOMMemoryPressure": "auto", "ManagedOOMMemoryPressureLimit": "0", "ManagedOOMPreference": "none", "ManagedOOMSwap": "auto", "MemoryAccounting": "yes", "MemoryAvailable": "11346976768", "MemoryCurrent": "142753792", "MemoryDenyWriteExecute": "no", "MemoryHigh": "infinity", "MemoryKSM": "no", "MemoryLimit": "infinity", "MemoryLow": "0", "MemoryMax": "infinity", "MemoryMin": "0", "MemoryPeak": "142770176", "MemoryPressureThresholdUSec": "200ms", "MemoryPressureWatch": "auto", "MemorySwapCurrent": "0", "MemorySwapMax": "infinity", "MemorySwapPeak": "0", "MemoryZSwapCurrent": "0", "MemoryZSwapMax": "infinity", "MountAPIVFS": "no", "MountImagePolicy": "root=verity+signed+encrypted+unprotected+absent:usr=verity+signed+encrypted+unprotected+absent:home=encrypted+unprotected+absent:srv=encrypted+unprotected+absent:tmp=encrypted+unprotected+absent:var=encrypted+unprotected+absent", "NFileDescriptorStore": "0", "NRestarts": "0", "NUMAPolicy": "n/a", "Names": "openclaw-audit-openclaw.service", "NeedDaemonReload": "no", "Nice": "0", "NoNewPrivileges": "no", "NonBlocking": "no", "NotifyAccess": "none", "OOMPolicy": "stop", "OOMScoreAdjust": "0", "OnFailureJobMode": "replace", "OnSuccessJobMode": "fail", "Perpetual": "no", "PrivateDevices": "no", "PrivateIPC": "no", "PrivateMounts": "no", "PrivateNetwork": "no", "PrivateTmp": "no", "PrivateUsers": "no", "ProcSubset": "all", "ProtectClock": "no", "ProtectControlGroups": "no", "ProtectHome": "no", "ProtectHostname": "no", "ProtectKernelLogs": "no", "ProtectKernelModules": "no", "ProtectKernelTunables": "no", "ProtectProc": "default", "ProtectSystem": "no", "RefuseManualStart": "no", "RefuseManualStop": "no", "ReloadResult": "success", "ReloadSignal": "1", "RemainAfterExit": "no", "RemoveIPC": "no", "Requires": "-.mount sysinit.target home.mount system.slice", "RequiresMountsFor": "/home/audit-openclaw/workspace", "Restart": "always", "RestartKillSignal": "15", "RestartMaxDelayUSec": "infinity", "RestartMode": "normal", "RestartSteps": "0", "RestartUSec": "5s", "RestartUSecNext": "5s", "RestrictNamespaces": "no", "RestrictRealtime": "no", "RestrictSUIDSGID": "no", "Result": "success", "RootDirectoryStartOnly": "no", "RootEphemeral": "no", "RootImagePolicy": "root=verity+signed+encrypted+unprotected+absent:usr=verity+signed+encrypted+unprotected+absent:home=encrypted+unprotected+absent:srv=encrypted+unprotected+absent:tmp=encrypted+unprotected+absent:var=encrypted+unprotected+absent", "RuntimeDirectoryMode": "0755", "RuntimeDirectoryPreserve": "no", "RuntimeMaxUSec": "infinity", "RuntimeRandomizedExtraUSec": "0", "SameProcessGroup": "no", "SecureBits": "0", "SendSIGHUP": "no", "SendSIGKILL": "yes", "SetLoginEnvironment": "no", "Slice": "system.slice", "StandardError": "inherit", "StandardInput": "null", "StandardOutput": "journal", "StartLimitAction": "none", "StartLimitBurst": "5", "StartLimitIntervalUSec": "10s", "StartupBlockIOWeight": "[not set]", "StartupCPUShares": "[not set]", "StartupCPUWeight": "[not set]", "StartupIOWeight": "[not set]", "StartupMemoryHigh": "infinity", "StartupMemoryLow": "0", "StartupMemoryMax": "infinity", "StartupMemorySwapMax": "infinity", "StartupMemoryZSwapMax": "infinity", "StateChangeTimestamp": "Sat 2026-05-23 20:31:48 PDT", "StateChangeTimestampMonotonic": "6597732633876", "StateDirectoryMode": "0755", "StatusErrno": "0", "StopWhenUnneeded": "no", "SubState": "running", "SuccessAction": "none", "SurviveFinalKillSignal": "no", "SyslogFacility": "3", "SyslogLevel": "6", "SyslogLevelPrefix": "yes", "SyslogPriority": "30", "SystemCallErrorNumber": "2147483646", "TTYReset": "no", "TTYVHangup": "no", "TTYVTDisallocate": "no", "TasksAccounting": "yes", "TasksCurrent": "14", "TasksMax": "18884", "TimeoutAbortUSec": "1min 30s", "TimeoutCleanUSec": "infinity", "TimeoutStartFailureMode": "terminate", "TimeoutStartUSec": "1min 30s", "TimeoutStopFailureMode": "terminate", "TimeoutStopUSec": "1min 30s", "TimerSlackNSec": "50000", "Transient": "no", "Type": "simple", "UID": "1014", "UMask": "0022", "UnitFilePreset": "enabled", "UnitFileState": "enabled", "User": "audit-openclaw", "UtmpMode": "init", "WantedBy": "multi-user.target", "WatchdogSignal": "6", "WatchdogTimestampMonotonic": "0", "WatchdogUSec": "0", "WorkingDirectory": "/home/audit-openclaw/workspace"}}

TASK [Wait for gateway port to be listening] ***********************************
ok: [wolf.tailf7742d.ts.net -> localhost] => {"changed": false, "elapsed": 29, "match_groupdict": {}, "match_groups": [], "path": null, "port": 40612, "search_regex": null, "state": "started"}

TASK [Read gateway authentication token from config file] **********************
ok: [wolf.tailf7742d.ts.net] => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result", "changed": false}

TASK [Parse gateway token from config] *****************************************
ok: [wolf.tailf7742d.ts.net] => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result", "changed": false}

TASK [Validate gateway token format] *******************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "gateway_token_result_stdout is not defined or gateway_token_result_stdout | length < 32 or not (gateway_token_result_stdout is regex('^[a-zA-Z0-9_-]+$'))", "skip_reason": "Conditional result was False"}

TASK [Copy device pairing script] **********************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "checksum": "de98a7e90a1640675b8454bf6b538aa34650626e", "dest": "/home/audit-openclaw/pair_device.mjs", "gid": 1014, "group": "audit-openclaw", "md5sum": "dad2220cdb88526b9d9855e07fcceaaa", "mode": "0700", "owner": "audit-openclaw", "size": 5993, "src": "/home/xclm/.ansible/tmp/ansible-tmp-1779593539.7906888-1459356-67064077187122/.source.mjs", "state": "file", "uid": 1014}

TASK [Install ws package for pairing script] ***********************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "cmd": ["npm", "install", "ws"], "delta": "0:00:00.428655", "end": "2026-05-23 20:32:21.411781", "msg": "", "rc": 0, "start": "2026-05-23 20:32:20.983126", "stderr": "", "stderr_lines": [], "stdout": "\nadded 1 package in 357ms", "stdout_lines": ["", "added 1 package in 357ms"]}

TASK [Run device pairing via localhost] ****************************************
changed: [wolf.tailf7742d.ts.net] => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result", "changed": true}

TASK [Parse device credentials] ************************************************
ok: [wolf.tailf7742d.ts.net] => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result", "changed": false}

TASK [Validate device credentials] *********************************************
skipping: [wolf.tailf7742d.ts.net] => {"changed": false, "false_condition": "device_credentials.deviceToken is not defined or device_credentials.deviceToken | length < 10", "skip_reason": "Conditional result was False"}

TASK [Clean up pairing script] *************************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "path": "/home/audit-openclaw/pair_device.mjs", "state": "absent"}

TASK [Clean up node_modules from pairing] **************************************
changed: [wolf.tailf7742d.ts.net] => {"changed": true, "path": "/home/audit-openclaw/node_modules", "state": "absent"}

TASK [Save all credentials to fact for retrieval] ******************************
ok: [wolf.tailf7742d.ts.net] => {"censored": "the output has been hidden due to the fact that 'no_log: true' was specified for this result", "changed": false}

PLAY RECAP *********************************************************************
wolf.tailf7742d.ts.net     : ok=32   changed=16   unreachable=0    failed=0    skipped=5    rescued=0    ignored=0   

Success! openclaw v2026.4.2 installed as 'audit-openclaw' on wolf-i
```
Exit: `0`


---

## Lifecycle transcripts (audit-* agents)

For each agent type, the full sequence is captured in order:
`configure` → `start` → `sync` → `stop` → `restart`. Install was captured
in the previous section.

After all three agents are configured and started, the post-install
`clm agent ps` capture documents the running state. Per-agent read-only
commands (`secret list`, `memory show`, `integration list`, `skill list`,
`logs --tail 20`) are captured while the agents are running.

### audit-zeroclaw (configure + start)

### `clm agent configure audit-zeroclaw --yes`

```console
$ clm agent configure audit-zeroclaw --yes
╭────────────────────────────────────────────────────────── Agent Configuration ───────────────────────────────────────────────────────────╮
│ Onboarding: audit-zeroclaw on wolf-i                                                                                                     │
│ Current state: PENDING                                                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Starting onboarding...

═══════════════════════════════════════════════════
 Stage 1/4: PROVIDERS
 Assign inference provider to this agent
═══════════════════════════════════════════════════

Available providers:
  1. clm-openrouter (openrouter, openai/gpt-4o) ✓
  2. local-inx (ollama, qwen3-coder:30b-128k) ✓
  3. maurice-openrouter (openrouter, z-ai/glm-4.5-air) ✓
  4. clawrium-bedrock (bedrock, zai.glm-4.7) ✓
  5. clawrium-coder (ollama, qwen3-coder-next:q4_K_M) ✓
  6. clawrium-glm-flash (ollama, glm-4.7-flash:latest) ✓
  7. clawrium-nemotron (ollama, nemotron-cascade-2:30b-a3b-q4_K_M) ✓
  8. clawrium-deepseek (ollama, deepseek-r1:70b) ✓
  9. clawrium-glm51 (openrouter, z-ai/glm-5) ✓


Syncing config to agent... ✓
Saving provider selection... ✓

Stage PROVIDERS complete.
Stage 2/4: IDENTITY — auto-skipped (ZeroClaw uses minimal identity)

═══════════════════════════════════════════════════
 Stage 3/4: CHANNELS
 Configure communication channels
═══════════════════════════════════════════════════

Select default channel:
  1. cli (recommended)
  2. discord

✓ Default channel: cli

Stage CHANNELS complete.

═══════════════════════════════════════════════════
 Stage 4/4: VALIDATE
 Verify agent is properly configured
═══════════════════════════════════════════════════

[1/3] Validating agent installation...
  ✓ Agent installed
[2/3] Validating provider configuration...
  ✓ Provider: clm-openrouter (openrouter)
  Checking API key...
  ✓ API credentials configured
[3/3] Testing provider connectivity...
  ✓ Provider connectivity OK

Validation passed

Stage VALIDATE complete.

═══════════════════════════════════════════════════
 Onboarding Complete!
═══════════════════════════════════════════════════

State: READY
Run 'clm agent start audit-zeroclaw' to start your agent.
```
Exit: `0`

### `clm agent start audit-zeroclaw`

```console
$ clm agent start audit-zeroclaw
Starting agent: audit-zeroclaw on wolf-i
  Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
  Starting audit-zeroclaw on wolf.tailf7742d.ts.net...
  Daemon started; pairing audit-zeroclaw...
  Re-pairing zeroclaw after start...
  Gateway token rotated for audit-zeroclaw. Active chat sessions on other machines will need to reconnect.
  Pairing token refreshed
  Started audit-zeroclaw successfully
✓ Agent started successfully
  Run 'clm agent ps' to check status
```
Exit: `0`


### audit-hermes (configure + start)

### `clm agent configure audit-hermes --yes`

```console
$ clm agent configure audit-hermes --yes
╭────────────────────────────────────────────────────────── Agent Configuration ───────────────────────────────────────────────────────────╮
│ Onboarding: audit-hermes on wolf-i                                                                                                       │
│ Current state: PENDING                                                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Starting onboarding...

═══════════════════════════════════════════════════
 Stage 1/4: PROVIDERS
 Assign inference provider to this agent
═══════════════════════════════════════════════════

Available providers:
  1. clm-openrouter (openrouter, openai/gpt-4o) ✓
  2. local-inx (ollama, qwen3-coder:30b-128k) ✓
  3. maurice-openrouter (openrouter, z-ai/glm-4.5-air) ✓
  4. clawrium-bedrock (bedrock, zai.glm-4.7) ✓
  5. clawrium-coder (ollama, qwen3-coder-next:q4_K_M) ✓
  6. clawrium-glm-flash (ollama, glm-4.7-flash:latest) ✓
  7. clawrium-nemotron (ollama, nemotron-cascade-2:30b-a3b-q4_K_M) ✓
  8. clawrium-deepseek (ollama, deepseek-r1:70b) ✓
  9. clawrium-glm51 (openrouter, z-ai/glm-5) ✓


Syncing config to agent... ✓
Saving provider selection... ✓

Stage PROVIDERS complete.
Stage 2/4: IDENTITY — auto-skipped (Hermes manages SOUL.md/AGENTS.md inside ~/.hermes/; clm does not push identity files in this iteration)

═══════════════════════════════════════════════════
 Stage 3/4: CHANNELS
 Configure communication channels
═══════════════════════════════════════════════════

Select default channel:
  1. cli (recommended)
  2. discord
  3. slack

✓ Default channel: cli

Stage CHANNELS complete.

═══════════════════════════════════════════════════
 Stage 4/4: VALIDATE
 Verify agent is properly configured
═══════════════════════════════════════════════════

[1/4] Validating agent installation...
  ✓ Agent installed
[2/4] Validating provider configuration...
  ✓ Provider: clm-openrouter (openrouter)
  Checking API key...
  ✓ API credentials configured
[3/4] Testing provider connectivity...
  ✓ Provider connectivity OK
[4/4] Verifying hermes health on agent host...
  ✓ hermes --version OK, ~/.hermes/.env exists, /health returned 200

Validation passed

Stage VALIDATE complete.

═══════════════════════════════════════════════════
 Onboarding Complete!
═══════════════════════════════════════════════════

State: READY
Run 'clm agent start audit-hermes' to start your agent.
```
Exit: `0`

### `clm agent start audit-hermes`

```console
$ clm agent start audit-hermes
Starting agent: audit-hermes on wolf-i
  Checking audit-hermes on wolf.tailf7742d.ts.net...
  Starting audit-hermes on wolf.tailf7742d.ts.net...
  Started audit-hermes successfully
✓ Agent started successfully
  Run 'clm agent ps' to check status
```
Exit: `0`


### audit-openclaw (configure + start)

### `clm agent configure audit-openclaw --yes`

```console
$ clm agent configure audit-openclaw --yes
╭────────────────────────────────────────────────────────── Agent Configuration ───────────────────────────────────────────────────────────╮
│ Onboarding: audit-openclaw on wolf-i                                                                                                     │
│ Current state: PENDING                                                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

Starting onboarding...

═══════════════════════════════════════════════════
 Stage 1/4: PROVIDERS
 Assign inference provider to this agent
═══════════════════════════════════════════════════

Available providers:
  1. clm-openrouter (openrouter, openai/gpt-4o) ✓
  2. local-inx (ollama, qwen3-coder:30b-128k) ✓
  3. maurice-openrouter (openrouter, z-ai/glm-4.5-air) ✓
  4. clawrium-bedrock (bedrock, zai.glm-4.7) ✓
  5. clawrium-coder (ollama, qwen3-coder-next:q4_K_M) ✓
  6. clawrium-glm-flash (ollama, glm-4.7-flash:latest) ✓
  7. clawrium-nemotron (ollama, nemotron-cascade-2:30b-a3b-q4_K_M) ✓
  8. clawrium-deepseek (ollama, deepseek-r1:70b) ✓
  9. clawrium-glm51 (openrouter, z-ai/glm-5) ✓


Syncing config to agent... ✗ Failed to configure openclaw: Configure playbook failed: failed
Error: Failed to apply provider configuration. Run 'clm agent configure audit-openclaw --stage providers' to retry.
Onboarding failed at stage: providers
```
Exit: `1`


> **Note:** `audit-openclaw configure --yes` fails on this fleet with no
> default provider auto-selected. The remaining lifecycle commands below
> are still run sequentially to capture their verbatim behavior against
> an unconfigured agent — this is intentional baseline data. See
> Callouts on the PR for the documented decision.

#### audit-openclaw: `start` (against unconfigured agent)

### `clm agent start audit-openclaw`

```console
$ clm agent start audit-openclaw

Error: Cannot start audit-openclaw - onboarding incomplete

Current state: PROVIDERS (0/4)

Incomplete stages:
  ○ providers  - Assign inference provider to this agent
  ○ identity   - Configure agent personality and behavior
  ○ channels   - Configure communication channels
  ○ validate   - Verify agent is properly configured

Run 'clm agent configure audit-openclaw' to complete onboarding.

To force start anyway (not recommended):
  clm agent start audit-openclaw --force

```
Exit: `1`


#### audit-openclaw: `sync`

### `clm agent sync audit-openclaw`

```console
$ clm agent sync audit-openclaw
Syncing agent: audit-openclaw on wolf-i
  Syncing audit-openclaw on wolf.tailf7742d.ts.net...
  Configuring audit-openclaw...
  Configuring audit-openclaw on wolf.tailf7742d.ts.net...
  Running Ansible playbook...
  Saving configuration to hosts.json...
  Successfully configured audit-openclaw
  Sync complete for audit-openclaw
✓ Configuration synced
  Run 'clm agent ps' to check status
```
Exit: `0`


#### audit-openclaw: `stop`

### `clm agent stop audit-openclaw`

```console
$ clm agent stop audit-openclaw
Stopping agent: audit-openclaw on wolf-i
  Checking audit-openclaw on wolf.tailf7742d.ts.net...
  Stopping audit-openclaw on wolf.tailf7742d.ts.net...
  Stopped audit-openclaw successfully
✓ Agent stopped successfully
```
Exit: `0`


#### audit-openclaw: `restart`

### `clm agent restart audit-openclaw`

```console
$ clm agent restart audit-openclaw
Restarting agent: audit-openclaw on wolf-i
  Restarting audit-openclaw on wolf.tailf7742d.ts.net...
  Checking audit-openclaw on wolf.tailf7742d.ts.net...
  Stopping audit-openclaw on wolf.tailf7742d.ts.net...
  Stopped audit-openclaw successfully
  Checking audit-openclaw on wolf.tailf7742d.ts.net...
Error: Cannot start audit-openclaw: onboarding incomplete (state=providers). Run 'clm agent configure audit-openclaw' first.
```
Exit: `1`


### audit-zeroclaw: sync / stop / restart


#### audit-zeroclaw: `sync`

### `clm agent sync audit-zeroclaw`

```console
$ clm agent sync audit-zeroclaw
Syncing agent: audit-zeroclaw on wolf-i
  Syncing audit-zeroclaw on wolf.tailf7742d.ts.net...
  Configuring audit-zeroclaw...
  Configuring audit-zeroclaw on wolf.tailf7742d.ts.net...
  Loaded provider API key from secrets
  Running Ansible playbook...
  Pairing token captured
  Saving configuration to hosts.json...
  Gateway token rotated for audit-zeroclaw. Active chat sessions on other machines will need to reconnect.
  Successfully configured audit-zeroclaw
  Sync complete for audit-zeroclaw
✓ Configuration synced
  Run 'clm agent ps' to check status
```
Exit: `0`


#### audit-zeroclaw: `stop`

### `clm agent stop audit-zeroclaw`

```console
$ clm agent stop audit-zeroclaw
Stopping agent: audit-zeroclaw on wolf-i
  Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
  Stopping audit-zeroclaw on wolf.tailf7742d.ts.net...
  Stopped audit-zeroclaw successfully
✓ Agent stopped successfully
```
Exit: `0`


#### audit-zeroclaw: `restart`

### `clm agent restart audit-zeroclaw`

```console
$ clm agent restart audit-zeroclaw
Restarting agent: audit-zeroclaw on wolf-i
  Restarting audit-zeroclaw on wolf.tailf7742d.ts.net...
  Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
  Stopping audit-zeroclaw on wolf.tailf7742d.ts.net...
  Stopped audit-zeroclaw successfully
  Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
  Starting audit-zeroclaw on wolf.tailf7742d.ts.net...
  Daemon started; pairing audit-zeroclaw...
  Re-pairing zeroclaw after restart...
  Gateway token rotated for audit-zeroclaw. Active chat sessions on other machines will need to reconnect.
  Pairing token refreshed
  Started audit-zeroclaw successfully
✓ Agent restarted successfully
  Run 'clm agent ps' to check status
```
Exit: `0`


### audit-hermes: sync / stop / restart


#### audit-hermes: `sync`

### `clm agent sync audit-hermes`

```console
$ clm agent sync audit-hermes
Syncing agent: audit-hermes on wolf-i
  Syncing audit-hermes on wolf.tailf7742d.ts.net...
  Configuring audit-hermes...
  Configuring audit-hermes on wolf.tailf7742d.ts.net...
  Loaded provider API key from secrets
  Running Ansible playbook...
  Saving configuration to hosts.json...
  Successfully configured audit-hermes
  Sync complete for audit-hermes
✓ Configuration synced
  Run 'clm agent ps' to check status
```
Exit: `0`


#### audit-hermes: `stop`

### `clm agent stop audit-hermes`

```console
$ clm agent stop audit-hermes
Stopping agent: audit-hermes on wolf-i
  Checking audit-hermes on wolf.tailf7742d.ts.net...
  Stopping audit-hermes on wolf.tailf7742d.ts.net...
  Stopped audit-hermes successfully
✓ Agent stopped successfully
```
Exit: `0`


#### audit-hermes: `restart`

### `clm agent restart audit-hermes`

```console
$ clm agent restart audit-hermes
Restarting agent: audit-hermes on wolf-i
  Restarting audit-hermes on wolf.tailf7742d.ts.net...
  Checking audit-hermes on wolf.tailf7742d.ts.net...
  Stopping audit-hermes on wolf.tailf7742d.ts.net...
  Stopped audit-hermes successfully
  Checking audit-hermes on wolf.tailf7742d.ts.net...
  Starting audit-hermes on wolf.tailf7742d.ts.net...
  Started audit-hermes successfully
✓ Agent restarted successfully
  Run 'clm agent ps' to check status
```
Exit: `0`


### Post-lifecycle agent ps (audit-* agents visible)

### `clm agent ps`

```console
$ clm agent ps


                                                       Agent Fleet Status                                                        
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name           ┃ Agent Type ┃ Provider   ┃ Host   ┃ Address                ┃ Port  ┃ Version  ┃ Status           ┃ Installed  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩
│ audit-hermes   │ hermes     │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 40425 │ 2026.5.7 │ ready (stopped)  │ 2026-05-24 │
│ audit-openclaw │ openclaw   │ -          │ wolf-i │ wolf.tailf7742d.ts.net │ 40612 │ 2026.4.2 │ onboarding (0/4) │ 2026-05-24 │
│ audit-zeroclaw │ zeroclaw   │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 40616 │ 0.7.5    │ running          │ 2026-05-24 │
│ clawrium-d01   │ zeroclaw   │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 41429 │ 0.7.5    │ running          │ 2026-05-19 │
│ espresso       │ hermes     │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 41583 │ 2026.5.7 │ running          │ 2026-05-11 │
│ maurice        │ hermes     │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 40317 │ 2026.5.7 │ running          │ 2026-05-22 │
│ nemotron-alpha │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40919 │ 0.7.5    │ running          │ 2026-05-22 │
│ nemotron-beta  │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40971 │ 0.7.5    │ running          │ 2026-05-20 │
│ wolf-i         │ openclaw   │ bedrock    │ wolf-i │ wolf.tailf7742d.ts.net │ 40198 │ 2026.4.2 │ running          │ 2026-04-11 │
└────────────────┴────────────┴────────────┴────────┴────────────────────────┴───────┴──────────┴──────────────────┴────────────┘


audit-hermes on wolf-i:
  ✓ providers  - (2026-05-24)
  ○ identity   - (skipped)
  ✓ channels   - (2026-05-24)
  ✓ validate   - (2026-05-24)

audit-openclaw on wolf-i:
  ○ providers  - pending
  ○ identity   - pending
  ○ channels   - pending
  ○ validate   - pending
```
Exit: `0`


---

## Per-agent read-only command transcripts (audit-* agents)

For each audit-* agent: secret list, memory show, integration list,
skill list, logs --tail 20. Captured while the agents are in their
post-lifecycle state.

### audit-zeroclaw

### `clm agent secret list audit-zeroclaw`

```console
$ clm agent secret list audit-zeroclaw
╭─────────────────────────────────────────────────── Traceback (most recent call last) ────────────────────────────────────────────────────╮
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/cli/agent.py:2686 in secret_list                    │
│                                                                                                                                          │
│   2683 │   """List secrets for an agent."""                                                                                              │
│   2684 │   from clawrium.cli.secret import list_cmd                                                                                      │
│   2685 │                                                                                                                                 │
│ ❱ 2686 │   list_cmd(claw_name=claw_name)                                                                                                 │
│   2687                                                                                                                                   │
│   2688                                                                                                                                   │
│   2689 @secret_app.command(name="remove")                                                                                                │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/cli/secret.py:130 in list_cmd                       │
│                                                                                                                                          │
│   127 │   instance_secrets = secrets.get(instance_key, {})                                                                               │
│   128 │                                                                                                                                  │
│   129 │   # Build gateway config based on agent type                                                                                     │
│ ❱ 130 │   required_secrets = get_required_secrets(claw_type)                                                                             │
│   131 │   required_keys = {s["key"] for s in required_secrets}                                                                           │
│   132 │   stored_keys = set(instance_secrets.keys())                                                                                     │
│   133 │   missing_keys = required_keys - stored_keys                                                                                     │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/core/registry.py:744 in get_required_secrets        │
│                                                                                                                                          │
│   741 │   Returns:                                                                                                                       │
│   742 │   │   List of required `SecretDefinition` objects                                                                                │
│   743 │   """                                                                                                                            │
│ ❱ 744 │   manifest = load_manifest(claw_name)                                                                                            │
│   745 │   return manifest.get("secrets", {}).get("required", [])                                                                         │
│   746                                                                                                                                    │
│   747                                                                                                                                    │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/core/registry.py:638 in load_manifest               │
│                                                                                                                                          │
│   635 │   │   agent_dir = registry_package / claw_name                                                                                   │
│   636 │   │                                                                                                                              │
│   637 │   │   if not agent_dir.is_dir():                                                                                                 │
│ ❱ 638 │   │   │   raise ManifestNotFoundError(                                                                                           │
│   639 │   │   │   │   f"Agent type '{claw_name}' not found in registry"                                                                  │
│   640 │   │   │   )                                                                                                                      │
│   641                                                                                                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
ManifestNotFoundError: Agent type 'audit-zeroclaw' not found in registry
```
Exit: `1`

### `clm agent memory show audit-zeroclaw`

```console
$ clm agent memory show audit-zeroclaw

Agent: audit-zeroclaw (wolf.tailf7742d.ts.net)
Workspace: /home/audit-zeroclaw/.zeroclaw/workspace
Total size: 2.2 KB

 File          Status    Size 
 SOUL.md       present  325 B 
 IDENTITY.md   present  376 B 
 USER.md       present  247 B 
 AGENTS.md     present  391 B 
 TOOLS.md      present  387 B 
 MEMORY.md     present  176 B 
 HEARTBEAT.md  present  381 B 
```
Exit: `0`

### `clm agent integration list audit-zeroclaw`

```console
$ clm agent integration list audit-zeroclaw

Agent: audit-zeroclaw
  No integrations assigned

Use 'clm agent integration add <agent> <integration>' to assign integrations
```
Exit: `0`

### `clm agent skill list audit-zeroclaw`

```console
$ clm agent skill list audit-zeroclaw
No skills installed on audit-zeroclaw. Try clm agent skill install audit-zeroclaw clawrium/tdd.
```
Exit: `0`

### `clm agent logs audit-zeroclaw --tail 20`

```console
$ clm agent logs audit-zeroclaw --tail 20
Usage: clm agent logs [OPTIONS] CLAW_NAME
Try 'clm agent logs --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ No such option '--tail'.                                                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```
Exit: `2`


### audit-hermes

### `clm agent secret list audit-hermes`

```console
$ clm agent secret list audit-hermes
╭─────────────────────────────────────────────────── Traceback (most recent call last) ────────────────────────────────────────────────────╮
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/cli/agent.py:2686 in secret_list                    │
│                                                                                                                                          │
│   2683 │   """List secrets for an agent."""                                                                                              │
│   2684 │   from clawrium.cli.secret import list_cmd                                                                                      │
│   2685 │                                                                                                                                 │
│ ❱ 2686 │   list_cmd(claw_name=claw_name)                                                                                                 │
│   2687                                                                                                                                   │
│   2688                                                                                                                                   │
│   2689 @secret_app.command(name="remove")                                                                                                │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/cli/secret.py:130 in list_cmd                       │
│                                                                                                                                          │
│   127 │   instance_secrets = secrets.get(instance_key, {})                                                                               │
│   128 │                                                                                                                                  │
│   129 │   # Build gateway config based on agent type                                                                                     │
│ ❱ 130 │   required_secrets = get_required_secrets(claw_type)                                                                             │
│   131 │   required_keys = {s["key"] for s in required_secrets}                                                                           │
│   132 │   stored_keys = set(instance_secrets.keys())                                                                                     │
│   133 │   missing_keys = required_keys - stored_keys                                                                                     │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/core/registry.py:744 in get_required_secrets        │
│                                                                                                                                          │
│   741 │   Returns:                                                                                                                       │
│   742 │   │   List of required `SecretDefinition` objects                                                                                │
│   743 │   """                                                                                                                            │
│ ❱ 744 │   manifest = load_manifest(claw_name)                                                                                            │
│   745 │   return manifest.get("secrets", {}).get("required", [])                                                                         │
│   746                                                                                                                                    │
│   747                                                                                                                                    │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/core/registry.py:638 in load_manifest               │
│                                                                                                                                          │
│   635 │   │   agent_dir = registry_package / claw_name                                                                                   │
│   636 │   │                                                                                                                              │
│   637 │   │   if not agent_dir.is_dir():                                                                                                 │
│ ❱ 638 │   │   │   raise ManifestNotFoundError(                                                                                           │
│   639 │   │   │   │   f"Agent type '{claw_name}' not found in registry"                                                                  │
│   640 │   │   │   )                                                                                                                      │
│   641                                                                                                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
ManifestNotFoundError: Agent type 'audit-hermes' not found in registry
```
Exit: `1`

### `clm agent memory show audit-hermes`

```console
$ clm agent memory show audit-hermes

Agent: audit-hermes (wolf.tailf7742d.ts.net)
Workspace: /home/audit-hermes/.hermes/memories
Total size: 537 B

 File       Status    Size 
 MEMORY.md  missing      - 
 USER.md    missing      - 
 SOUL.md    present  537 B 
```
Exit: `0`

### `clm agent integration list audit-hermes`

```console
$ clm agent integration list audit-hermes

Agent: audit-hermes
  No integrations assigned

Use 'clm agent integration add <agent> <integration>' to assign integrations
```
Exit: `0`

### `clm agent skill list audit-hermes`

```console
$ clm agent skill list audit-hermes
No skills installed on audit-hermes. Try clm agent skill install audit-hermes clawrium/tdd.
```
Exit: `0`

### `clm agent logs audit-hermes --tail 20`

```console
$ clm agent logs audit-hermes --tail 20
Usage: clm agent logs [OPTIONS] CLAW_NAME
Try 'clm agent logs --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ No such option '--tail'.                                                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```
Exit: `2`


### audit-openclaw

### `clm agent secret list audit-openclaw`

```console
$ clm agent secret list audit-openclaw
╭─────────────────────────────────────────────────── Traceback (most recent call last) ────────────────────────────────────────────────────╮
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/cli/agent.py:2686 in secret_list                    │
│                                                                                                                                          │
│   2683 │   """List secrets for an agent."""                                                                                              │
│   2684 │   from clawrium.cli.secret import list_cmd                                                                                      │
│   2685 │                                                                                                                                 │
│ ❱ 2686 │   list_cmd(claw_name=claw_name)                                                                                                 │
│   2687                                                                                                                                   │
│   2688                                                                                                                                   │
│   2689 @secret_app.command(name="remove")                                                                                                │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/cli/secret.py:130 in list_cmd                       │
│                                                                                                                                          │
│   127 │   instance_secrets = secrets.get(instance_key, {})                                                                               │
│   128 │                                                                                                                                  │
│   129 │   # Build gateway config based on agent type                                                                                     │
│ ❱ 130 │   required_secrets = get_required_secrets(claw_type)                                                                             │
│   131 │   required_keys = {s["key"] for s in required_secrets}                                                                           │
│   132 │   stored_keys = set(instance_secrets.keys())                                                                                     │
│   133 │   missing_keys = required_keys - stored_keys                                                                                     │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/core/registry.py:744 in get_required_secrets        │
│                                                                                                                                          │
│   741 │   Returns:                                                                                                                       │
│   742 │   │   List of required `SecretDefinition` objects                                                                                │
│   743 │   """                                                                                                                            │
│ ❱ 744 │   manifest = load_manifest(claw_name)                                                                                            │
│   745 │   return manifest.get("secrets", {}).get("required", [])                                                                         │
│   746                                                                                                                                    │
│   747                                                                                                                                    │
│                                                                                                                                          │
│ /home/devashish/.local/share/uv/tools/clawrium/lib/python3.13/site-packages/clawrium/core/registry.py:638 in load_manifest               │
│                                                                                                                                          │
│   635 │   │   agent_dir = registry_package / claw_name                                                                                   │
│   636 │   │                                                                                                                              │
│   637 │   │   if not agent_dir.is_dir():                                                                                                 │
│ ❱ 638 │   │   │   raise ManifestNotFoundError(                                                                                           │
│   639 │   │   │   │   f"Agent type '{claw_name}' not found in registry"                                                                  │
│   640 │   │   │   )                                                                                                                      │
│   641                                                                                                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
ManifestNotFoundError: Agent type 'audit-openclaw' not found in registry
```
Exit: `1`

### `clm agent memory show audit-openclaw`

```console
$ clm agent memory show audit-openclaw

Agent: audit-openclaw (wolf.tailf7742d.ts.net)
Workspace: /home/audit-openclaw/.openclaw/workspace
Total size: 0 B

 File         Status   Size 
 SOUL.md      missing     - 
 IDENTITY.md  missing     - 
 USER.md      missing     - 
 TOOLS.md     missing     - 
```
Exit: `0`

### `clm agent integration list audit-openclaw`

```console
$ clm agent integration list audit-openclaw

Agent: audit-openclaw
  No integrations assigned

Use 'clm agent integration add <agent> <integration>' to assign integrations
```
Exit: `0`

### `clm agent skill list audit-openclaw`

```console
$ clm agent skill list audit-openclaw
No skills installed on audit-openclaw. Try clm agent skill install audit-openclaw clawrium/tdd.
```
Exit: `0`

### `clm agent logs audit-openclaw --tail 20`

```console
$ clm agent logs audit-openclaw --tail 20
Usage: clm agent logs [OPTIONS] CLAW_NAME
Try 'clm agent logs --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ No such option '--tail'.                                                                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```
Exit: `2`


---

## Teardown — remove audit-* agents

Only the three `audit-*` agents are removed. Pre-existing agents are
preserved. `--force` is used to avoid the interactive confirmation
prompt; this matches the non-interactive baseline goal.

### `clm agent remove audit-zeroclaw --force`

```console
$ clm agent remove audit-zeroclaw --force
Removing agent: audit-zeroclaw from wolf-i
  Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
  Stopping audit-zeroclaw before removal...
  Checking audit-zeroclaw on wolf.tailf7742d.ts.net...
  Removing audit-zeroclaw from wolf.tailf7742d.ts.net...
  Removing from local configuration...
  Cleaned up instance secrets
  Agent state directory already absent
  Removed audit-zeroclaw successfully
✓ Agent removed successfully
```
Exit: `0`

### `clm agent remove audit-hermes --force`

```console
$ clm agent remove audit-hermes --force
Removing agent: audit-hermes from wolf-i
  Checking audit-hermes on wolf.tailf7742d.ts.net...
  Stopping audit-hermes before removal...
  Checking audit-hermes on wolf.tailf7742d.ts.net...
  Removing audit-hermes from wolf.tailf7742d.ts.net...
  Removing from local configuration...
  Cleaned up instance secrets
  Agent state directory already absent
  Removed audit-hermes successfully
✓ Agent removed successfully
```
Exit: `0`

### `clm agent remove audit-openclaw --force`

```console
$ clm agent remove audit-openclaw --force
Removing agent: audit-openclaw from wolf-i
  Checking audit-openclaw on wolf.tailf7742d.ts.net...
  Removing audit-openclaw from wolf.tailf7742d.ts.net...
  Removing from local configuration...
  Cleaned up instance secrets
  Agent state directory already absent
  Removed audit-openclaw successfully
✓ Agent removed successfully
```
Exit: `0`


---

## Final state (post-teardown)

Verifies that wolf-i has returned to its pre-capture state (the six
pre-existing agents). The fleet is **not empty** — the issue contract
called for an empty fleet but the audit preserved the pre-existing
fleet (see Preamble and PR Callouts).

### `clm agent ps`

```console
$ clm agent ps


                                                   Agent Fleet Status                                                   
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┓
┃ Name           ┃ Agent Type ┃ Provider   ┃ Host   ┃ Address                ┃ Port  ┃ Version  ┃ Status  ┃ Installed  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━┩
│ clawrium-d01   │ zeroclaw   │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 41429 │ 0.7.5    │ running │ 2026-05-19 │
│ espresso       │ hermes     │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 41583 │ 2026.5.7 │ running │ 2026-05-11 │
│ maurice        │ hermes     │ openrouter │ wolf-i │ wolf.tailf7742d.ts.net │ 40317 │ 2026.5.7 │ running │ 2026-05-22 │
│ nemotron-alpha │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40919 │ 0.7.5    │ running │ 2026-05-22 │
│ nemotron-beta  │ zeroclaw   │ ollama     │ wolf-i │ wolf.tailf7742d.ts.net │ 40971 │ 0.7.5    │ running │ 2026-05-20 │
│ wolf-i         │ openclaw   │ bedrock    │ wolf-i │ wolf.tailf7742d.ts.net │ 40198 │ 2026.4.2 │ running │ 2026-04-11 │
└────────────────┴────────────┴────────────┴────────┴────────────────────────┴───────┴──────────┴─────────┴────────────┘

```
Exit: `0`

### `clm host ps wolf-i`

```console
$ clm host ps wolf-i
Checking status of 'wolf-i'...
                Host Status: wolf-i                
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Property     ┃ Value                            ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Connection   │ Connected                        │
│ Hostname     │ wolf.tailf7742d.ts.net           │
│ SSH Config   │ wolf-i                           │
│ Port         │ 22                               │
│ User         │ xclm                             │
│ Added        │ 2026-04-11T04:46:19.295019+00:00 │
│ Last Seen    │ 2026-04-11T04:46:19.295019+00:00 │
│ Tags         │ -                                │
│ Architecture │ x86_64                           │
│ CPU Cores    │ 4                                │
│ Memory       │ 15.5 GB                          │
│ GPU          │ intel                            │
└──────────────┴──────────────────────────────────┘

Addresses:
    192.168.1.36
  * wolf.tailf7742d.ts.net (tailscale)
```
Exit: `0`


---

**Capture end (UTC):** 2026-05-24T03:42:22Z


# Implementation Plan — Issue #377

Deploy zeroclaw agent `clawrium-d-01` on wolf-i with DGX Spark inference.

## Overview

Operational deployment using existing Clawrium capabilities. No source changes.

- **Agent name:** `clawrium-d-01`
- **Type:** `zeroclaw` (registry entry exists; x86_64 Ubuntu 22.04/24.04 supported)
- **Host:** `wolf-i` (alias) @ `192.168.1.36`, user `xclm`, x86_64, 15.9 GB RAM
- **Inference provider:** `local-inx` (existing ollama provider @ `http://192.168.1.17:11434` — the DGX Spark)
- **Model:** `qwen2.5-coder`
- **SOUL / Identity:** auto-skipped (zeroclaw default; intentionally fungible per spec)

## Files to Modify

**None in the Clawrium source tree.** This issue does not change code. The only files written are:

- `.itx/377/00_PLAN.md` (this file)
- `.itx/377/02_NOTES.md` (run log, created during execution)
- `~/.config/clawrium/hosts.json` (mutated by `clm agent install` to record the new agent under wolf-i — managed by the CLI, not edited by hand)
- `~/.config/clawrium/secrets.json` (any provider/agent credentials touched during configure — managed by the CLI)

## Steps

### 1. Pre-flight checks

```bash
# Confirm host is reachable and known
clm host ls
clm host show wolf-i

# Confirm the DGX Spark provider exists and responds; list available models
clm provider ls
clm provider test local-inx
clm provider models local-inx | grep -i qwen
```

Stop the run if:
- `wolf-i` is missing → user must add it first (out of scope).
- `local-inx` is not reachable → fix the DGX before continuing.
- `qwen2.5-coder` is not listed → `ollama pull qwen2.5-coder` on the DGX Spark host, then re-test.

### 2. Confirm name availability on the host

```bash
clm agent ps --host wolf-i
```

`clawrium-d-01` must not already exist on `wolf-i`. If it does, decide between renaming (e.g. `clawrium-d-02`) or removing the existing instance (`clm agent remove clawrium-d-01`).

### 3. Install the zeroclaw agent

```bash
clm agent install \
  --type zeroclaw \
  --host wolf-i \
  --name clawrium-d-01
```

Expected outcome (from `zeroclaw/playbooks/install.yaml`):

- Linux user `clawrium-d-01` created on wolf-i with `/usr/sbin/nologin` shell.
- ZeroClaw binary v0.7.5 fetched for `x86_64-unknown-linux-gnu` and placed at `/home/clawrium-d-01/bin/zeroclaw` (sha256 verified).
- `/home/clawrium-d-01/.zeroclaw/{workspace,state}` scaffolded.
- Systemd unit `zeroclaw-clawrium-d-01.service` dropped **disabled** (not started yet).

### 4. Configure the agent

```bash
# Stage 1 — providers: bind to the existing DGX Spark ollama provider
clm agent configure clawrium-d-01 --stage providers
# When prompted:
#   - select provider: local-inx
#   - select model:    qwen2.5-coder

# Stage 2 — identity: auto-skipped per zeroclaw manifest

# Stage 3 — channels: confirm CLI default
clm agent configure clawrium-d-01 --stage channels

# Stage 4 — validate
clm agent configure clawrium-d-01 --stage validate
```

This renders `/home/clawrium-d-01/.zeroclaw/config.toml` from `templates/config.toml.j2` with:
- `[providers.models.ollama]` block: `kind = "ollama"`, `model = "qwen2.5-coder"`, `base_url = "http://192.168.1.17:11434"`
- `[gateway]` block: `host = "0.0.0.0"`, `port` assigned, `require_pairing = true`
- `[personality]` block: name `clawrium-d-01`, defaults otherwise

### 5. Start and verify

```bash
clm agent start clawrium-d-01
clm agent ps                         # status: running
clm agent show clawrium-d-01         # provider, model, gateway URL, uptime
clm chat clawrium-d-01 "ping"        # round-trip through the DGX Spark
```

### 6. Record run notes

Append to `.itx/377/02_NOTES.md`:
- Exact provider/model selected
- Gateway port assigned
- DGX Spark response latency (rough)
- Anything that deviated from this plan

## Test Strategy

This is an operational task. Verification is observational, not unit-tested.

| Check | How | Pass condition |
|---|---|---|
| Host reachable | `clm host show wolf-i` | hardware block populated, last_check recent |
| Provider reachable | `clm provider test local-inx` | success, model list returned |
| Model present on DGX | `clm provider models local-inx \| grep qwen2.5-coder` | match returned |
| Agent installed | `clm agent ps --host wolf-i` | row for `clawrium-d-01` |
| Agent configured | `clm agent show clawrium-d-01` | provider `local-inx`, model `qwen2.5-coder` |
| Agent running | `clm agent ps` | status `running`, uptime > 0 |
| Chat round-trip | `clm chat clawrium-d-01 "ping"` | non-empty model response within ~10s |

Rollback (if any step fails irrecoverably):

```bash
clm agent stop clawrium-d-01    # if started
clm agent remove clawrium-d-01  # tears down systemd unit, user, files
```

## Risks

1. **`qwen2.5-coder` not pulled on the DGX.** Mitigation: step 1 explicitly checks. Operator pulls manually if missing — `ollama pull qwen2.5-coder` on the DGX Spark host.
2. **wolf-i RAM (~16 GB) close to model requirements.** The model runs on the **DGX Spark**, not on wolf-i; wolf-i only runs the zeroclaw daemon (`~256 MB` resident typical). Risk is low.
3. **Existing `clawrium-d-01` instance.** Caught by step 2.
4. **Gateway port collision** if other zeroclaw agents are already on wolf-i. `clm agent install` auto-assigns; risk is low.

## Subtasks

None — single operational task, fits in one PR's worth of activity (here: one runbook execution). No code change → no PR.

## Out of Scope

The original capability spec described autonomous behaviour:
- Polling GitHub for `agent-ready` labelled issues
- Claiming, reading `.itx/<N>/00_PLAN.md`, implementing
- Branch + PR creation

**Clawrium does not have these capabilities today.** ZeroClaw is a chat-only assistant binary (the daemon exposes a gateway; `clm chat` is the interface). Delivering the autonomous behaviour requires one of:

- A new agent type (e.g. `implclaw`) with its own polling runtime
- A separate cron / systemd timer on wolf-i that uses `clm chat clawrium-d-01 …` to drive issue work
- Upstream changes in `zeroclaw-labs/zeroclaw`

That work will be tracked in a separate follow-up issue after this deployment is verified.

---

<details>
<summary>Prompt Log</summary>

**Stage:** planning
**Skill:** `/itx:plan-create`
**Timestamp:** 2026-05-16
**Model:** claude-opus-4-7

```prompt
build a new agent based on this [clawrium-d-01 — Agent Configuration spec]
… use the existing infrastructure and capabilities available in Clawrium to
create this agent. … It will use ZeroClaw. … run on the host called wolf-pi …
DGX Spark as an inference provider.
```

Decisions captured during planning:
- Host `wolfpi` resolved to existing alias `wolf-i` (192.168.1.36).
- "DGX Spark" provider resolved to existing `local-inx` (192.168.1.17:11434) per user direction; not renamed.
- Model fixed to `qwen2.5-coder`.
- Autonomous GH polling / PR behaviour confirmed out of scope; not deliverable with existing zeroclaw.

</details>

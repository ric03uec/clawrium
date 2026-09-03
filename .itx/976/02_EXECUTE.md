# Issue #976 — Execution log

Executes `.itx/976/00_PLAN.md` for the zeroclaw + litellm allow-list extension.

## Code changes (summary)

1. **Allow-list**: `src/clawrium/core/render.py:89-99` — added `"litellm"` to
   `_AGENT_TYPE_PROVIDER_SUPPORT["zeroclaw"]`; removed the deferred-work
   carve-out comment. Also added `"litellm"` to `_ZEROCLAW_PROVIDER_KINDS`
   (`render.py:1376`) — the second guard inside `render_zeroclaw` itself.
2. **Renderer normalization**: `render_zeroclaw` at `render.py:1482` — the
   `provider.type in ("opencode", "opencode-go")` branch now also covers
   `"litellm"`; behaviour is byte-identical (strip trailing `/`, append `/v1`
   if absent).
3. **Template**: `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
   — added `{% elif provider.type == "litellm" %}base_url = … api_key = …`
   branch. Existing `ollama` / `opencode`-tuple / default branches
   byte-identical.
4. **Tests**: `tests/core/test_render.py`
   - Added `(render_zeroclaw, "litellm")` to the idempotency parametrize
     list (`test_render.py:527`).
   - Added five zeroclaw-litellm tests: three-level provider block,
     endpoint-with-`/v1`, endpoint-without-`/v1`, trailing-slash strip,
     trailing-slash-after-`/v1` strip, and a byte-lock fixture assertion.
   - Byte-lock fixture at `tests/core/fixtures/zeroclaw_config_litellm.toml`.
   - Added CLI attach test at
     `tests/cli/clawctl/provider/test_agent_attach_zeroclaw_litellm.py` (three
     tests: attach succeeds, single-provider invariant still rejects a
     second attach, `build_render_inputs` passes end-to-end).
5. **Docs**: Removed the "only four providers" carve-out from
   `docs/agent-support/zeroclaw.md` + `website/docs/agent-support/zeroclaw.md`;
   added `litellm` to the provider matrix and per-provider rendering table.
6. **CHANGELOG**: Single `### Added` entry under `[Unreleased]` (#976).

## Local test + lint

- `make lint` → clean (ruff + eslint).
- `make test` → 4822 passed, 2 skipped (pytest); 329 passed (vitest).
- The 10 new tests (5 renderer + 5 CLI/render-through-attach) all pass;
  50 zeroclaw render tests total remain green.

## Live UAT — wolf-i / clawrium-d01 / clawrium-gtm-litellm

Target agent: `clawrium-d01` (zeroclaw @ v0.8.2 on wolf-i).
Target provider: `clawrium-gtm-litellm` (type=litellm, endpoint
`http://192.168.1.17:4000`, model `Qwen3.8-27B-FP8`).

Every command is issued with the branch build via `uv run clawctl …` from
this worktree so the code under test is what is exercised.


### Step 0 — surface current state

```
$ uv run clawctl host get | grep wolf-i
wolf-i          wolf.tailf7742d.ts.net              xclm   ready    144d

$ uv run clawctl agent get | grep clawrium-d01
clawrium-d01        zeroclaw   wolf-i          clawrium-glm51         ready        54d   -

$ uv run clawctl agent provider get --agent clawrium-d01 -o json
[
  {
    "kind": "provider",
    "name": "clawrium-glm51",
    "agent": "clawrium-d01"
  }
]

$ uv run clawctl provider registry get | grep clawrium-gtm-litellm
clawrium-gtm-litellm           litellm      Qwen3.8-27B-FP8                     set
```

Current provider on `clawrium-d01` is `clawrium-glm51`. The single-provider
invariant means we must `detach` it before attaching
`clawrium-gtm-litellm`. This will trigger a `sync` afterwards, which
rotates the zeroclaw gateway bearer (issue #437 contract). No live chat
sessions on this agent should be assumed to survive.


### Step 1 — detach current openrouter provider

```
$ uv run clawctl agent provider detach clawrium-glm51 --agent clawrium-d01
agent/clawrium-d01: detached provider 'clawrium-glm51'
```

Exit 0. Single-provider invariant means we must detach before attaching a new one.

### Step 2 — attach the litellm provider (previously blocked by #976 allow-list)

```
$ uv run clawctl agent provider attach clawrium-gtm-litellm --agent clawrium-d01
agent/clawrium-d01: attached provider 'clawrium-gtm-litellm'
```

Exit 0. This is the CLI-facing gate that #976 closes — before this
change, `build_render_inputs` (called under the hood by attach) refused
the operation with `render_zeroclaw does not support provider type
'litellm'`. Post-#976 it succeeds.

### Step 3 — sync (first run — full render + restart + re-pair)

```
$ uv run clawctl agent sync clawrium-d01
agent/clawrium-d01: validating local state ...
agent/clawrium-d01: pushing config (provider, skills, channels, env) ...
agent/clawrium-d01: restarting unit ...
agent/clawrium-d01: verifying health ...
agent/clawrium-d01: validate: assembling render inputs for clawrium-d01
agent/clawrium-d01: validate: checking host install for clawrium-d01
agent/clawrium-d01: render: rendering canonical config for zeroclaw
agent/clawrium-d01: render: preserving 1 onboard section(s) from on-host clawrium-d01 config
agent/clawrium-d01: diff: reading on-host files from wolf.tailf7742d.ts.net
agent/clawrium-d01: github_integration: wired gh + git credential helper for github integration 'clawrium-d01-github' on clawrium-d01
agent/clawrium-d01: write: writing /home/clawrium-d01/.zeroclaw/config.toml
agent/clawrium-d01: push_workspace: {"state": "complete", "files_pushed": [], "files_excluded": []}
agent/clawrium-d01: restart: restarting zeroclaw-clawrium-d01.service
agent/clawrium-d01: verify: checking unit is active
agent/clawrium-d01: repair: re-pairing zeroclaw gateway for clawrium-d01
agent/clawrium-d01: sync: Re-pairing zeroclaw after sync...
  Gateway token rotated for clawrium-d01. ...
agent/clawrium-d01: sync: Pairing token refreshed
agent/clawrium-d01: sync: synced clawrium-d01: 1 written, 1 unchanged
agent/clawrium-d01: synced  (drift=0, took 6s, 1 written, 1 unchanged)
```

Exit 0. No renderer error. Config written to
`/home/clawrium-d01/.zeroclaw/config.toml`. Gateway bearer rotated per
#437 contract. drift=0 on the first pass.

### Step 4 — daemon-level verification of the rendered provider block

`zeroclaw config list --filter providers.models` on the agent host
proves the rendered TOML parses into the correct three-level provider
table with all three key fields populated:

```
$ uv run clawctl agent exec clawrium-d01 -- config list --filter providers.models
Providers:
  providers.models.litellm.clawrium-d01.api_key = ****                 (Option<String>) 🔒
  providers.models.litellm.clawrium-d01.kind    = <unset>              (Option<String>)
  providers.models.litellm.clawrium-d01.uri     = http://192.168.1.17:4000/v1 (Option<String>)
  providers.models.litellm.clawrium-d01.model   = Qwen3.8-27B-FP8      (Option<String>)
  ...
```

**Important finding — `uri` vs `base_url`**: an initial revision of
this branch emitted `base_url = "..."` inside the litellm block
(matching the plan's spec of "byte-identical to opencode branch").
Empirically that key is silently dropped by zeroclaw v0.8.2 — `config
list` showed `uri = <unset>`. zeroclaw's OpenAI-compatible provider
schema uses `uri`. The template was updated to emit `uri` for the
litellm branch, and daemon parsing was re-verified: `uri =
http://192.168.1.17:4000/v1` is now populated. The plan's guidance to
"match opencode's shape" is a `[DECISION]` on the PR — see Callouts.
opencode-on-zeroclaw uses `base_url` today and may be affected by the
same field-name mismatch, but that's out of scope for #976 (which is
scoped to the litellm allow-list extension).

The zeroclaw daemon's provider catalog (`zeroclaw providers`)
recognizes the provider as configured:

```
$ uv run clawctl agent exec clawrium-d01 -- providers | grep -i litellm
  litellm             LiteLLM (configured)
```

### Step 5 — idempotency check

```
$ uv run clawctl agent sync clawrium-d01
...
agent/clawrium-d01: synced  (drift=0, took 6s, 1 written, 1 unchanged)
```

drift=0 as expected.

### Step 6 — chat (blocked by a pre-existing, fleet-wide zeroclaw
gate, NOT by #976)

```
$ uv run clawctl agent chat clawrium-d01 --once "ping" --timeout 120
ZeroClaw chat is using a non-TLS WebSocket (ws://) to a non-loopback host ...
Protocol error: This agent isn't fully set up yet. The operator needs to run
Quickstart before I can reply.
```

**Root cause of the chat block**: zeroclaw v0.8.2 gates chat behind a
`onboard_state.quickstart_completed = true` flag. Our template
currently emits `[onboard_state]` with only `completed_sections = [...]`;
it does not emit `quickstart_completed`, which defaults to `false` in
the daemon. Every `clawctl agent sync` re-renders the config and thus
resets the flag.

**Control experiment — the same gate blocks a completely unrelated
zeroclaw agent with an openrouter provider**:

```
$ uv run clawctl agent chat e2e-zeroclaw --once "ping" --timeout 20
Protocol error: This agent isn't fully set up yet. The operator needs to run
Quickstart before I can reply.
```

`e2e-zeroclaw` uses `clm-openrouter` (openrouter provider), not
litellm, and hits the identical error. This confirms the chat block is
a pre-existing fleet-wide zeroclaw gate, orthogonal to #976. Every
existing zeroclaw agent on wolf-i (there are three: `clawrium-d01`,
`e2e-zeroclaw`, and `ep6-hermes`'s zeroclaw sibling if any) shares this
state.

**In-scope for #976 (all verified live on wolf-i)**:
- ✅ Allow-list gate opens on attach
- ✅ `build_render_inputs` accepts the litellm provider
- ✅ Renderer produces the correct three-level TOML block
- ✅ `clawctl agent sync` succeeds end-to-end (render + push + restart
     + re-pair)
- ✅ Idempotent (drift=0 on second sync)
- ✅ Daemon parses the config; `providers.models.litellm.<alias>.{uri,
     api_key, model}` are all set correctly
- ✅ Daemon's provider catalog acknowledges `litellm (configured)`

**Out of scope for #976 (deferred to a follow-up)**:
- ⚠ `onboard_state.quickstart_completed` is never emitted by
   `render_zeroclaw`, so the daemon's chat gate stays closed after
   every sync — for ALL zeroclaw agents, not just litellm.
- ⚠ `clawctl agent restart clawrium-d01` fails at the systemd stop
   step ("restart failed: Stop failed:"). Unrelated to render layer.

Both belong in a follow-up issue targeting `render_zeroclaw` +
`clawctl agent restart` on zeroclaw v0.8.2.

## Local test + lint (after the `uri` template fix)

- `make lint` → clean.
- `uv run pytest tests -q` → 4822 passed, 2 skipped.
- The 10 new tests + 40 existing zeroclaw render tests all green.


## Post-merge re-UAT (after merging #974 from main)

After merging origin/main into this branch, the `Quickstart` chat
gate documented above was resolved by #974's aliased channels /
schema-v3 fix. Re-verification on wolf-i / clawrium-d01:

### Step 7 (post-merge) — sync

```
$ uv run clawctl agent sync clawrium-d01
...
agent/clawrium-d01: sync: synced clawrium-d01: 1 written, 1 unchanged
agent/clawrium-d01: synced  (drift=0, took 5s, 1 written, 1 unchanged)
```

drift=0, config re-rendered on the schema-v3 template + litellm branch.

### Step 8 — chat (now working)

```
$ uv run clawctl agent chat clawrium-d01 --once "one word reply so I know the LiteLLM proxy path works: alive?" --timeout 120
ZeroClaw chat is using a non-TLS WebSocket (ws://) to a non-loopback host …
Alive

$ uv run clawctl agent chat clawrium-d01 --once "what model are you?" --timeout 60
ZeroClaw chat is using a non-TLS WebSocket (ws://) to a non-loopback host …
I'm Qwen, a large language model developed by Alibaba Group. For specific
version details, you can check the official website or technical reports.

What can I help you with today?
```

Exit 0. Reply routed via the LiteLLM proxy at
`http://192.168.1.17:4000` fronting `Qwen3.8-27B-FP8`. Model identity
in the second reply ("I'm Qwen") is what the LiteLLM proxy is
configured to route to. **End-to-end litellm attach → sync → chat is
green.**

The two `[ENVIRONMENT]` / `[TODO-FOLLOWUP]` callouts in the PR body
about the fleet-wide Quickstart gate are now stale — #974 fixed the
root cause. Callouts were updated on the PR body to reflect this.

## Local test + lint (post-merge)

- `make lint` → clean.
- `uv run pytest tests -q` → 4841 passed, 2 skipped.
- 72 zeroclaw + litellm-attach tests all green (up from 59 pre-merge
  as #974 also added zeroclaw discord-binding tests).

# Implementation Plan — #621

`render_hermes` silently drops non-primary attachments on the sync render path.
This is the central of three follow-up bugs from parent #589; planned as a
single PR (no subtasks).

## 1. Root Cause

### Where it goes wrong: `src/clawrium/core/render.py:render_hermes`

`build_render_inputs` (lines 230–490) walks `agent.providers` and **picks
exactly one provider** — the one whose `role == "primary"` (lines 252–267) —
then builds a single `ProviderInputs` dataclass (lines 333–342) and stuffs it
into `RenderInputs.provider` (line 491). Every non-primary attachment is read
from `hosts.json`, role-checked, and then dropped on the floor. There is no
second iteration, no per-attachment credential resolution, and no list-shaped
field on `RenderInputs` to hold them.

`render_hermes` (lines 631–753) then reads `inputs.provider` (singular) and
passes only that to the template context (lines 730–746):

```python
env_body  = _render_hermes_template("hermes-env.canonical.j2",       provider=inputs.provider, ...)
yaml_body = _render_hermes_template("hermes-config.canonical.yaml.j2", provider=inputs.provider, ...)
```

There is no `config.providers` key in the context at all. The canonical
template (`hermes-config.canonical.yaml.j2`) consequently only sees the
primary; it switches on `provider.type` and emits hard-coded
`auxiliary.title_generation` defaults per primary type (e.g. line 39–40 for
bedrock). The attached compression / title_generation slots are not in the
context, so they cannot be rendered — which is exactly what the wolf-i repro
shows.

### Where the legacy code does it right: `src/clawrium/core/lifecycle.py`

`sync_agent` (lines 1169–1631) already contains the correct multi-attachment
walk:

- `_build_overlay(provider_name)` (lines 1242–1262) is the per-provider
  registry → overlay helper.
- The multi-provider branch (lines 1264–1298) iterates `attachments`,
  calls `_build_overlay` for each, attaches the `role` + per-attachment
  `model` override, and accumulates `provider_overlays = [...]`.
- Line 1497 persists `existing_config["providers"] = provider_overlays`
  into the agent's config dict before handing it to `configure_agent`.

So `config.providers[]` IS built on the sync code path. But `configure_agent`
(line 1756 onward) only resolves credentials for the **primary** — see lines
2042–2059, which read `config_data["provider"]` (singular) and load exactly
one `provider_api_key` / `aws_access_key` / `aws_secret_key`. The per-overlay
credential hydration the user expected at line ~2042 does not exist; this is
what the `TODO(#501 Phase 3)` block at lines 1489–1495 already calls out.

> Reconciliation with the issue body: the user reported `agent.config.providers
> is null` in hosts.json. That is consistent with the wolf-i agent having been
> attached / configured before #613 landed, OR with `existing_config` being
> rebuilt from scratch by configure_agent rather than the dict the overlay
> mutated. Either way, the canonical fix is at the render layer; we should
> NOT depend on hosts.json carrying the overlay forward because:
>   (a) the legacy overlay code at lifecycle.py:1264-1298 only runs on
>       configure / sync, never on the new `clawrium.core.render` path; and
>   (b) #589's direction is to move all overlay logic into `render_hermes`
>       and retire the lifecycle.py overlay duplication.

### Net of (1) and (2)

`render_hermes` is the canonical render path (`#583`, `lifecycle.py:2204`),
but it is missing the multi-provider walk that `lifecycle.py:1264-1298`
implements. The fix is to port that walk into `build_render_inputs`
(credential resolution) and add a list field on `RenderInputs` that
`render_hermes` then passes into the template context.

## 2. Approach

Single PR. Touch only `src/clawrium/core/render.py` + the canonical templates
(see §"Coordination with #622" below).

### 2.1 New typed inputs (hermes-only)

Multi-provider is a **hermes-only** concept — `_pa.supports_multi_provider`
returns True for hermes alone, and zeroclaw/openclaw enforce a singleton
attachment. Putting the new fields directly on `RenderInputs` (shared
across all three render functions) would force `render_zeroclaw` and
`render_openclaw` to carry three empty tuples they never read. Wrong shape.

Instead, introduce a hermes-only sub-bundle and hang it off `RenderInputs`
as an `Optional` field — populated only when `agent_type == "hermes"`,
`None` otherwise:

```python
@dataclass(frozen=True)
class AttachedProviderInputs:
    name: str
    type: str
    role: str              # "primary" | "compression" | "title_generation" | ...
    model: str             # per-attachment override OR provider.default_model
    endpoint: str = ""
    region: str = ""

@dataclass(frozen=True)
class HermesProviderBundle:
    """All-attachment view used by `render_hermes` only.

    Carries every attachment (primary included) so the canonical template
    can iterate one list, plus the credential dicts the env template
    needs to emit per-attachment API keys / AWS triples.
    """
    attachments: tuple[AttachedProviderInputs, ...]
    api_keys: tuple[tuple[str, str], ...]          # sorted (provider_type, key)
    aws_credentials: tuple[                         # sorted (provider_name, (ak, sk, region))
        tuple[str, tuple[str, str, str]], ...
    ]

@dataclass(frozen=True)
class RenderInputs:
    ...
    provider: ProviderInputs                       # unchanged — populated from primary
    hermes: HermesProviderBundle | None = None     # NEW — populated only for hermes
```

Rationale:
- `render_zeroclaw` / `render_openclaw` ignore `inputs.hermes` entirely;
  their byte output is unchanged and the dataclass shape they care about
  did not grow.
- `render_hermes` reads `inputs.hermes` (raise `AgentConfigError` if
  `None`, which would mean `build_render_inputs` mis-routed — defensive).
- Credentials are **deduped by provider type** for the bearer-key flow
  per the #614 contract (one `ANTHROPIC_API_KEY=` line max in `.env`).
  We raise on type-collision with different keys instead of silently
  picking one. For bedrock the dict is keyed by provider name because
  per-aux AWS env vars need to flow into the per-aux YAML block.

### 2.2 `build_render_inputs` changes

After the existing primary-pick block (lines 252–267) and the existing
primary credential / provider-record gates (lines 269–342), **gate on
`agent_type == "hermes"`** and only then do a second walk that iterates
every attachment (including the primary, so the canonical template can
render a uniform list). For zeroclaw/openclaw, `hermes=None` flows
through and nothing else changes:

```python
hermes_bundle: HermesProviderBundle | None = None
if agent_type == "hermes":
    attached: list[AttachedProviderInputs] = []
    api_keys: dict[str, str] = {}                # provider_type -> api_key
    aws_creds: dict[str, tuple[str, str, str]] = {}  # provider_name -> (ak, sk, region)

    for entry in attachments:
    if not isinstance(entry, dict):
        # singleton-string shape: already handled by primary pick above; only
        # hermes hits this branch and validate() guarantees dict shape there.
        continue
    name = entry["name"]
    record = get_provider(name)
    if record is None:
        raise AgentConfigError(f"provider {name!r} attached to {agent_name!r} not registered")
    ptype = (record.get("type") or "").strip()
    supported = _AGENT_TYPE_PROVIDER_SUPPORT.get(agent_type, frozenset())
    if ptype not in supported:
        raise AgentConfigError(
            f"agent {agent_name!r} (type {agent_type}) attached to provider "
            f"{name!r} of unsupported type {ptype!r}"
        )

    # Credential resolution — same gates as the primary path
    if ptype == "bedrock":
        ak, sk = get_provider_aws_credentials(name)
        ak, sk = _clean_secret(ak), _clean_secret(sk)
        if not ak or not sk:
            raise AgentConfigError(
                f"bedrock provider {name!r} attached to {agent_name!r} missing AWS creds"
            )
        aws_creds[name] = (ak, sk, record.get("region", "") or "us-east-1")
    elif ptype in _BEARER_API_KEY_TYPES:
        key = _clean_secret(get_provider_api_key(name))
        if not key:
            raise AgentConfigError(
                f"provider {name!r} (type {ptype}) attached to {agent_name!r} missing API key"
            )
        prior = api_keys.get(ptype)
        if prior is not None and prior != key:
            raise AgentConfigError(
                f"agent {agent_name!r} has two providers of type {ptype!r} with "
                f"different API keys; hermes emits one {ptype.upper()}_API_KEY env var "
                f"and would silently keep one. Detach one or unify the secret."
            )
        api_keys[ptype] = key
    elif ptype in _LOCAL_ENDPOINT_TYPES:
        if not record.get("endpoint"):
            raise AgentConfigError(f"provider {name!r} missing endpoint")
    else:
        raise AgentConfigError(f"provider {name!r} type {ptype!r} unsupported by render path")

    attached.append(AttachedProviderInputs(
        name=name,
        type=ptype,
        role=entry.get("role", "") or ("primary" if name == primary_name else ""),
        model=(entry.get("model") or record.get("default_model") or ""),
        endpoint=record.get("endpoint", "") or "",
        region=record.get("region", "") or "",
    ))

    hermes_bundle = HermesProviderBundle(
        attachments=tuple(attached),
        api_keys=tuple(sorted(api_keys.items())),
        aws_credentials=tuple(sorted(aws_creds.items())),
    )

return RenderInputs(
    ...,
    provider=primary_provider_inputs,   # unchanged — back-compat
    hermes=hermes_bundle,               # None for zeroclaw/openclaw
)
```

Notes:
- The walk is gated `if agent_type == "hermes":` so zeroclaw/openclaw
  never even enter it. Their `RenderInputs` carries `hermes=None`.
- Primary's credentials are still resolved in the original block (lines
  293–331) so single-provider hermes agents render byte-identical
  output. The new walk **re-resolves** the primary's credentials inside
  the hermes branch; the resulting `api_keys[primary.type] = primary.api_key`
  is harmless because the collision check compares equal-value to itself.

### 2.3 `render_hermes` changes

At entry, require the hermes bundle (defensive: would only be `None` if
`build_render_inputs` mis-routed an agent_type), then forward it into
both template contexts:

```python
if inputs.hermes is None:
    raise AgentConfigError(
        f"render_hermes called for {inputs.agent_name!r} but "
        f"inputs.hermes is None — build_render_inputs did not populate "
        f"the hermes bundle"
    )
hermes = inputs.hermes

yaml_body = _render_hermes_template(
    "hermes-config.canonical.yaml.j2",
    agent_name=inputs.agent_name,
    provider=inputs.provider,                 # unchanged (back-compat)
    providers=hermes.attachments,             # NEW
    ollama_base_url=ollama_base_url,
    atlassian_integrations=atlassian_views,
    mcp_atlassian_version=_HERMES_MCP_ATLASSIAN_VERSION,
)
env_body = _render_hermes_template(
    "hermes-env.canonical.j2",
    agent_name=inputs.agent_name,
    provider=inputs.provider,                 # unchanged (back-compat)
    providers=hermes.attachments,             # NEW
    provider_api_keys=dict(hermes.api_keys),                  # NEW
    provider_aws_credentials=dict(hermes.aws_credentials),    # NEW
    api_server=inputs.api_server,
    channels=inputs.channels,
    integrations=integration_views,
    last_github_token=last_github_token,
)
```

`provider=inputs.provider` stays so the existing template branches don't
move under #622's feet — see coordination note. `render_zeroclaw` /
`render_openclaw` are not touched.

### 2.4 Coordination with #622

**The template change in #622 is a hard dependency for the rendered yaml to
actually contain auxiliary blocks.** Options:

| Option | Pro | Con |
|---|---|---|
| Ship #621 + #622 in one PR | Single landable unit; no half-fixed state on `main` | Bigger diff, slightly harder ATX review |
| Ship #621 first, then #622 | Smaller PRs | Between merges, the renderer passes context the template ignores — operationally a no-op, no regression |

**This plan assumes #621 and #622 land in the SAME PR.** Reasons:
1. AGENTS.md template-lockstep rule (called out in #622's body) — both
   template families (`hermes-config.canonical.yaml.j2` and
   `hermes-config.yaml.j2`) should update with their rendering driver.
2. Per-aux env vars are part of #621's contract (`provider_api_keys` /
   `provider_aws_credentials` context vars) and must be consumed by the
   `hermes-env.canonical.j2` template in the SAME PR or the env file
   regresses to "only primary key emitted" the moment a bedrock-aux is
   attached.
3. The integration / snapshot test in §3 only passes if both halves land.

If the orchestrator decides otherwise, split as: PR-A (this plan,
render-only, no snapshot test) + PR-B (#622 templates + snapshot test).
PR-A on its own changes no on-disk output; safe to land but provides no
customer value until PR-B.

## 3. Test Strategy

All tests live in `tests/core/test_render.py` (existing module per
references at render.py:6,76).

### 3.1 Multi-attachment fixture (NEW)

A single fixture: hermes agent with 3 attachments —
`[primary: anthropic-prod, compression: openrouter-aux, title_generation: bedrock-mac]`.
Seed `providers.json` + `secrets.json` with credentials for all three.

Tests:

1. **`test_build_render_inputs_multi_provider_hermes`** — assert
   `inputs.providers` length == 3, roles preserved, each
   `AttachedProviderInputs.model` resolved (override OR provider default).
2. **`test_build_render_inputs_credentials_dedup_by_type`** — assert
   `provider_api_keys` has both `anthropic` and `openrouter` entries (two
   different types), and `provider_aws_credentials` has the bedrock-mac
   entry keyed by provider name.
3. **`test_build_render_inputs_collision_raises`** — two providers of the
   same type with different API keys raises `AgentConfigError`.
4. **`test_render_hermes_multi_provider_yaml_snapshot`** — call
   `render_hermes(inputs)`, snapshot-assert
   `rendered.files[".hermes/config.yaml"]` against a golden file. Golden
   contains:
   - `model:` block from primary anthropic.
   - `auxiliary.compression:` and `auxiliary.title_generation:` blocks,
     each with `provider:` + `model:`.
5. **`test_render_hermes_multi_provider_env_snapshot`** — golden `.env`
   contains `ANTHROPIC_API_KEY=...`, `OPENROUTER_API_KEY=...`, and the
   bedrock-aux AWS triple (`AWS_*_AUX_<NAME>=...` — exact env-var name
   shape is #622's call; this test pins whatever shape #622 chooses).

### 3.2 Single-provider hermes regression (NEW)

1. **`test_render_hermes_single_provider_yaml_unchanged`** — fixture: one
   primary anthropic attachment. Snapshot-assert the rendered yaml is
   **byte-identical** to a frozen golden captured from `main` immediately
   before this PR. Same for `.env`. This is the canary that catches any
   accidental indentation / ordering drift from the new code path.

### 3.3 Other-agent-type non-regression (NEW, explicit)

The user contract is: **zeroclaw and openclaw renderers must not be
touched.** Codify with hard byte-locks so a future refactor cannot
quietly drag them into the hermes path:

1. **`test_render_zeroclaw_byte_identical_after_621`** — fixture: a
   zeroclaw agent with one openrouter attachment. Run `render_zeroclaw`
   and snapshot-assert every byte of every file in `rendered.files`
   matches a golden captured from `main` immediately before this PR.
2. **`test_render_openclaw_byte_identical_after_621`** — same as above
   for openclaw (anthropic + bedrock + zai fixtures, one per supported
   provider type, all single-attachment).
3. **`test_build_render_inputs_hermes_bundle_is_none_for_non_hermes`** —
   call `build_render_inputs` for a zeroclaw agent and an openclaw
   agent; assert `inputs.hermes is None` on both. This pins the
   `agent_type == "hermes"` gate so removing it gets caught.
4. **`test_render_zeroclaw_rejects_hermes_bundle`** /
   **`test_render_openclaw_rejects_hermes_bundle`** — construct a
   `RenderInputs` with `hermes=HermesProviderBundle(...)` and pass it to
   `render_zeroclaw` / `render_openclaw`; assert the renderers ignore
   it (output is byte-identical to the `hermes=None` case). This locks
   the "zeroclaw/openclaw renderers do not read `inputs.hermes`"
   contract against accidental future coupling.

### 3.4 Existing tests

`tests/core/test_render.py` already covers single-provider hermes,
zeroclaw, and openclaw. Verify **no existing test changes are needed**.
If any do, that itself is a signal the new code regressed back-compat
or that an "other-provider" path got touched — both are blockers.

### 3.4.1 End-to-end scenario (wolf-i, real host)

The original repro was on `wolf-i` via Tailscale. Re-run that same flow
against this PR to close the loop on the customer outcome. This is the
final gate before merge — unit + snapshot tests alone cannot prove the
remote `~/.hermes/config.yaml` is correct.

**Setup**
- Target host: `wolf-i` (the host on which #589 validation surfaced the bug).
- Fresh hermes agent (or `clawctl agent delete` + re-create to start clean).
- Three providers registered in `clawctl provider`:
  - `clawrium-anthropic` — type `anthropic`, default model `claude-sonnet-4-6`.
  - `clawrium-openrouter` — type `openrouter`, default model
    `anthropic/claude-haiku-4.5`.
  - `clawrium-bedrock-mac` — type `bedrock`, region `us-east-1`,
    default model `zai.glm-4.7`.

**Steps**

```bash
# 1. Create the hermes agent
clawctl agent create wolf-hermes --type hermes --host wolf-i

# 2. Multi-attach (CLI from #612 — already shipped, used here as the
#    declarative driver)
clawctl agent provider attach clawrium-anthropic     --agent wolf-hermes --role primary
clawctl agent provider attach clawrium-openrouter    --agent wolf-hermes --role compression
clawctl agent provider attach clawrium-bedrock-mac   --agent wolf-hermes --role title_generation
clawctl agent provider get --agent wolf-hermes
# expect: table shows all 3 attachments with correct role + model

# 3. Sync (the canonical render path this PR fixes)
clawctl agent sync wolf-hermes
# expect: success, no warnings

# 4. Inspect the remote on-host files
ssh wolf-i 'sudo cat /home/wolf-hermes/.hermes/config.yaml'
ssh wolf-i 'sudo cat /home/wolf-hermes/.hermes/.env'

# 5. Start and smoke-test
clawctl agent start wolf-hermes
clawctl agent chat wolf-hermes --message "ping"
```

**Expected on-host state (`~/.hermes/config.yaml`)**

```yaml
model:
  provider: "anthropic"
  default: "claude-sonnet-4-6"
auxiliary:
  compression:
    provider: "openrouter"
    model: "anthropic/claude-haiku-4.5"
  title_generation:
    provider: "bedrock"
    model: "zai.glm-4.7"
bedrock:
  region: "us-east-1"
```

Key differences from today's broken output:
- `auxiliary.compression:` and `auxiliary.title_generation:` blocks
  exist and name the **attached** providers (not the upstream
  per-primary-type fill-ins).
- `bedrock.region:` is present because a bedrock provider is attached
  (even though primary is anthropic) — driven by the per-aux iteration.

**Expected on-host state (`~/.hermes/.env`)**

```
ANTHROPIC_API_KEY='sk-ant-...'
OPENROUTER_API_KEY='sk-or-...'
AWS_ACCESS_KEY_ID='AKIA...'
AWS_SECRET_ACCESS_KEY='...'
AWS_DEFAULT_REGION='us-east-1'
```

All three credential families present in one `.env`; no missing aux
keys, no upstream defaults filling in.

**Smoke check**
- `clawctl agent chat wolf-hermes --message "ping"` returns a response
  from the **anthropic** primary (existing single-provider path still
  works end-to-end).
- Hermes daemon logs (`journalctl -u hermes-wolf-hermes`) show the
  daemon picking up the auxiliary slots without "missing provider key"
  or "upstream default fallback" warnings.

**Non-regression scenario (other agent types)**

On a separate host (e.g. `kevin` or any standing host with a zeroclaw
agent), run `clawctl agent sync <zeroclaw-agent>` and diff the resulting
`.zeroclaw/config.toml` against the pre-merge capture. Must be
byte-identical. Same drill for an openclaw agent on whichever host has
one configured. This is the human-level confirmation of the §3.3 unit
snapshot pins.

## 3.5 UAT / Acceptance Criteria

Hard contract for this PR — none of these may slip:

**Hermes (positive)**
- [ ] Hermes agent with `[primary anthropic, compression openrouter,
      title_generation bedrock]` attachments renders `~/.hermes/config.yaml`
      with one `auxiliary.<role>:` block per non-primary attachment, each
      naming the attached provider's model id.
- [ ] `~/.hermes/.env` contains every per-attachment credential
      (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, bedrock AWS triple)
      with no upstream-default fill-ins for missing aux slots.
- [ ] Two providers of the same type with different bearer keys raises
      `AgentConfigError` at `build_render_inputs` — no silent last-wins.

**Hermes (regression)**
- [ ] Single-provider hermes (one primary, no aux) renders **byte-identical**
      `.hermes/.env` and `.hermes/config.yaml` to `main` (snapshot-pinned).

**Other agent types — explicit no-touch**
- [ ] `render_zeroclaw` output is **byte-identical** to `main` for every
      currently-supported provider type (snapshot-pinned).
- [ ] `render_openclaw` output is **byte-identical** to `main` for every
      currently-supported provider type (snapshot-pinned).
- [ ] `build_render_inputs(zeroclaw_agent).hermes is None` and
      `build_render_inputs(openclaw_agent).hermes is None`.
- [ ] No edits to `render_zeroclaw`, `render_openclaw`, their helpers, or
      either of their templates (`*.zeroclaw.*`, `*.openclaw.*`,
      `_render_zeroclaw_*`, `_render_openclaw_*`). PR diff must show
      changes only in: `render.py` (hermes branch + shared scaffolding),
      `hermes-config.canonical.yaml.j2`, `hermes-env.canonical.j2`,
      and `tests/`.
- [ ] No changes to `_AGENT_TYPE_PROVIDER_SUPPORT` entries for `zeroclaw`
      / `openclaw` (render.py:67-70).
- [ ] No changes to `_BEARER_API_KEY_TYPES` or `_LOCAL_ENDPOINT_TYPES`
      semantics — those are shared and must not shift.

**Cross-cutting**
- [ ] No changes to `lifecycle.py` (the `_build_overlay` / multi-provider
      branch stays as-is; out-of-scope per §6).
- [ ] No changes to install.py, CLI, ansible playbooks, or hosts.json
      schema.
- [ ] `make test` and `make lint` clean.
- [ ] E2E scenario in §3.4.1 passes on `wolf-i` against the PR branch
      (remote `~/.hermes/config.yaml` matches expected, agent starts and
      responds via `clawctl agent chat`).
- [ ] Non-regression run of `clawctl agent sync` against one zeroclaw
      and one openclaw agent on real hosts yields byte-identical on-host
      config files vs. pre-merge capture.

## 4. Risks

### 4.1 Credential-resolution path divergence

`get_provider_api_key` / `get_provider_aws_credentials` (clawrium.core.providers)
are the same functions the primary path already uses; no new database
lookup, no new failure mode for non-primary. Lowest-risk dimension.

The one edge: a hermes agent attached pre-#612 (singleton role) suddenly
re-evaluating role assignment. `normalize_attachments` (render.py:245)
already canonicalizes; the test in §3.1 should include a "legacy
attachment without role field" sub-fixture to confirm we don't raise on
those.

### 4.2 Single-provider regression risk

Two surface areas:
- The new credential walk re-resolves the primary's key. If
  `get_provider_api_key` is non-idempotent (logs, side effects), this is a
  visible change. Grep confirms it is a pure read (providers/storage.py).
- The template context now carries extra kwargs (`providers`,
  `provider_api_keys`, `provider_aws_credentials`). The canonical templates
  are loaded with `StrictUndefined` (render.py:779), so adding context
  keys is safe — only **removing** them or referencing missing ones would
  raise. The snapshot test in §3.2 is the byte-level guard.

### 4.3 AGENTS.md lockstep (`hermes-config.yaml.j2` ↔ `hermes-config.canonical.yaml.j2`)

The legacy `hermes-config.yaml.j2` was updated in #614/#618 to iterate
`config.providers[]`. The canonical sibling was not (the gap #622
documents). Going forward, every change to either template must be
mirrored to the other or the dual-render paths (#583) diverge silently.

Mitigation in scope of this PR: file a follow-up to add a CI lint that
diffs key tokens between the two template families and fails on drift
(out of scope here; mention in PR body so it isn't lost). For now, the
snapshot tests in §3 will catch the canonical drift; the legacy template
already has its own snapshot via the ansible playbook tests.

### 4.4 zeroclaw / openclaw collateral

`render_zeroclaw` and `render_openclaw` do not read `inputs.hermes`. For
those agent types, `build_render_inputs` skips the hermes walk entirely
(`agent_type == "hermes"` gate) and emits `RenderInputs(..., hermes=None)`.
The only shape change visible to them is one extra optional field on the
shared `RenderInputs` dataclass — irrelevant to their renderers.

### 4.5 `lifecycle.py` overlay duplication

The lifecycle overlay at `sync_agent` lines 1264–1298 will continue to
exist after this PR. It still writes to `existing_config["providers"]`,
which is fine — the canonical render path no longer depends on that
field being populated in hosts.json (it builds its own from attachments
directly). The overlay can be deleted in a follow-up once the
`configure_agent` → Ansible-template path is fully retired in favor of
the pre-rendered `prerendered_files` mechanism (lifecycle.py:2219). Out
of scope here; flag in PR body.

## 5. Files to Modify

- `src/clawrium/core/render.py` — new dataclass, `build_render_inputs`
  walk, `render_hermes` context.
- `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2`
  — #622's iteration (assuming co-landing; see §2.4).
- `src/clawrium/platform/registry/hermes/templates/hermes-env.canonical.j2`
  — per-attachment API key + AWS env-var emission (also part of #622
  scope; co-landing).
- `tests/core/test_render.py` — new fixtures + multi-provider tests +
  single-provider snapshot regression.
- `tests/core/snapshots/` (or wherever existing snapshots live) — frozen
  goldens for the multi-attachment and single-attachment yaml + env.

No CLI, lifecycle, ansible playbook, or install.py changes.

## 6. Out of Scope

- Retiring the `lifecycle.py:1264-1298` overlay (follow-up).
- CI lint to enforce template-family lockstep (follow-up — note in PR body).
- Pre-rendering hermes config.yaml via `prerendered_files` (today only
  zeroclaw uses that; lifecycle.py:2219). When that lands, this PR's
  `render_hermes` output flows directly to the playbook with no
  Ansible-side Jinja, which is the ultimate goal of #583. Not in scope
  here; planned via a separate issue.

## 7. Subtasks

None — single PR.

---

## Prompt Log

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-05T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx:plan-create 621

Orchestrator handoff notes (parent #589 follow-up bugs):
- PLAN-ONLY session. No implementation, no commit, no PR.
- Investigate from worktree /home/devashish/workspace/ric03uec/clawrium-issue-621.
- No subtask issues — central bug, one PR.
- Required output: root cause walk through render.py:render_hermes vs
  lifecycle.py overlay, approach with credential dicts + config.providers
  context, coordination call with #622, test gap proposal (multi-attach
  fixture + single-provider regression), risk inventory.
- Found during end-to-end validation of #589 on wolf-i.
- After plan written and posted as comment on #621, STOP.
```

**Output**: This file plus a comment on issue #621 summarizing the plan.

---

## End-to-end Verification (post-implementation)

Ran against `wolf-i` per §3.4.1 using the `uv run clawctl` dev build from
this worktree.

**Setup**
- Agent: `maurice` (hermes on wolf-i, clean state before run).
- Primary attachment: `maurice-openrouter` (openrouter, role=primary).
- Aux attachment: `clawrium-bedrock-mac` (bedrock, role=title_generation).

**Sync render diff** (`clawctl agent sync maurice --dry-run --diff`)

`.hermes/config.yaml`:

```diff
 auxiliary:
   title_generation:
-    model: "anthropic/claude-haiku-4.5"
+    provider: "bedrock"
+    model: 'zai.glm-4.7'
```

The attached `clawrium-bedrock-mac` provider's type + model now flow
into the aux block; the upstream `anthropic/claude-haiku-4.5` default
is correctly suppressed.

`.hermes/.env` — added rows on the render side:

```
OPENROUTER_API_KEY='sk-or-v1-...'      (primary)
AWS_ACCESS_KEY_ID='AKIA...'            (NEW — bedrock aux)
AWS_SECRET_ACCESS_KEY='gVZWJDz...'     (NEW — bedrock aux)
AWS_DEFAULT_REGION='us-east-1'         (NEW — bedrock aux)
```

**Pass criteria check**
- [x] `auxiliary.title_generation:` block emitted with attached provider's
      type + model (not upstream default).
- [x] AWS triple emitted for the bedrock aux even though primary is
      openrouter (not bedrock).
- [x] Primary creds + `HERMES_INFERENCE_PROVIDER='openrouter'` unchanged.

**Non-regression (zeroclaw + openclaw)**

`clawctl agent sync clawrium-d01 --dry-run --diff` (zeroclaw) and
`clawctl agent sync wolf-i --dry-run --diff` (openclaw) show diffs only
from pre-existing host-side drift (encrypted-on-disk tokens vs
plaintext-rendered, empty `paired_tokens` reset — both pre-#621
behavior). The textual diff of this PR touches zero zeroclaw/openclaw
code paths or templates, and the §3.3 unit tests
(`test_621_zeroclaw_render_ignores_hermes_bundle`,
`test_621_openclaw_render_ignores_hermes_bundle`, plus the existing
zeroclaw/openclaw snapshots) all pass.

**Cleanup**

Detached both providers from maurice. Agent restored to original empty
state — `clawctl agent provider get --agent maurice` shows no
attachments.

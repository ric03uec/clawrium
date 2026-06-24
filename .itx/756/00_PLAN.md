# Plan — Issue #756: openclaw litellm primary model mis-rendered on `configure`

> **v3 (simpler renderer).** Replaces v1 and v2. Same end state — install /
> configure / sync all write `~/.openclaw/openclaw.json` through one Python
> function. The renderer change is now a single optional parameter on
> `_render_openclaw_json`, not a separate "install stub" helper.

## Overview

The root cause is two divergent render paths for `~/.openclaw/openclaw.json`:

- `clawctl agent sync` → canonical Python renderer `clawrium.core.render._render_openclaw_json` (handles litellm correctly).
- `clawctl agent configure` and `clawctl agent create` (install) → legacy Jinja template `src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2`, served by `ansible.builtin.template` (no `litellm` branch).

**Fix (user-decided):** collapse all three callers onto the canonical Python renderer. After this change there is exactly **one writer** for `~/.openclaw/openclaw.json` — `_render_openclaw_json` deep-updates the static baseline at `templates/openclaw.json` and the playbook just `copy: content:`-s the bytes. The Jinja template, its tests, and any helpers that exist only to feed it are deleted.

## Preflight results

### Q1: Does the canonical renderer support a no-provider call (install bootstrap)?

**Not today.** `render.py:1408` reads `inputs.provider.type` unconditionally; `build_render_inputs` (`render.py:323`) raises when no provider is attached. At install time, no provider is attached — install fires before `clawctl provider attach`.

**Fix:** make `_render_openclaw_json` accept `provider: ProviderInputs | None`. When `None`, skip the provider-dependent steps (`agents.defaults.model.primary` and `models.providers.<name>`). Everything else (gateway, channels, baseline preservation) stays. Same function, one optional parameter — no second helper, no parallel code path.

### Q2: Does `install.yaml` really need to write `openclaw.json` at install time?

**Yes.** The pair step (`install.yaml:300+`) launches `pair_device.mjs` against `ws://127.0.0.1:{{ openclaw_port }}`. The openclaw daemon must be running by then, and it needs a valid `openclaw.json` with the gateway block. (Compare zeroclaw, which defers `config.toml` to configure — openclaw can't because pair happens inside install.)

### Q3: What does `core/install.py` actually populate for openclaw's `config.*`?

**Only `gateway`** (`install.py:817–826`): port, bind=`lan`, and an auth token minted via `secrets.token_hex(24)`. Everything else the legacy `openclaw.json.j2` emits comes from its own `default(...)` filters — workspace defaults, session defaults, tools defaults, browser defaults, env defaults — and those defaults already exist verbatim in the static baseline `src/clawrium/platform/registry/openclaw/templates/openclaw.json`. So install needs nothing beyond `gateway` to produce a daemon-startable file.

## Architecture (end state)

```
install.py
  └─> _render_openclaw_json(provider=None, gateway=<install-time-gateway>,
                            discord_channel=None)
        → bytes (baseline + gateway only)
        → passed as ansible extravar
        → install.yaml does copy: content: ...

lifecycle.configure_agent
  └─> render_openclaw(build_render_inputs(name))
        └─> _render_openclaw_json(provider=<attached>, gateway=...,
                                  discord_channel=...)
              → bytes (full canonical)
              → passed as ansible extravar
              → configure.yaml does copy: content: ...

lifecycle_canonical.sync_agent_canonical
  └─> render_openclaw(build_render_inputs(name))  ← unchanged
        → bytes → atomic write on host

DELETED: openclaw.json.j2, the four template tasks, TestOpenClawTemplate.
```

One renderer. Three callers. One on-disk format. Bug gone.

## Files to Modify

### Production code

- **`src/clawrium/core/render.py`** — change `_render_openclaw_json` signature: `provider: "ProviderInputs"` → `provider: "ProviderInputs | None"`. In the body:
  - Step 1 (`model["primary"] = provider_default_model`): wrap in `if provider is not None:`.
  - Step 5 (litellm `models.providers.<name>` block): already gated on `provider.type == "litellm"` — extend the guard to `provider is not None and provider.type == "litellm"`.
  - Caller `render_openclaw` (top-level, env + json together) still requires a provider — install doesn't need `.openclaw/env`, only configure/sync do. No signature change there.

- **`src/clawrium/core/install.py`** (~`:817–826`) — after minting `gateway_auth_token`, call `_render_openclaw_json(provider=None, provider_default_model=None, gateway=GatewayInputs(port=openclaw_port, bind="lan", auth=gateway_auth_token), discord_channel=None)`. Pass the bytes as a new ansible extravar `prerendered_openclaw_config_json` (same name as the configure extravar — install and configure use the same key because both feed the same playbook variable name semantics; the playbook tasks live in different files so there's no collision).

- **`src/clawrium/core/lifecycle.py:2510–2580`** — add an `elif resolved_type == "openclaw":` block mirroring the hermes block (2544–2575). Call `render_openclaw(build_render_inputs(unix_agent_name))`. Write `prerendered_files[".openclaw/openclaw.json"]`. Handle `AgentConfigError` and broad `Exception` the same way hermes does.

- **`src/clawrium/core/lifecycle.py:2670–2685`** — extend `ansible_vars` with `"prerendered_openclaw_config_json": prerendered_files.get(".openclaw/openclaw.json", "")`.

- **`src/clawrium/platform/registry/openclaw/playbooks/configure.yaml:208–217`** — replace `ansible.builtin.template` task with `ansible.builtin.copy: content: "{{ prerendered_openclaw_config_json }}"`. Keep `owner`, `group`, `mode 0600`, `no_log: true`, `notify: Restart openclaw service`.

- **`src/clawrium/platform/registry/openclaw/playbooks/configure_macos.yaml:225–233`** — same swap; macOS `group: staff`, `dest: /Users/{{ agent_name }}/.openclaw/openclaw.json`.

- **`src/clawrium/platform/registry/openclaw/playbooks/install.yaml:175–192`** — same swap. Keep the `when: not openclaw_already_installed` gate.

- **`src/clawrium/platform/registry/openclaw/playbooks/install_macos.yaml:230–245`** — same swap.

### Deletions

- **DELETE `src/clawrium/platform/registry/openclaw/templates/openclaw.json.j2`** (224 lines). After the four playbook swaps, zero callers. Grep gate before delete: `grep -rn "openclaw.json.j2" src/ tests/` must return empty.

- **DELETE `tests/test_configure_claw.py::TestOpenClawTemplate`** (~`:1117+`). Replaced by byte-lock fixtures + the parity test described below. Other classes in `test_configure_claw.py` are untouched.

- **Audit `core/install.py` for dead extravar plumbing for openclaw** — anything other than `config["gateway"]` that was set only because the legacy template consumed it. Q3 says only `gateway` is set, so this is likely a no-op audit; document the check.

### Tests

- **NEW `tests/core/test_lifecycle_openclaw_prerender.py`** — mirror `tests/core/test_lifecycle_hermes_prerender.py`. Asserts `configure_agent` populates `ansible_vars["prerendered_openclaw_config_json"]` with bytes equal to `render_openclaw(build_render_inputs(...)).files[".openclaw/openclaw.json"]`. One test per provider type (litellm, openrouter, ollama, bedrock, anthropic, openai).

- **EXTEND `tests/core/test_render.py`** — add tests for `_render_openclaw_json(provider=None, ...)`:
  - returns bytes that parse as valid JSON
  - output preserves the static baseline byte-for-byte except gateway
  - output has NO `agents.defaults.model.primary` key beyond what the baseline ships
  - output has NO `models.providers.<name>` litellm block
  - gateway block contains the supplied port / bind / auth token

- **EXTEND `tests/integration/test_render_matrix.py`** — today only `_setup_openclaw_bedrock_discord` exists for openclaw (`:305`). Add five setup fns: `openclaw_litellm_bare`, `openclaw_openrouter_bare`, `openclaw_ollama_bare`, `openclaw_anthropic_bare`, `openclaw_openai_bare`. Each registers a new cell with a byte-locked fixture under the existing fixtures path (follow the hermes fixture convention — confirm exact path at execution time).

- **PARITY TEST** in `tests/core/test_lifecycle_openclaw_prerender.py`: for each of the six provider types, assert that `configure_agent`'s pre-rendered bytes are byte-identical to what `sync_agent_canonical` produces for the same inputs. This is the load-bearing assertion that the two paths have collapsed into one — if it ever fails, divergence is back.

## Steps

1. **Make `_render_openclaw_json` accept `provider=None`** and skip the two provider-dependent steps. Unit-test in `tests/core/test_render.py`.
2. **Wire `install.py`** to call `_render_openclaw_json(provider=None, ...)` and pass `prerendered_openclaw_config_json` as an extravar.
3. **Switch `install.yaml` + `install_macos.yaml`** to `copy: content:`.
4. **Add the openclaw pre-render branch** in `lifecycle.configure_agent` (after the hermes `elif`). Wire `prerendered_openclaw_config_json` into `ansible_vars`.
5. **Switch `configure.yaml` + `configure_macos.yaml`** to `copy: content:`.
6. **Grep gate**: `grep -rn "openclaw.json.j2" src/ tests/` returns empty. **Delete the template file.**
7. **Delete `TestOpenClawTemplate`** in `tests/test_configure_claw.py`. Audit `core/install.py` for orphan `config.*` extravars set only for the template; remove if found.
8. **Add `test_lifecycle_openclaw_prerender.py`** (per-provider unit + parity tests).
9. **Add byte-lock fixtures** in `test_render_matrix.py` for the five new provider/openclaw combos. Hand-review every fixture diff before committing — golden files.
10. **`make lint && make test`** locally inside the worktree. All green.
11. **UAT on wolf-i** (real host with litellm provider). See UAT section.

## Test Strategy

- **Unit (no-provider renderer)**: `tests/core/test_render.py` — `_render_openclaw_json(provider=None, ...)` returns baseline + gateway, no model writes, no litellm block.
- **Unit (configure pre-render)**: per-provider-type tests in `tests/core/test_lifecycle_openclaw_prerender.py` asserting extravar bytes match `render_openclaw` output.
- **Byte-lock (render matrix)**: five new openclaw cells in `tests/integration/test_render_matrix.py`, each pinning JSON output verbatim. Catches accidental schema drift across all provider types.
- **Parity (load-bearing)**: per-provider-type test asserting `configure_agent`-pre-rendered bytes == `sync_agent_canonical`-rendered bytes. If this fails, divergence is back.
- **Lint/format**: `make lint && make format`.
- **Existing tests**: `make test` — `TestOpenClawTemplate` deletion expected; nothing else should regress.

## UAT (wolf-i, openclaw, litellm provider)

1. `clawctl agent configure wolf-i`
2. `clawctl agent exec wolf-i -- cat ~/.openclaw/openclaw.json | jq '.agents.defaults.model.primary'` → `"clawrium-gtm-litellm/writer"` (prefixed).
3. `... | jq '.models.providers."clawrium-gtm-litellm"'` → non-null block with `baseUrl`, `apiKey`, `models[]`.
4. `clawctl agent restart wolf-i`
5. `clawctl agent exec wolf-i -- agent --agent main --message "hello"` → no `FailoverError: Unknown model: openai/writer`; routed response from the litellm-backed model.
6. **Parity on live host**: `clawctl agent sync wolf-i`; re-run step 2. Byte-identical output.
7. **Fresh-install smoke** (separate host): `clawctl agent create <name> --type openclaw --host <fresh>` → confirm pair succeeds, `openclaw.json` post-install has gateway block + baseline scaffolding but no `agents.defaults.model.primary`. Then `clawctl agent attach <litellm-provider> --agent <name> && clawctl agent configure <name>` → step 2 again. Validates the install → attach → configure handoff.

## Risk / Blast Radius

- **Widest fix in the openclaw playbook surface to date.** Touches install + configure + macOS variants of both. Mitigated by:
  - **The static baseline already contains every default the legacy template was emitting** — the no-provider call to `_render_openclaw_json` is byte-equivalent to "load baseline + patch gateway."
  - **Six byte-lock fixtures** cover every provider type, not just litellm.
  - **Parity test** is the structural guarantee.
- **Removing a 224-line template** — high visual diff, low semantic risk after the four playbook swaps; the grep gate at step 6 enforces zero callers.
- **Install path is the highest-risk swap** because it runs against fresh hosts where rollback is "rebuild the host." UAT step 7 includes a fresh-install smoke on a separate host.
- **Gateway bearer token**: `openclaw.json` embeds it. `no_log: true` must remain on every new `copy:` task — verified at steps 3 and 5.
- **One-parameter renderer change** is low-risk: signature widening, no caller breakage; existing tests cover `provider != None`, new tests cover `provider == None`.

## Out of Scope

- **#755** — openclaw `sync` doesn't run brave-plugin install. Separate fix in `lifecycle_canonical`, separate PR.
- **#757** — channels stale-key hydration leak (`streaming` etc.). Surface shrinks after #756 lands (configure-write path collapses onto canonical render which already drops unmanaged keys) but the hydration-allowlist fix is independent.

## Subtasks

**None.** Multiple files, single coherent architectural collapse. Splitting fragments the byte-lock and parity tests, which only make sense once all callers are on the canonical path. Execute linearly via `/itx:plan-scaffold 756`.

## Complexity

**M.**

## References

- Issue body: `gh issue view 756`
- Hermes precedent (PR #622): `src/clawrium/core/lifecycle.py:2544–2575`, `tests/core/test_lifecycle_hermes_prerender.py`, `src/clawrium/platform/registry/hermes/playbooks/configure.yaml:111,126`
- Zeroclaw precedent (PR #555 / #560 / #567): same pattern earlier; install path defers config write to configure (`zeroclaw/playbooks/install.yaml:174`).
- Canonical renderer: `src/clawrium/core/render.py:_render_openclaw_json` (1579+), `_openclaw_json_baseline` (1548), `render_openclaw` (1383+), litellm branch at `:1446–1456`, `models.providers` block at `:1619+`.
- Baseline JSON: `src/clawrium/platform/registry/openclaw/templates/openclaw.json` (the canonical source `_render_openclaw_json` deep-updates).
- `build_render_inputs` no-provider raise: `src/clawrium/core/render.py:323`.
- Install-time config build: `src/clawrium/core/install.py:817–826`.
- Render matrix: `tests/integration/test_render_matrix.py` (existing `openclaw_bedrock_discord` at `:305`).
- Legacy template tests to delete: `tests/test_configure_claw.py::TestOpenClawTemplate` (~`:1117+`).

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
ok. this is a bug bash session. your job is to orchestrate multiple bugs to a resolution. start with 755, 756, 757. investigate all three and find out if these are still valid and give me a high level plan to address them. dont create any files. use subagents to do this and collate their feedback here

[then]

start with 756, plan-create it in a worktree. the fix is to remove two divergent paths and merge them into a single canonical path.

[then, v2 of plan after preflight]

1. do the preflight check 2. fine change complexity 3. good. 4. yes. everything collapses into a single path. delete whatever doesnt make sense after that. do the research and show me updated plan

[then, v3 after questioning the install_stub approach]

how is the openclaw.json rendered if jinja template is gone? also why is the install called install_stub? i dont get the blocker and workflow

update plan with this. remove previous method
```

**Output**: `.itx/756/00_PLAN.md` (this file, v3) on branch `issue-756-openclaw-canonical-render` in worktree `/home/devashish/workspace/ric03uec/clawrium-issue-756`.

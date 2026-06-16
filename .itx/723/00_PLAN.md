# Implementation Plan — #723

feat(openclaw): accept litellm provider type (extend support set + JSON render)

## Overview

Wire `litellm` into the openclaw render path so an openclaw agent can attach a `type=litellm` provider (e.g. `clawrium-gtm-litellm` → Qwen3-Next-80B-A3B-Instruct-FP8 via the LiteLLM proxy at `inx:4000`) and have `clawctl agent configure` / `clawctl agent sync` emit a working `.openclaw/openclaw.json`.

Reference target: `wolf-i` (openclaw on `wolf.tailf7742d.ts.net`) gets pointed at the same LiteLLM proxy + Qwen3-Next backbone that the gtm pipeline uses.

## Resolved upstream research

openclaw's native shape for custom OpenAI-compatible providers (incl. LiteLLM) is an in-`openclaw.json` `models.providers.<id>` block — there is no env-var path for this provider class. Per `docs.openclaw.ai/gateway/config-tools#custom-providers-and-base-urls`:

```json5
models: {
  mode: "merge",
  providers: {
    "<provider-id>": {
      baseUrl: "http://host:port/v1",
      apiKey: "<bearer>",            // inline or "${ENV_VAR}"
      api: "openai-completions",     // <- the value for LiteLLM
      models: [{
        id: "<model>", name: "<model>", reasoning: false, input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 65536, maxTokens: 16384
      }]
    }
  }
}
```

Model is then referenced as `"<provider-id>/<model>"` in `agents.defaults.model.primary`.

Accepted `api` values: `openai-completions`, `openai-responses`, `anthropic-messages`, `google-generative-ai`. For LiteLLM (and vLLM, and any /v1/chat/completions endpoint) the value is **`openai-completions`**.

Consequence for clawrium:

- **No `.openclaw/env` template change.** LiteLLM's bearer goes inline in `openclaw.json` under `models.providers.<id>.apiKey`. No `OPENCLAW_LITELLM_URL` / `LITELLM_API_KEY` to invent.
- **`_render_openclaw_json` grows a 6th managed path** — `models.providers.<provider-id>` — populated from the attached provider's `endpoint`, `api_key`, and `default_model`. This is the only meaningful render change.
- Precedent: the legacy Ansible template `openclaw.json.j2` already writes an analogous `models.providers.ollama` block (`openclaw.json.j2:117-140`) with `api: "ollama"`. The shape is the same; only `api` and `apiKey` differ.

## Files to Modify

- `src/clawrium/core/render.py`
  - Line 80–89: add `litellm` to `_AGENT_TYPE_PROVIDER_SUPPORT['openclaw']`. Update the deferred-work comment at lines 75–79 to narrow to zeroclaw only.
  - Line 1292–1294: add `litellm` to `_OPENCLAW_SUPPORTED_PROVIDERS`.
  - Line 1299–1302: `_OPENCLAW_MODEL_PREFIX` becomes per-attachment for litellm (the prefix is the clawctl provider name, not a static type-keyed string). Two options under "Open Implementation Detail" below.
  - Line 1496 `_render_openclaw_json`: accept the full `provider` (currently only `provider_default_model`) so the litellm branch can read `endpoint`, `api_key`, and provider `name`. Add the 6th managed path. Update the docstring at lines 1313–1331 to document it.

- `src/clawrium/core/render.py` (caller at line 1422): pass the provider through.

- `tests/core/test_render.py`
  - New positive test: `render_openclaw` succeeds for `type=litellm`; the resulting `.openclaw/openclaw.json` contains a well-formed `models.providers.<provider-name>` block with `api: "openai-completions"`, `baseUrl` ending in `/v1`, and `apiKey` matching the provider secret.
  - Negative test update: the existing "unsupported provider" test that pinned `litellm` as the rejected case (if any) must be re-pointed at `vertex` to preserve negative-path coverage.
  - Byte-lock fixture for openclaw + litellm — mirrors the existing openclaw + ollama / openclaw + openrouter byte-locks.
  - Regression-pin: openclaw + bedrock / + ollama byte-locks unchanged (no surprise drift from the `_render_openclaw_json` signature change).

- `tests/cli/test_provider_attach.py` (or whichever module covers attach validation today)
  - Attach a litellm provider to an openclaw agent → succeeds; second attach → rejected with the existing single-provider-invariant message (preserves #426 behavior on openclaw).

- `CHANGELOG.md`
  - `## [Unreleased]` → `### Added` entry: "openclaw agents can now attach `type=litellm` providers (custom OpenAI-compatible endpoints, e.g. LiteLLM/vLLM proxies)."

- `docs/agent-support/openclaw.md` (if present) and `docs/agent-support/index.md`
  - Remove the openclaw-doesn't-support-litellm carve-out; mirror the hermes row.

## Open Implementation Detail (decide during execution, not before)

The model-prefix table `_OPENCLAW_MODEL_PREFIX` today is type-keyed and static (`"openrouter": "openrouter/"`). For litellm the prefix is the clawctl **provider name**, not the type. Two choices:

1. **Bypass the table for litellm**: in `render_openclaw`, branch on `ptype == "litellm"` and compute `model_id = f"{provider.name}/{provider.default_model}"` directly. Smallest delta. Asymmetric with the other types but honest about the constraint.
2. **Restructure the table to be a per-type callable** (e.g. `_OPENCLAW_MODEL_PREFIX["litellm"] = lambda p: f"{p.name}/"`). Cleaner extensibility for any future per-attachment-keyed provider. Bigger surface.

Recommend (1) — three lines of branching, no API change.

## Steps

1. **Plan landing + AC sync** (this commit). Plan file + updated GitHub AC live on `feat/723-openclaw-litellm` off main. No source code touched yet.

2. **Allow-list bump** in `render.py` (4 lines). Run `make test` — expected: any test that pinned `litellm` as openclaw-unsupported flips to passing-when-it-should-fail. Re-pin those tests to `vertex`. Commit.

3. **`_render_openclaw_json` refactor.** Change signature to accept `provider` (full object). Update single call site. No behavioral change yet (the litellm branch is empty). `make test` green.

4. **Add the `models.providers.<id>` writer for litellm.** Behavioral. `make test` should now have new failing tests in `tests/core/test_render.py` for the byte-lock — they don't exist yet; add them in this same commit.

5. **Model-id prefixing** for litellm — implementation per "Open Implementation Detail" above. `make test` green.

6. **Attach-validation test** in `tests/cli/test_provider_attach.py`. `make test` green.

7. **Docs touch** — remove the openclaw-no-litellm carve-out in `docs/agent-support/*.md`. Mirror to `website/docs/agent-support/*.md` per the mirror rule in AGENTS.md.

8. **CHANGELOG entry** under `[Unreleased]` → `### Added`.

9. **Live verification on `wolf-i`.** Pre-state snapshot of `~/.config/clawrium/hosts.json` and `wolf-i`'s `.openclaw/openclaw.json` saved to `.itx/723/snapshots/`.
   - `clawctl agent provider detach wolf-i clawrium-bedrock`
   - `clawctl agent provider attach wolf-i clawrium-gtm-litellm --role primary`
   - `clawctl agent sync wolf-i` — expect clean (1 written, 1 unchanged, drift=0).
   - `clawctl agent exec wolf-i -- --version` — succeeds.
   - SSH-direct smoke (curl one-shot) against the gateway chat endpoint with the persisted bearer — single-sentence completion routed via the Qwen3-Next backbone on inx. Capture command + response in `.itx/723/02_EXECUTE.md`.
   - **Rollback:** detach litellm + re-attach `clawrium-bedrock` from snapshot. Documented in plan so it's not improvised at the wrong moment.

10. **Update root `CHANGELOG.md`** if the docs touch in step 7 surfaced any user-visible behavior beyond the bare "openclaw + litellm now works" line.

## Test Strategy

- **Unit (deterministic):** byte-lock fixtures in `tests/core/test_render.py` for openclaw + litellm cover the `models.providers` block shape, the `agents.defaults.model.primary` prefix, and the absence of any new env-template branch (env body unchanged from openclaw + ollama baseline modulo the provider-specific section).
- **CLI integration (in-process):** attach-validation against a fixture host config — no SSH, no network.
- **Live (manual, on wolf-i):** sync + exec + smoke chat against the real LiteLLM/vLLM stack on inx. This is the acceptance bar from #723; non-negotiable for merge.

## Acceptance Criteria (revised — replaces issue body AC)

- [ ] `_AGENT_TYPE_PROVIDER_SUPPORT['openclaw']` and `_OPENCLAW_SUPPORTED_PROVIDERS` both include `litellm`. The deferred-work comment at `render.py:75-79` is narrowed to zeroclaw only.
- [ ] `_render_openclaw_json` accepts a full provider and writes a `models.providers.<provider-name>` block with `baseUrl: <endpoint>/v1`, `apiKey: <bearer>`, `api: "openai-completions"`, and one `models[]` entry built from `default_model`. The 5 existing managed paths are unaffected.
- [ ] `agents.defaults.model.primary` for an openclaw + litellm attachment is `"<provider-name>/<default_model>"` (e.g. `clawrium-gtm-litellm/writer`).
- [ ] `.openclaw/env` is unchanged for litellm vs the openclaw + ollama baseline — no new env vars emitted, no template branch added.
- [ ] `clawctl agent provider attach <openclaw-agent> <litellm-provider> --role primary` succeeds and writes the attachment in `hosts.json`.
- [ ] `clawctl agent configure <openclaw-agent>` and `clawctl agent sync <openclaw-agent>` both succeed against an openclaw agent whose primary is a `litellm` provider. Sync reports drift=0 on a second consecutive invocation.
- [ ] Byte-lock fixture added to `tests/core/test_render.py` for openclaw + litellm.
- [ ] Existing openclaw byte-locks (ollama, openrouter, bedrock) are byte-identical after the refactor.
- [ ] Single-provider invariant on openclaw still rejects a second provider attachment (preserves #426 behavior).
- [ ] Live verification on `wolf-i`: provider swap to `clawrium-gtm-litellm`, sync clean, exec returns, smoke chat through the gateway routes via the Qwen3-Next-80B-A3B-Instruct-FP8 backbone on inx. Command + response recorded in `.itx/723/02_EXECUTE.md`.
- [ ] `CHANGELOG.md` `[Unreleased]` → `### Added` entry shipped in the same PR.
- [ ] `docs/agent-support/*.md` + the mirrored `website/docs/agent-support/*.md` updated to remove the openclaw-no-litellm carve-out.

## Risks

- **`_render_openclaw_json` signature change.** Callers: `lifecycle.py`, `lifecycle_canonical.py`. Both call sites must be updated in lockstep. Single-PR scope means any miss is caught by the test suite before merge.
- **`baseUrl` normalization.** Providers' `endpoint` field may or may not include a trailing `/v1`. Inspect existing stored providers; normalize in `_render_openclaw_json` to always append `/v1` if absent (matching what hermes does for litellm). Add a unit test pinning both shapes.
- **Discord pairing on wolf-i** (guild `1475252698466226357`, channel `1492934246052921344`) must survive the provider swap. Byte-lock test must pin that `channels.discord` is untouched by the litellm branch.
- **Drift between gtm changelog and `hosts.json`** for the `clawrium-gtm` agent itself — `.sdlc/clawrium-gtm/CHANGELOG.md` claims rebind to `clawrium-gtm-litellm` but `hosts.json` still shows `clm-openrouter`. Out of scope here. Flag in PR description; do not fix in this PR.
- **`contextWindow` / `maxTokens` defaults.** vLLM's Qwen3-Next is run with `--max-model-len 65536`. The legacy ollama branch defaults to `131072 / 16384`. Use `65536 / 16384` as the litellm defaults to match the gtm vLLM config; let the provider record optionally override via `provider.context_window` / `provider.max_tokens` (already supported on ollama, mirror it).

## Subtasks

None. Single contained PR. Three render-layer files + tests + docs + one live verification. `complexity:s` label is correct.

## Prompt log

### Plan

**Stage**: planning
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-15T00:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-plan-create 723 (dont create file yet)
```

```prompt
ok. now write the plan and update acceptance tests. this should be part of one pr. write thie plan in a worktree off of main
```

**Output**: `.itx/723/00_PLAN.md` (this file) on branch `feat/723-openclaw-litellm` off `origin/main` in worktree `~/workspace/ric03uec/clawrium-issue-723/`. Issue #723 acceptance criteria rewritten in lockstep to reflect the Path B (in-JSON `models.providers`) resolution from upstream openclaw docs (`docs.openclaw.ai/gateway/config-tools#custom-providers-and-base-urls`). No source code changed yet.

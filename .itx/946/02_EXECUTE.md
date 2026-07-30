# Issue #946 — Phase 4 Execution (ITX-STUCK best-guess)

**Date**: 2026-07-24
**Branch**: `issue-946-provider-credentials-gateway`
**Base**: `issue-945-delete-bare-openclaw`
**Executor**: `/itx:execute 946 --pr-base=issue-945-delete-bare-openclaw`

## Context

Parent-plan §7.5 (upstream NemoClaw gateway CLI verb for provider
registration) remains UNRESOLVED — see `.itx/946/00_BLOCKED.md` for the
full rationale. Under the orchestrator's ITX-STUCK directive, this
execution proceeds with a **best-guess** integration surface and opens a
PR marked `[ITX-STUCK]` so the owner can course-correct at review time.

## What changed

1. **`src/clawrium/core/nemoclaw.py`** — added
   `gateway_register_provider(sandbox, name, api_key, base_url)`
   returning a `NemoclawCommand` whose `argv` is
   `nemoclaw <sandbox> gateway provider add <name> --api-key <k> --base-url <u>`.
   All four inputs are validated (sandbox pattern, provider-name
   pattern, base_url scheme + no-whitespace/control, api_key
   no-newline/null). Single seam for a future upstream-verified swap.

2. **`src/clawrium/platform/registry/openclaw/templates/openclaw-env.canonical.j2`**
   — deleted the provider block that emitted
   `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` /
   `ZAI_API_KEY` / `OPENCODE_API_KEY` / `OPENAI_BASE_URL` /
   `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
   `AWS_DEFAULT_REGION` / `OPENCLAW_OLLAMA_URL` into the sandbox's
   `.openclaw/env`. Non-provider env output (gateway vars, default
   model id, channel tokens, integration tokens) is unchanged.

3. **Tests**
   - `tests/core/test_nemoclaw_builder.py`: `TestGatewayRegisterProvider`
     covering argv shape + input-validation rejection paths.
   - `tests/core/test_render.py`: new parametrized non-leakage test
     `test_openclaw_provider_credentials_absent_from_sandbox_env` across
     every supported provider type. Byte-lock strings updated. Existing
     positive-emission asserts flipped to negative.
   - `tests/integration/test_render_matrix.py`: `expected_keys` on
     openclaw cells (openrouter, ollama, anthropic, openai,
     bedrock+discord) updated to key off `OPENCLAW_DEFAULT_MODEL` /
     channel token instead of the deleted provider vars.
   - `tests/cli/clawctl/provider/test_registry.py`: opencode
     end-to-end assertion flipped.

4. **`CHANGELOG.md`** — new `### BREAKING` entry documenting the
   sandbox env change and the "re-run configure on every openclaw" op.

## What did NOT change (deliberately)

- **`_render_openclaw_json`'s litellm inline `apiKey`
  (`render.py:2213`)** — still writes the bearer into
  `.openclaw/openclaw.json`. The upstream openclaw daemon reads it
  from the JSON directly and does not honor an env-var alternative
  today (see #723 for the pin). Removing it without a gateway
  substitute would break every litellm openclaw agent. Called out
  under `[UNRESOLVED]` on the PR.

- **`openclaw/playbooks/configure.yaml` + legacy `.env.j2`** — not
  invoked by modern kubectl-style `clawctl agent configure` (per
  AGENTS.md "Openclaw uses the same shape as zeroclaw…"). Left
  untouched to keep the diff surgical.

- **The Ansible seam that would actually shell out to
  `gateway_register_provider(...).argv` on the host** — deferred.
  Wiring it into `core/lifecycle_canonical.py` (analogous to
  `_openclaw_install_plugins` / `_hermes_install_slack_mcp`) is the
  natural next commit, but doing so before §7.5 is answered would
  bake the guessed argv into ansible-runner extravars. That's a
  bigger blast radius than shipping only the render-layer strip +
  builder API. Called out under `[UNRESOLVED]`.

## Verification

- `make lint` → clean (Python + GUI ESLint both pass).
- `make test` → **4727 passed, 8 skipped**.
- Non-regression: every `render_hermes` / `render_zeroclaw` positive
  API_KEY assertion still holds; the deleted block is openclaw-only.
- Real-host UAT on wolf-i: **NOT PERFORMED**. Called out under
  `[ENVIRONMENT]` — orchestrator to sweep post-merge once §7.5 is
  answered and the ansible seam lands.

## Prompt Log

**Stage**: execute
**Skill**: /itx:execute
**Timestamp**: 2026-07-24T00:00:00Z
**Model**: claude-opus-4-7

```prompt
946 --pr-base=issue-945-delete-bare-openclaw. CRITICAL DIRECTIVE from orchestrator:
§7.5 blueprint override is unresolved and the orchestrator cannot answer it.
Per itx-execute skill contract you MUST NOT halt or ask; make best-guess and
open a PR with [ITX-STUCK] marker. Best-guess API: extend
src/clawrium/core/nemoclaw.py with gateway_register_provider(sandbox, name,
api_key, base_url) that shells out to nemoclaw <sandbox> gateway provider add
<name> --api-key <k> --base-url <u> (guessed from NemoClaw idioms). Delete
provider env injection from src/clawrium/core/render.py openclaw path. Add
tests. Non-regression for hermes/zeroclaw shared render. Run make lint &&
make test. Run ATX iterations. Open PR against issue-945-delete-bare-openclaw
with [ITX-STUCK] marker + Callouts sections: [DECISION] documenting the
guessed API, [UNRESOLVED] pointing at #11 §7.5, [ENVIRONMENT] noting wolf-i
UAT deferred to post-merge orchestrator sweep. If in doubt: implement, do
not ask.
```

**Output**: Render-layer strip + `gateway_register_provider` builder +
test coverage. Ansible wiring + host UAT deferred pending §7.5 and
post-merge orchestrator sweep.

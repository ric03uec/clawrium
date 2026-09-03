# Issue #976 — feat(zeroclaw): accept litellm provider type

## Scope

Extend zeroclaw's renderer + template to accept a `litellm`-type provider,
matching the shape already used by `opencode` on zeroclaw and by `litellm`
on openclaw (#723) and hermes (#705).

## Three contained edits (per issue body)

1. **Allow-list** — `src/clawrium/core/render.py:94`: add `"litellm"` to
   `_AGENT_TYPE_PROVIDER_SUPPORT["zeroclaw"]`. Delete or narrow the
   deferred-work comment at lines 83–88 (this issue closes that carve-out).

2. **Renderer normalization** — `render_zeroclaw` (~line 1482): extend the
   `provider.type in ("opencode", "opencode-go")` branch to also cover
   `"litellm"`. Strip trailing `/`, append `/v1` if absent. Behaviour must
   be byte-identical to the existing opencode path.

3. **Template** — `src/clawrium/platform/registry/zeroclaw/templates/zeroclaw-config.toml.j2`
   (~lines 48–51): add a `{% elif provider.type == "litellm" %}` branch that
   emits both `base_url` and `api_key` under
   `[providers.models.litellm.<alias>]`. Existing `ollama` / `opencode` /
   default branches MUST remain byte-identical.

## Not changing

- `.zeroclaw/zeroclaw-env.conf` — bearer lives inline in `config.toml`
  under `providers.models.litellm.<alias>.api_key`, matching opencode.
- Multi-provider attachments — still hermes-only (single-provider
  invariant on zeroclaw stands).
- Zeroclaw channel schema (#974) — untouched.

## Tests (per acceptance criteria)

Add to `tests/core/test_render.py`:

- Renderer emits `[providers.models.litellm.<alias>]` with correct
  `model`, `base_url`, `api_key`.
- Endpoint normalization test (with + without trailing `/v1`; with + without
  trailing `/`).
- Byte-lock fixture: `tests/core/fixtures/zeroclaw_config_litellm.toml`.

Verify byte-lock fixtures for existing zeroclaw providers
(openrouter, anthropic, openai, ollama, opencode, opencode-go) remain
byte-identical after the change.

Verify single-provider-attach invariant on zeroclaw still rejects a second
attach.

## Docs

- `CHANGELOG.md` `[Unreleased]` → `### Added`: single line for the litellm
  support extension.
- `docs/agent-support/*.md` + `website/docs/agent-support/*.md` — remove
  the zeroclaw-no-litellm carve-out.

## Live UAT — MANDATORY BEFORE PR (per user instruction)

The user's explicit instruction: **do NOT open the PR until the integration
works on an existing agent on `wolf-i`.** No exceptions.

Verification recipe (record command + response in
`.itx/976/02_EXECUTE.md`):

1. From this repo's dev checkout, install the branch on `wolf-i`:
   ```bash
   clawctl host list        # confirm wolf-i alias reachable
   ```
2. Confirm the target agent is `clawrium-d01` on `wolf-i` and the target
   provider is `clawrium-gtm-litellm` (type=litellm, endpoint
   `http://192.168.1.17:4000`).
3. Attach:
   ```bash
   clawctl agent provider attach clawrium-d01 clawrium-gtm-litellm
   ```
   (May already be attached — surface current state, don't blindly
   re-attach.)
4. Sync:
   ```bash
   clawctl agent sync clawrium-d01
   ```
   Expected: exits 0, no renderer error, config rendered.
5. Idempotency:
   ```bash
   clawctl agent sync clawrium-d01     # drift=0 expected
   ```
6. Chat:
   ```bash
   clawctl agent chat clawrium-d01 --once "ping"
   ```
   Expected: reply routed through LiteLLM proxy's `Qwen3.8-27B-FP8`.

Paste the command + response verbatim into `.itx/976/02_EXECUTE.md`.

If UAT fails: fix, re-verify. **Do not open the PR with a failing UAT.**

## Review — atx CLI (per user instruction)

After tests pass locally AND wolf-i UAT is clean:

1. Push branch.
2. Open draft PR (base=main).
3. Run `atx review` on the branch (project supervisor / task per the
   local `atx` CLI conventions).
4. Iterate up to 3 rounds. If not clean after 3, open the PR with an
   `[ITX-STUCK]` marker and Callouts documenting each unresolved blocker.
5. On clean, mark PR ready for review.

Prefer the ATX CLI over any MCP path — the user said "use atx cli".

## Callouts on the PR body

Every PR opened must include a `## Callouts` section (write `_None._` if
empty). Follow the AGENTS.md ATX PR template.

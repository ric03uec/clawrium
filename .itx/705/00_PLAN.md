# Implementation Plan — Issue #705

**Title**: feat(provider): add litellm provider type (URL + API key, OpenAI-compatible)
**Labels**: agent-created, complexity:s
**Mode**: single execution task (no subtasks)
**Review**: manual (ATX skipped per operator instruction)

## Overview

LiteLLM is an OpenAI-compatible proxy. Today clawrium supports `ollama` (URL,
no key) and bearer-token cloud types (`openai`, `openrouter`, `anthropic`,
`zai`) — but nothing that combines "free-form URL" + "bearer API key" + the
hermes `provider: "custom"` render path. This plan adds a new provider type
`litellm` that does exactly that: the `ollama` shape plus a bearer key, and
the same `provider: "custom"` / `base_url: <url>/v1` / `default: <model>`
render output that ollama already produces.

End-to-end target: migrate the `clawrium-gtm` hermes agent's `curator` and
`compression` roles (currently using ollama-bypass to `gemma4:31b`) onto a
real litellm provider fronted by `inx` at `http://192.168.1.17:4000`.

## Files

| File | Change |
|---|---|
| `src/clawrium/core/providers/storage.py` | Add `"litellm"` to `PROVIDER_MODELS`. Add `fetch_litellm_models(endpoint, api_key)` mirroring `fetch_ollama_models`: GET `<endpoint>/v1/models` with `Authorization: Bearer <key>`, parse `data[].id`. Reuse SSRF guard from `validate_ollama_url`. |
| `src/clawrium/cli/provider.py` | `add`: accept `--url` for litellm, prompt for API key, require `--model`. `edit`: same `--url` rule + `--update-key`. `refresh`: branch on type → `fetch_litellm_models` with key from `get_provider_api_key`. `list`: show URL + masked key. Fix stale `clm` → `clawctl` in help text. |
| `src/clawrium/core/render.py` | Add `"litellm"` to `_BEARER_API_KEY_TYPES`. Add to all three sets in `_AGENT_TYPE_PROVIDER_SUPPORT`. Add `elif ptype == "litellm"` next to ollama branch computing `<endpoint>/v1`. Plumb URL + key into template inputs for primary and aux. |
| `src/clawrium/platform/registry/hermes/templates/hermes-config.canonical.yaml.j2` | `{% elif provider.type == 'litellm' %}` branch — same `provider: "custom"` / `base_url` / `default` shape as ollama. Extend aux loop to emit `base_url` when entry type is `litellm`. |
| `src/clawrium/platform/registry/hermes/templates/hermes-env.canonical.j2` | `{% elif provider.type == 'litellm' %}` branch: `HERMES_INFERENCE_PROVIDER='custom'` + `LITELLM_API_KEY=<key>`. For aux: `LITELLM_<ROLE_UPPER>_API_KEY=<key>`. |
| `tests/test_core_providers.py` | `litellm` in `test_validate_provider_type_valid`. `fetch_litellm_models` happy + auth-header + SSRF-block tests. |
| `tests/test_cli_provider.py` | `test_add_litellm_success`, `test_edit_litellm_url`, `test_edit_litellm_update_key`, `test_refresh_litellm` (mock `/v1/models`), `test_types_lists_litellm`. |
| `tests/core/test_render.py` | Hermes test: litellm primary → `config.yaml` has `base_url: '<url>/v1'`, `.env` has `LITELLM_API_KEY=...`. Aux variant. |
| `CHANGELOG.md` | `### Added` entry under `[Unreleased]`. |

## Steps (single task)

1. **Storage layer** — add `litellm` to `PROVIDER_MODELS`, write
   `fetch_litellm_models` with SSRF guard + bearer header.
2. **Storage tests** — `make test tests/test_core_providers.py` passes.
3. **CLI surface** — extend `add`/`edit`/`refresh`/`list`/`types` to handle
   litellm. Fix stale `clm` → `clawctl` strings while in there.
4. **CLI tests** — `make test tests/test_cli_provider.py` passes.
5. **Render path (primary)** — add litellm to `_BEARER_API_KEY_TYPES` +
   `_AGENT_TYPE_PROVIDER_SUPPORT`. Wire `litellm_base_url` mirroring
   `ollama_base_url`. Add Jinja branches in both hermes templates for primary.
6. **Render path (auxiliary)** — extend hermes-config aux loop to include
   `base_url` for litellm aux entries; extend hermes-env to emit
   `LITELLM_<ROLE_UPPER>_API_KEY` for each litellm aux.
7. **Render tests** — `make test tests/core/test_render.py` passes for
   primary + aux litellm scenarios.
8. **Full suite + lint** — `make test` + `make lint` clean.
9. **E2E on `clawrium-gtm`** (operator verification, post-merge):
   - `uv run clawctl provider add inx-litellm --type litellm --url http://192.168.1.17:4000 --model gemma4:31b` (prompts for master key).
   - `uv run clawctl provider refresh inx-litellm` — verify `available_models`.
   - Detach + reattach: `uv run clawctl agent provider detach clawrium-gtm-writer-gemma4 --agent clawrium-gtm` then `uv run clawctl agent provider attach inx-litellm --agent clawrium-gtm --role curator --model gemma4:31b`.
   - `uv run clawctl agent sync clawrium-gtm`.
   - SSH to `wolf-i`, verify `~/.hermes/config.yaml` has `auxiliary.curator.provider: "custom"` + correct `base_url`/`default`, and `~/.hermes/.env` has `LITELLM_CURATOR_API_KEY=…`.
   - Restart confirmed clean; functional probe via hermes API server (`0.0.0.0:8681`) on the curator role.
   - Repeat for `compression` role.
10. **CHANGELOG** — `### Added` entry.
11. **Commit + PR** — manual review (ATX skipped per operator instruction).

## Test Strategy

- Unit tests cover: storage (provider type registration, fetch helper, SSRF
  guard), CLI (add/edit/refresh/list/types), render (primary + aux for hermes).
- `make test` + `make lint` are the gate for the PR.
- E2E verification on `clawrium-gtm` is operator-driven post-merge (requires
  the LiteLLM master key and SSH access to `wolf-i`).

## Risks

- **Aux env var collision** — multiple litellm providers attached to one
  hermes agent at different roles would collide on `LITELLM_API_KEY`. Mitigated
  with `LITELLM_<ROLE_UPPER>_API_KEY` namespacing for aux slots; primary keeps
  the flat `LITELLM_API_KEY`.
- **Aux render path expansion** — the existing hermes aux loop emits only
  `provider`/`model` for each aux entry. Custom-endpoint types (litellm) need
  `base_url` too. The template change is small but worth flagging — it's the
  only spot where the litellm shape diverges from a pure ollama clone.
- **LiteLLM reachability from `wolf-i`** — E2E presumes the LiteLLM at
  `192.168.1.17:4000` is reachable from `wolf-i`. If not, hermes startup fails
  loudly; surfaces in the systemd unit, not silently masked.

## Subtasks

None — single task execution.

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-13T00:00:00Z
**Model**: claude-opus-4-7

```prompt
705 dont dont create plan file. just giv eme plan first

(follow-ups in same session)
— "dude. what the fuck. the current cli is clawctl no clm. seriously? do  your researrch"
— "what the fuck are you talking about. this issue is to add another rgsitry provider like ollama but for litellm. no structural changes or migration? what am i msising"
— "no subtatks. i want one task only update plan and steps"
— "yes usethe litellm api key format. also the end to end test is to make this work end to end on an existing hermes agent. updte the plan based on this. use the existing hermes agent called clawrium-gtm to udpate this and make it work"
— "update plan send pr"
— "dont do atx review"
```

**Output**: `.itx/705/00_PLAN.md` (this file) + execution to follow on
branch `feat/litellm-provider-705`, manual-review PR.

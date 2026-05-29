# Issue #556 — Execution Log

Subtask of #555: F1 + F2 deterministic `build_render_inputs` and pure
`render_hermes / render_zeroclaw / render_openclaw`.

## Execution

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-29T19:13:00Z
**Model**: claude-opus-4-7

```prompt
/itx:execute 556
```

**Output**: New module `src/clawrium/core/render.py` (RenderInputs +
build_render_inputs raising on missing attachment + pure renderers
branching only on provider.type) plus comprehensive unit + idempotency
tests in `tests/core/test_render.py`. Not wired into lifecycle.

## ATX Review Iterations

### Iteration 1 — Rating 2/5

Cost ~$2.68 USD; 4 specialists; 10 blocking issues across renderer
contracts, manifest fidelity, security, and test coverage:

- **B1** `zai`/`vertex` accepted by build but missing from hermes/zeroclaw renderers
- **B2** vertex emits bearer token as `GOOGLE_APPLICATION_CREDENTIALS` (must be a path)
- **B3** render_zeroclaw missing `[autonomy] shell_env_passthrough` (mandatory grep gate)
- **B4** render_openclaw output key `.openclaw/.env` should be `.openclaw/env`
- **B5** `ChannelInputs` missing `allow_all_users` / `home_channel_name` / `home_channel_thread_id`
- **B6** `GatewayInputs` missing `allow_public_bind`
- **B7** YAML key injection via raw `integration.name` in `mcp_servers`
- **B8** NUL-byte secrets pass truthiness check (need `_clean_secret`)
- **B9** Slack render path entirely untested
- **B10** Empty/null `provider_type` path untested

### Iteration 2 — Infrastructure timeout

ATX review timed out twice (12m, 18m) on the verification pass. All
10 iter-1 blockers and most warnings (W2–W4, W6–W8) addressed in
code + tests; local `make test` (3549 passed) and `make lint` clean.
Per the `/itx:execute` skill's resilient-ATX contract, the PR opens
with the iteration history documented and a Callout flagging the
incomplete verification round.

## Verification

- `make test-py`: 3549 passed, 7 skipped
- `make lint-py`: ruff clean

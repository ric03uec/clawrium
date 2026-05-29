# Issue #448 — Stable secrets keying via immutable `key_id`

## Summary

`secrets.json` keys per-agent entries as `<hostname>:<type>:<name>`, where `hostname` is mutable. When operators change a host's network coordinates (IP → DNS, LAN IP → Tailscale name, renumber), every per-agent secret on that host becomes silently unreachable on the next `configure`/`chat`/`sync`.

Affected secret types: Discord bot tokens, Slack tokens, GitHub PATs, provider API keys (OpenRouter / Anthropic / OpenAI / Bedrock), hermes `HERMES_API_SERVER_KEY` bearer.

This plan implements **stable keying via `host["key_id"]`** (per issue #448's proposed fix), with explicit scope expansion to cover all `get_instance_key` callsites and the env-file consistency invariant that triggered the original maurice-on-wolf-i breakage (separate context: chat 401 traced to drift between `secrets.json[192.168.1.36:hermes:maurice]` and the daemon's `.env` rendered from `wolf.tailf7742d.ts.net:hermes:maurice`).

## Root cause

`get_instance_key(host, type, name)` in `src/clawrium/core/secrets.py:225` accepts an arbitrary string and is called everywhere with `host["hostname"]`. Hostname is the network address of the host — operators routinely mutate it. `key_id` (initialized to `hostname` at `clawctl host create` time, `src/clawrium/cli/clawctl/host/create.py:110`) is *intended* to be stable but:

1. Re-running `clawctl host create` against an existing host overwrites `key_id` to the new hostname.
2. No callsite uses `key_id` today; they all use `hostname` directly.

Result: any hostname mutation orphans every secret for every agent on that host.

## Scope

### In scope

1. **All `get_instance_key` callsites switch to `host["key_id"]`.** Enumerated (current grep):
   - `src/clawrium/core/install.py:364, 713, 775`
   - `src/clawrium/core/lifecycle.py:312, 1380, 1535, 1611, 1722, 1745, 2284`
   - `src/clawrium/cli/chat.py:743`
   - Any others surfaced by a fresh grep at execution time
2. **`clawctl host create` preserves `key_id` on re-record.** When `clawctl host create <ip> --alias <existing-alias>` is run against a host whose alias already exists, update `hostname`/`port`/`addresses` but preserve the existing `key_id`. Print a one-line notice: `host <alias>: hostname <old> → <new> (key_id preserved)`.
3. **Env-file consistency invariant in `lifecycle.start_agent`** (hermes-specific, applies to other env-file-rendering agents if they exist). Before starting the daemon, compare the on-host env file's `API_SERVER_KEY` against `secrets.json[<key_id>:hermes:<name>].HERMES_API_SERVER_KEY.value`. On mismatch, trigger `configure_agent` (re-render + restart) before proceeding. **`secrets.json` is authoritative; on-host env files are derived.**
4. **Doc updates**: `docs/agent-support/hermes.md` instance-key format → `<key_id>:hermes:<name>`; `docs/host-preparation.md` note on `key_id` immutability.
5. **Tests** (see below).

### Out of scope (deliberately excluded)

- **Automatic in-code migration** of legacy `<hostname>:*` secrets entries. Per maintainer instruction: no migration code. Existing affected agents will be migrated manually on each affected machine. New installs use the stable keying from day one.
- **Alias rename**: deliberately invalidates secrets (acknowledged by #448's out-of-scope note — alias rename is a deliberate identity change). Alias is not part of the key path; alias change has no effect on secret resolution. No work needed.
- **Zeroclaw gateway bearer in `hosts.json.gateway.auth`**: governed by issue #437's rotation contract (always re-pair on configure/sync/restart). Untouched in this PR.
- **`clawctl secrets migrate` command**: deferred. If users on other machines complain, file a follow-up.

## Implementation phases

### Phase 1 — `get_instance_key` callsite sweep

Goal: every per-agent secret lookup keys by `host["key_id"]`, not `host["hostname"]`.

1. Grep for `get_instance_key(` across `src/`; verify the inventory above is complete.
2. For each callsite, change the first argument from `host["hostname"]` (or equivalent) to `host["key_id"]`. Use a defensive fallback for malformed records: `host.get("key_id") or host["hostname"]` — preserves legacy behavior when `key_id` is absent (e.g. hand-edited `hosts.json`); record this as a `[DECISION]` callout.
3. Update `get_instance_key`'s docstring in `src/clawrium/core/secrets.py:225` to specify "stable host identifier (`host["key_id"]`); MUST NOT be `hostname` which is mutable."
4. Update `secrets.py:__all__` exports unchanged.

### Phase 2 — `clawctl host create` preserves `key_id`

Goal: re-recording an existing host updates network coordinates without rotating its identifier.

1. `src/clawrium/cli/clawctl/host/create.py`: before constructing the new record (around line 108-124), check if a host with the same `alias` already exists via `clawrium.core.hosts.get_host_by_key_id` or alias lookup.
2. If existing: preserve `key_id` from the existing record; allow `hostname`, `port`, `addresses` to update. Emit notice via `stream_action`/`console`.
3. If new: behavior unchanged — mint `key_id = hostname` as today.
4. Add unit test: `tests/cli/clawctl/host/test_create_preserves_key_id.py`.

### Phase 3 — Env-file consistency invariant in `start_agent`

Goal: a `clawctl agent start` (and by extension `restart`) cannot leave the daemon running with a stale token.

1. `src/clawrium/core/lifecycle.py:start_agent` (hermes branch only — zeroclaw uses a different bearer path): before invoking the start playbook, run a tiny ansible probe (`slurp` or `command: cat`) against `/home/<agent_name>/.hermes/.env` to read the current `API_SERVER_KEY` value.
2. Compare with `secrets.json[<key_id>:hermes:<agent_name>].HERMES_API_SERVER_KEY.value`.
3. On mismatch: log a notice and invoke `configure_agent(...)` before continuing to start. On match: proceed.
4. On probe failure (host unreachable, file missing): log warning, proceed — start playbook will surface the real error.

### Phase 4 — Documentation

1. `docs/agent-support/hermes.md`: replace `<host>:hermes:<agent-name>` with `<key_id>:hermes:<agent-name>` and add one sentence: "`key_id` is the immutable host identifier set when the host was first registered via `clawctl host create`. It does not change when the host's `hostname` is updated."
2. `docs/host-preparation.md`: note in the "Register the host" section: "`clawctl host create` mints an immutable `key_id` on first run. Re-running it on an existing alias updates the hostname/IP without rotating the `key_id` — your secrets stay reachable."

### Phase 5 — Tests

Required coverage:

1. `tests/core/test_secrets_keying.py` (new): parametrized — for each callsite path in `install.py` / `lifecycle.py` / `chat.py`, verify the function reads from `secrets.json` keyed by `host["key_id"]`, not `host["hostname"]`.
2. `tests/core/test_install_hermes.py`: extend — install on a host whose `hostname` changes between two runs (`key_id` stable); assert single `HERMES_API_SERVER_KEY` entry under `<key_id>:hermes:<name>`, value reused on second install.
3. `tests/cli/clawctl/host/test_create_preserves_key_id.py` (new): re-running `clawctl host create` against an existing alias preserves `key_id` and only mutates `hostname` / `port` / `addresses`.
4. `tests/integration/test_secrets_survive_hostname_change.py` (new): end-to-end mocked — install agent with Discord+GitHub+provider secrets, mutate `hosts.json.hostname`, run `configure` + `chat`, assert all secrets resolve. Covers the full #448 repro (not just hermes bearer).
5. `tests/core/test_lifecycle_env_consistency.py` (new): hermes-specific — when on-host `.env`'s `API_SERVER_KEY` ≠ `secrets.json`'s `HERMES_API_SERVER_KEY`, `start_agent` invokes `configure_agent` before starting; when they match, it does not.

No migration tests (no migration code).

## ATX review

Use ATX CLI (`atx review --pr <pr-number>`) for review per the skill's fallback chain (MCP unavailable in this session). Persist session metadata to `.itx/448/atx-session.json` after every iteration. Iteration ceiling: 3.

## Acceptance criteria

- [ ] All `get_instance_key` callsites pass `host["key_id"]`; no callsite passes `host["hostname"]` directly.
- [ ] `clawctl host create` on an existing alias preserves `key_id`; CLI test asserts.
- [ ] `lifecycle.start_agent` hermes branch reconciles env-file ↔ secrets.json before start; unit test asserts on both match + mismatch paths.
- [ ] `make test` passes (Python + GUI).
- [ ] `make lint` passes.
- [ ] ATX review rating > 3/5 with no unresolved blockers, OR `[ITX-STUCK]` PR with documented Callouts after 3 iterations.
- [ ] Docs updated.
- [ ] PR body includes `## Callouts` section (per skill contract).
- [ ] PR title and body reference both #448 (Closes) and the maurice/wolf-i incident as context.

## Files expected to change

- `src/clawrium/core/secrets.py` — docstring + (no behavior change to `get_instance_key`)
- `src/clawrium/core/install.py` — callsite updates
- `src/clawrium/core/lifecycle.py` — callsite updates + env-file consistency invariant
- `src/clawrium/cli/chat.py` — callsite update
- `src/clawrium/cli/clawctl/host/create.py` — preserve `key_id` on re-record
- `docs/agent-support/hermes.md`
- `docs/host-preparation.md`
- `tests/core/test_secrets_keying.py` (new)
- `tests/core/test_install_hermes.py` (extend)
- `tests/cli/clawctl/host/test_create_preserves_key_id.py` (new)
- `tests/integration/test_secrets_survive_hostname_change.py` (new)
- `tests/core/test_lifecycle_env_consistency.py` (new)

## Notes for executor

- The plan was authored in a conversation between maintainer and Claude on 2026-05-28 after diagnosing a hermes 401 on agent `maurice` (host `wolf-i`, alias). Investigation traced to `secrets.json` containing two entries for the same agent (`wolf.tailf7742d.ts.net:hermes:maurice` ≠ `192.168.1.36:hermes:maurice`), with the daemon's `.env` rendered from the former and `clawctl agent chat` reading from the latter. The maintainer explicitly chose `key_id`-based stable keying (matching #448's proposal) over a uuid-based alternative.
- The maintainer explicitly excluded code-level migration — the affected agents on the maintainer's machine will be migrated by hand.
- No PR comment / interaction during execution. Surface decisions as PR Callouts per the skill's contract.

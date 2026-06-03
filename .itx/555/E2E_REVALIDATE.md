# E2E Re-Validation Report — #555 (post-#580/#579/#581 fixes + #582/#583 in-tree fixes)

**Date:** 2026-05-30
**Branch:** `e2e/555-revalidate-post-fix` (HEAD: this branch's tip after #582 + #583 in-tree fixes)
**Initial main HEAD at re-validation start:** `060efca` (post-#581 merge)
**Host:** wolf-i (192.168.1.36)
**Provider:** clawrium-glm51 (openrouter / z-ai/glm-5)
**Discord token:** DUMMY (plumbing-only verification — no live bot connection)

## Result matrix — FINAL (after #582 + #583 fixes)

| Agent | Type | Install | Provider | Channel | Chat | Destroy |
|-------|------|---------|----------|---------|------|---------|
| e2e-hermes   | hermes   | ✅ | ✅ | ✅ | ✅ `Hi there!` | ✅ |
| e2e-zeroclaw | zeroclaw | ✅ | ✅ (configure --stage providers works, no workaround) | ✅ | ✅ `Hi there!` | ✅ |
| e2e-openclaw | openclaw | ✅ | ✅ (configure --stage providers works, no workaround) | ✅ | ✅ `Hey there! 👋` | ✅ |

**Score: 15 / 15 pass, 0 partial, 0 fail.**

Legend: ✅ pass · ❌ fail · ⚠️ partial / required workaround.

## What landed in this branch on top of main `060efca`

### #582 fix — hermes `API_SERVER_KEY` hydration in canonical render

**Root cause:** `core/render.py:build_render_inputs` read `api_server.key` only from `hosts.json`, but `install.py:1141-1145` intentionally writes only the non-sensitive shape there (`enabled`/`host`/`port`) and keeps the bearer in `secrets.json` under `HERMES_API_SERVER_KEY`. The legacy `configure_agent` path hydrated it at `lifecycle.py:1695`; the new canonical-render path (introduced in #556/#559) never did. Every `agent sync` after the post-#318 schema change wrote `API_SERVER_KEY=''` into `~/.hermes/.env`, and hermes upstream correctly refused to bind a wildcard interface without a key.

**Fix:** `core/render.py:422-449` — `build_render_inputs` now hydrates the bearer from `secrets.json` when (a) `agent_type == "hermes"` and (b) the `hosts.json` blob lacks an inline key. Inline-key entries (pre-#318 legacy like `espresso`) keep working unchanged. Non-hermes agents never touch the secrets store.

### #583 fix — zeroclaw + openclaw `configure --stage providers`

Two distinct root causes both buried under the same opaque `"Configure playbook failed: failed"`:

1. **zeroclaw template filter:** the `toq` Jinja filter (added in `5ecb93b` for TOML-injection hardening) was registered only on the Python canonical renderer's Jinja env. The Ansible playbook renders the *same template file* (`zeroclaw-config.toml.j2`) via `ansible.builtin.template:` — that env has no `toq`. Template render failed → `no_log: true` hid the error.

2. **openclaw verify task:** the six `Verify .env credentials for <provider>` tasks used `ansible.builtin.lineinfile` with `check_mode: true` + `failed_when: <reg>.changed` to "verify presence" — broken semantics since April (commit `ca24b50`). lineinfile in check mode reports `changed=true` whenever the existing matched line differs from the placeholder `line:` value, which is every real run.

**Fixes:**
- Drop a filter plugin adjacent to the zeroclaw playbook (`filter_plugins/clawrium_filters.py`) and plumb `ANSIBLE_FILTER_PLUGINS` to ansible-runner so it's discovered.
- Better: collapse the dual-render entirely for zeroclaw's config.toml — `configure_agent` pre-renders via the canonical Python path and the playbook deploys with `copy: content: ...`. One render path now.
- Replace the broken openclaw verify tasks with proper `command: grep -qE '^KEY=.+'` probes.

### Observability — extracted `_summarize_ansible_configure_failure` pure helper

Three failure shapes now produce actionable errors instead of `"failed"`:
- Normal task failure → task name + msg/stderr.
- All-censored (`no_log: true`) → task name + `ANSIBLE_NO_LOG=False` hint. Bearer-leak invariant preserved verbatim.
- Pre-task failure (parse/inventory/connection) → recap stats + stdout/stderr tail (1KB).

## Test coverage added

- **8 tests** in `tests/core/test_render.py` for #582 hydration (inline-wins, fallback, malformed-secret rejection, non-hermes guard, end-to-end via `render_hermes` asserting `API_SERVER_KEY='<hex>'` appears in `.hermes/.env`).
- **14 tests** in `tests/core/test_configure_error_reporting.py` covering every branch of the new reporter + `toq` filter byte-parity with `_toml_escape`.
- **3 tests** in `tests/test_lifecycle.py` updated to the new richer error format — bearer-leak invariants verbatim.

Full suite: **3737 Python tests pass, 8 skipped, 0 failed. 231 frontend tests pass.**

## What holds post-fix (cumulative)

- **#575 / PR #580** (hermes Discord isolation) — *effectively* closed by the #582 fix. The api_server platform now binds correctly, so the gateway's "exit if all platforms failed" path no longer fires when Discord LoginFailure happens. The unhandled async LoginFailure still appears in the journal as noise (latent issue, non-blocking).
- **#576 / PR #579** (zeroclaw `gateway.host`) — confirmed. Rendered `config.toml` has `[gateway] host = "0.0.0.0"`.
- **#577 / PR #581** (openclaw identity-gate ledger consult) — confirmed. Breadcrumb emitted: `stage 'identity' already complete in onboarding ledger ... skipping manual-configure gate`.
- **#582** — fixed in-tree (this branch).
- **#583** — fixed in-tree (this branch).

## Detailed run log

### Hermes — `e2e-hermes`

1. **Install:** `clawctl agent create e2e-hermes --type hermes --host wolf-i` → ok=28, changed=11.
2. **Configure providers:** `--stage providers --provider clawrium-glm51` succeeded. `agent doctor` shows `Resolved provider: clawrium-glm51 (openrouter) api_key=present`.
3. **Channel:** registry record created, attached, synced. On-host `~/.hermes/.env` now has `API_SERVER_KEY='45a88e62…'` (64-char hex) **plus** the three `DISCORD_*` env vars. **#582 fix verified directly in the rendered file.**
4. **Chat:** ✅ `e2e-hermes> Hi there!`. Real glm-5 inference. `NRestarts=0`, `ActiveState=active`, port 8679 bound.
5. **Destroy:** clean.

### Zeroclaw — `e2e-zeroclaw`

1. **Install:** ok=16, changed=9.
2. **Configure providers:** **`--stage providers` works end-to-end** — no `sync` workaround. The canonical Python render path produces `config.toml`, the playbook deploys it via `copy:`, the daemon binds, the pair handshake completes, the gateway emits a fresh bearer. **#583 fix verified.**
3. **Channel + sync:** on-host `[channels.discord]` block populated; `[gateway] host = "0.0.0.0"` (#576).
4. **Chat:** ✅ `e2e-zeroclaw> Hi there!`. Real glm-5 inference on `0.0.0.0:41040`.
5. **Destroy:** clean.

### Openclaw — `e2e-openclaw`

1. **Install:** ok=32, changed=16.
2. **Configure providers (first attempt):** Hit the documented #523 identity gate (expected on fresh install — `onboarding.identity = pending`).
3. **Configure identity:** `--stage identity` succeeded.
4. **Configure providers (second attempt):** Emitted `stage 'identity' already complete in onboarding ledger ... skipping manual-configure gate` (#577 ledger fix), then ran the playbook **successfully** — the verify probes now actually verify presence instead of false-failing. **#583 openclaw fix verified.**
5. **Channel + sync:** on-host `~/.openclaw/env` has `DISCORD_BOT_TOKEN`, `~/.openclaw/openclaw.json` has `channels.discord` with `allowFrom = ["740723459344302120"]`.
6. **Chat:** ✅ `e2e-openclaw> Hey there! 👋`. Real glm-5 inference on `0.0.0.0:41554`.
7. **Destroy:** clean.

## Cleanup confirmed

- `clawctl agent get` shows zero `e2e-*` entries.
- All 3 channel registry records deleted.
- On-host `/home/e2e-*/.<type>/` directories all removed.
- On-host systemd units all `could not be found`.

## Outcome

The end-to-end pipeline is **fully green across all three agent types** for the first time on this branch — no workarounds, no partial cells, no swallowed errors. The two render paths (canonical Python + Ansible) now agree by construction for zeroclaw config.toml (one path), and the configure reporter actually tells the operator what failed.

# Issue #817 — Real-host UAT (wolf-i, x86_64)

**Result: BLOCKED at Step 4 (chat).** Do NOT push the manifest bump
in isolation — 0.8.2 introduces a breaking change to the `/ws/chat`
handshake that the clawrium chat client does not yet satisfy.
Upgrading a working 0.7.5 instance to 0.8.2 today would render
`clawctl agent chat <name>` non-functional.

Steps 6 (upgrade regression) was NOT run — halted per operator
instruction "if any step fails, do NOT push and stop." Step 7
(cleanup) WAS run so wolf-i is left clean.

## Environment

- Worktree: `~/workspace/ric03uec/clawrium-issue-817`
  (`issue-817-zeroclaw-0-8-2`, HEAD = `c285658`).
- CLI: `uv run clawctl` (loads the modified 0.8.2 manifest).
- Target host: `wolf-i` (`wolf.tailf7742d.ts.net`, Debian x86_64,
  user `xclm`, Tailscale-reachable).

## Step-by-step

### Step 1 — `clawctl agent create test-817 --type zeroclaw --host wolf-i --yes` ✅

Install picked 0.8.2 from the modified manifest:

```
TASK [Download zeroclaw binary]
url: https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.8.2/zeroclaw-x86_64-unknown-linux-gnu.tar.gz
size: 26667537 bytes
TASK [Display install success]
msg: ZeroClaw 0.8.2 installed for agent 'test-817'.
```

The sha256 checksum from the manifest matched the downloaded
tarball (Ansible `get_url` verifies before `unarchive`) — the
`6b9f7e9d9877a56b86d9d8597066b92173ff16252c961a7145e93e9a0d9adfd9`
digest we sourced from the release SHA256SUMS is correct for
x86_64.

Note: the CLI's `agent create` has no `--version` flag — version
selection is driven by `latest_supported_version(manifest,
hardware)`. Our test therefore relies on 0.8.2 being the manifest
max, which the change under test guarantees.

### Step 2 — `clawctl agent configure test-817 --stage providers --provider clawrium-glm51` + `--stage validate` ✅

Provider `clawrium-glm51` (openrouter, `z-ai/glm-5`) attached and
rendered into the on-host config.toml. The two configure calls both
succeed; the flow now requires a prior `clawctl agent provider
attach` before `configure --stage providers` will run.

The CLI's `agent configure` no longer accepts `--yes` (removed);
the `--stage` argument is required. Not a 0.8.2 regression — this
is the clawrium CLI shape as of this branch.

### Step 3 — `clawctl agent start test-817` ✅

Daemon started, pairing loop completed, `gateway_token_rotated`
event fired once (as required by the #437 invariant). Token prefix
observed: `zc_e9c0c…`.

### Step 5 (partial — pre-chat) ✅

- `clawctl agent get`: `test-817 … ready`.
- `clawctl agent doctor test-817`: `Status: ok` — provider resolved,
  config.toml + zeroclaw-env.conf rendered.
- On-host `zeroclaw --version` (via `clawctl agent shell`):
  `zeroclaw 0.8.2` — binary matches manifest.
- `ss -ltnp` on the host: gateway LISTEN on `0.0.0.0:41529`
  (wildcard bind — matches `features.web_ui.bind: wildcard`).
- `curl 127.0.0.1:41529/health`: `paired=true`, control-plane +
  channels + daemon all `status:"ok"`.

### Step 4 — `clawctl agent chat test-817 --once "hello"` ❌ BLOCKING

The `--once` flag itself is a pre-existing CLI stub —
`clawctl agent chat test-817 --once "…"` returns
`Not implemented: agent chat --once`. That is orthogonal to 0.8.2.

I fell back to invoking the underlying `ZeroClawChatBackend`
directly against the daemon's `/ws/chat` endpoint using the exact
gateway URL + bearer that `hosts.json` persisted:

```
ws://wolf.tailf7742d.ts.net:41529/ws/chat
Authorization: Bearer zc_e9c0c…
```

The daemon returns `HTTP 400` on the WebSocket upgrade:

```
< HTTP/1.1 400 Bad Request
Missing required `agent` query parameter — pass `?agent=<alias>`
matching a configured [agents.<alias>] entry.
```

**This is a 0.8.2 breaking change** in the ZeroClaw gateway. Two
things changed vs. 0.7.5:

1. `/ws/chat` now requires a `?agent=<alias>` query parameter.
2. That `<alias>` must resolve to an `[agents.<alias>]` sub-table
   in the on-host `config.toml`.

The on-host `config.toml` rendered by the current canonical
pipeline emits an empty `[agents]` table only — no `[agents.<alias>]`
sub-table exists, so even if the client passed a query param the
handshake would still fail against an unmatched alias.

`clawrium.core.chat_zeroclaw._ZeroClawChatBackend.connect` opens
`self.gateway_url` unchanged, so no client-side workaround is
available today.

### Steps 6, 7 — upgrade regression + cleanup

- Step 6 (upgrade `clawrium-d01` from 0.7.5 to 0.8.2, verify
  provider+channel survive) was **NOT** run. Halted per
  "if any step fails, do NOT push and stop."
- Step 7 (cleanup) **was** run — `clawctl agent delete test-817`
  succeeded. Wolf-i has no lingering test-817 state.

Pre-upgrade snapshot of `clawrium-d01` was captured at
`/tmp/pre_upgrade_clawrium-d01.txt` so a future run can compare;
the actual upgrade was NOT triggered.

## Disposition

The manifest-only change on this branch is **necessary but not
sufficient** to ship 0.8.2 safely.

Minimum additional work required before this PR merges:

1. **Canonical config.toml renderer** (`src/clawrium/core/render.py`
   → `_render_zeroclaw_config_toml` — verify the correct name) must
   emit at least one `[agents.<alias>]` sub-table. The natural
   alias is the agent instance name (i.e. what `<agent_name>` maps
   to in the playbook inventory).
2. **`clawrium.core.chat_zeroclaw.ZeroClawChatBackend`** must
   append `?agent=<alias>` to `gateway_url` before calling
   `websockets.connect(...)`. The alias comes from the same source
   the renderer used.
3. **Migration for existing 0.7.5 hosts** — a `clawctl agent sync`
   after this PR must re-render the config.toml with the new
   `[agents.<alias>]` sub-table so their upgraded 0.8.2 daemon can
   accept chat frames. Document under `[Unreleased] ### Changed`
   as an operator-visible change (or `### BREAKING` if we choose
   not to auto-migrate).
4. Once those three are in place, re-run this UAT script AND
   Step 6 (upgrade regression on `clawrium-d01`).

Alternative path: split the work — land the manifest-only bump
here, gated on the renderer + chat client fixes in a separate PR
that must merge first (or same-PR). The manifest bump alone is
correct in isolation (new binary hash, new URL, new min version)
but is dangerous to ship without the two client-side changes.

## Recommendation

Do NOT push branch `issue-817-zeroclaw-0-8-2` as-is. Either:

- (a) Add the renderer + chat-client changes to this branch and
      re-run UAT; or
- (b) Open a follow-up issue for the chat regression and keep this
      branch parked until that lands.

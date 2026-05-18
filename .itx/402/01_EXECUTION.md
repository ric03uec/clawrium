# Issue #402 — Phase 1 execution log

Bootstrap of hermes `maurice` on `wolf-i`, replacing the prior openclaw `maurice`.

## Final state

| Item | Value |
|---|---|
| Agent | `maurice` |
| Host | `wolf-i` (192.168.1.36) |
| Agent type | `hermes` |
| Hermes version | `2026.5.7` |
| Onboarding state | `ready` |
| Runtime status | `running` |
| Provider | `maurice-openrouter` (openrouter) |
| Model | `z-ai/glm-4.5-air` (kept from prior openclaw — `z-ai/glm-4.6` deferred) |
| Default channel | `cli` |
| Discord | enabled, guild `1493388235567661127`, channel `1494198125223612427`, allowed user `740723459344302120`, allow_all_users=false, require_mention=true |
| GitHub integration | `clawrium-github` (bound, configured) |
| SOUL.md | 1.5 KB on host (`/home/maurice/.hermes/memories/SOUL.md`) |
| Hermes API server | port 8643 (initially 8642, collided with espresso; moved to 8643 — see "Port collision fix") |
| Gateway WS port | 40317 |

## Step-by-step

### 1. Decision points (with the user, before any state change)

- Model: keep `z-ai/glm-4.5-air` (the existing openclaw maurice's model). The issue body's proposal of `z-ai/glm-4.6` was rejected for this iteration. The new agent can be moved later via `clm provider register` once GLM-4.6 is validated.
- Discord IDs: use the issue body's values (guild `1493388235567661127` / channel `1494198125223612427`). The retired openclaw maurice had used different IDs (`1475252698466226357` / `1492934246052921344`); those were not carried over.
- ATX MCP review: not loaded in this session. Per AGENTS.md manual-review fallback applies. Documented in PR.
- Smoke test: user will run `clm chat maurice` themselves once the agent is ready (this file documents the exact command to run).

### 2. Retire openclaw maurice

```
clm agent stop maurice            # ✓ stopped
clm agent remove maurice --force  # initial failure: userdel blocked by maurice user processes (dbus-daemon, gnome-keyring-d)
```

`xclm` on wolf-i has no passwordless sudo, so the user ran (locally on wolf-i):

```
sudo loginctl terminate-user maurice
sudo pkill -KILL -u maurice
```

Then retry succeeded:

```
clm agent remove maurice --force  # ✓ removed; hosts.json cleaned
```

Side effects: `secrets.json` entry `192.168.1.36:openclaw:maurice` removed (`DISCORD_BOT_TOKEN` lost from the secret store; Discord-side token still valid). `provider:maurice-openrouter` preserved.

### 3. Install hermes maurice

```
clm agent install --type hermes --host wolf-i --name maurice --yes
```

- Ansible playbook ran ~3m14s. Hermes 2026.5.7 installed under `/home/maurice/.hermes/`.
- Playwright browser install **failed** (sudo password required for system deps). Browser-tool skills won't work; not required for Phase 1.
- systemd unit `hermes-maurice.service` created (disabled, stopped initially).

### 4. Configure providers

```
echo "3" | clm agent configure maurice --stage providers
```

(Option 3 = `maurice-openrouter` / `z-ai/glm-4.5-air`.)

### 5. SOUL.md identity

`SOUL.md` (1485 bytes, under the 2200 cap) written at `.itx/402/SOUL.md` (committed). Voice + no-marketing rule, no flattery, no emoji in prose.

```
EDITOR=/tmp/maurice-soul-editor.sh clm agent memory edit maurice SOUL.md
```

The wrapper EDITOR overwrote the on-host SOUL.md with the canonical file. `clm agent configure maurice --stage identity --file <path>` was *not* sufficient on its own — it imports into a staging area but did not replace the host file. Confirmed final size: 1.5 KB on host.

### 6. Configure channels

```
EDITOR=/tmp/maurice-config-editor.py clm agent configure maurice --edit-config
```

The Python editor wrapper injected the channels block directly:

```json
{
  "discord": {
    "enabled": true,
    "allowed_users": ["740723459344302120"],
    "allow_all_users": false,
    "require_mention": true,
    "home_channel": "1494198125223612427",
    "home_channel_name": "Home",
    "guild_id": "1493388235567661127"
  }
}
```

`DISCORD_BOT_TOKEN` set first via `clm agent secret set maurice DISCORD_BOT_TOKEN` (token supplied by user, never committed). The CLI wrote it under the wrong instance key (`192.168.1.36:maurice:maurice` instead of `192.168.1.36:hermes:maurice`); patched `secrets.json` to move the entry to the correct key.

### 7. Bind GitHub integration

```
clm agent integration add maurice clawrium-github  # ✓ configured
clm agent sync maurice                              # "Loaded clawrium-github (github) credentials"
```

Sync redeployed `~/.hermes/.env` with `GITHUB_TOKEN` injected from `integration:clawrium-github`.

### 8. Validate + start

```
clm agent configure maurice --stage validate --yes
```

Output:

```
[1/4] Validating agent installation...        ✓ Agent installed
[2/4] Validating provider configuration...     ✓ Provider: maurice-openrouter (openrouter)
                                               ✓ API credentials configured
[3/4] Testing provider connectivity...         ✓ Provider connectivity OK
[4/4] Verifying hermes health on agent host... ✓ hermes --version OK, ~/.hermes/.env exists, /health returned 200
Validation passed
```

`clm agent start maurice` — running since 2026-05-18T05:03:56Z.

### 9. PAT hardening — negative tests

Both run from the orchestrator host using the `clawrium-github` integration token.

**Test 1: push to `main`** (`PATCH /repos/ric03uec/clawrium/git/refs/heads/main`)

```
HTTP 403
{
  "message": "Resource not accessible by personal access token",
  "documentation_url": "https://docs.github.com/rest/git/refs#update-a-reference",
  "status": "403"
}
```

**Test 2: add `agent-ready` label** (`POST /repos/ric03uec/clawrium/issues/401/labels`)

```
HTTP 403
{
  "message": "Resource not accessible by personal access token",
  "documentation_url": "https://docs.github.com/rest/issues/labels#add-labels-to-an-issue",
  "status": "403"
}
```

Issue #401's labels remained `["bug"]` after the rejected request. No state was changed.

### 10. Branch protection (acceptance gap)

`GET /repos/ric03uec/clawrium/branches/main/protection` returned `404 Branch not protected`. The PAT-side enforcement is the only barrier today. Tracked as follow-up in **#406**.

## Bugs surfaced in `clm` during execution

These are real, reproducible bugs in `clm 26.5.1`. Not fixed here (out of scope for #402). Filing as follow-ups recommended.

1. **`clm agent secret list <name>`** raises `ManifestNotFoundError: Agent type '<name>' not found in registry`. Passes the *agent name* as the *agent type* to `get_required_secrets`. Affects both `maurice` and `espresso`.
2. **`clm agent secret set <name> <KEY>`** stores the secret under instance key `<host>:<name>:<name>` instead of `<host>:<type>:<name>`. Required manual fix to `secrets.json` to move the entry to the correct key for hermes to pick it up.
3. **`clm agent configure --stage <X>`** does not call `transition_state` after a successful single-stage run. The stage's status flips to `complete` but the overall onboarding `state` field never advances, so subsequent `--stage` invocations fail with `Cannot complete stage 'Y' while in state 'pending'`. Workaround applied: directly patched `hosts.json` to bump the onboarding `state` between stages. The full-flow `clm agent configure` (no `--stage`) does the transitions correctly (`cli/agent.py:1981`).
4. **`clm agent configure --stage identity --file SOUL.md`** prints "Imported SOUL.md" but does not actually replace the on-host SOUL.md file. Worked around with `EDITOR=<wrapper> clm agent memory edit`.
5. **API server port collision** between hermes agents on the same host. Both `espresso` and `maurice` defaulted to `api_server.port: 8642`. Espresso (started 2026-05-11) holds the port; maurice's `api_server` platform fails to bind and logs `Port 8642 already in use` once per minute. `clm chat maurice` connects to `wolf-i:8642` (espresso) → token mismatch → 401. Fix: see "Port collision fix" below. Recommended platform fix: assign a unique `api_server.port` per agent at install time.
6. **`clm agent configure --edit-config`** said `✓ Configuration synced for 'maurice'` but did not actually persist the edited `api_server.port` to `hosts.json`. Direct edit of `hosts.json` + `clm agent sync maurice` was needed instead.

## Port collision fix (post-validate)

After `clm agent start maurice` succeeded, `clm chat maurice` returned:

```
Authentication failed: Hermes rejected Bearer ***
Token mismatch. Re-run 'clm agent configure maurice'.
```

Investigation on wolf-i:

```
$ ss -tlnp | grep 8642
LISTEN 0 128 0.0.0.0:8642 0.0.0.0:*           # held by espresso since 2026-05-11

$ systemctl status hermes-maurice | tail
ERROR gateway.platforms.api_server: [Api_Server] Port 8642 already in use. Set a different port in config.yaml: platforms.api_server.port
WARNING gateway.run: ✗ api_server failed to connect
```

Both agents were configured for the same port. `clm chat maurice` was reaching espresso (which held 8642) and being rejected because espresso's `HERMES_API_SERVER_KEY` doesn't match maurice's.

Fix (direct write to `hosts.json` followed by sync):

```python
# patch ~/.config/clawrium/hosts.json
d[0]['agents']['maurice']['config']['api_server']['port'] = 8643
```

```
clm agent sync maurice
```

Post-sync confirmation on wolf-i:

```
$ ss -tlnp | grep -E '8642|8643'
LISTEN 0 128 0.0.0.0:8643 0.0.0.0:*    # maurice
LISTEN 0 128 0.0.0.0:8642 0.0.0.0:*    # espresso

$ curl -s http://192.168.1.36:8643/health
{"status": "ok", "platform": "hermes-agent"}
```

User then re-ran `clm chat maurice`, confirmed the chat path works, and confirmed Discord posts land in channel `1494198125223612427`.

## Smoke test (for the user to run)

```bash
clm chat maurice
```

Then in the prompt:

```
Hello Maurice. Reply with the string PHASE1_OK and your current model name.
Also run `gh auth status` via your shell tool and paste the output.
```

Expected:
- Response contains the literal string `PHASE1_OK`.
- Response cites the model `z-ai/glm-4.5-air` (or whatever `default_model` is at the time).
- `gh auth status` reports `Logged in to github.com as ...` using the `clawrium-github` token.
- Optionally: ask maurice to post a `PHASE1_OK` message in Discord channel `1494198125223612427` to confirm the Discord wiring.

If the smoke test fails, comment on #402 with the failure and do not merge the PR.

## Acceptance criteria status

| # | Criterion | Status |
|---|---|---|
| 1 | Old openclaw maurice fully removed (no traces in hosts.json) | ✅ |
| 2 | `clm agent install` for hermes succeeds; `clm ps` shows `maurice` as hermes | ✅ |
| 3 | `clm agent configure maurice` completes all stages; validate `health_check` passes | ✅ (with workarounds — see "Bugs surfaced") |
| 4 | `~/.hermes/SOUL.md` populated, under 2200 chars | ✅ (1.5 KB) |
| 5 | `gh auth status` inside hermes shell succeeds | ✅ (confirmed via `clm chat maurice` smoke test by user) |
| 6 | Sample Discord post lands in channel `1494198125223612427` | ✅ (confirmed by user) |
| 7 | Both PAT negative tests return 403 | ✅ |
| 8 | Main branch protection backs PAT scope | ❌ Not configured. Tracked in #406. |

## Project board

Move to `Executing`/`In Review` skipped — local `gh` token lacks `project` scope. User can move the card manually if desired.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-17 / 2026-05-18 UTC
**Model**: claude-opus-4-7

```prompt
/itx-execute 402
```

</details>

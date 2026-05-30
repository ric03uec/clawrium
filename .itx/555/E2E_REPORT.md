# E2E Lifecycle Test Report — #555 canonical render

Sequential five-step lifecycle (install → configure provider → configure channel → chat → destroy) executed against all three bundled agent types on host `wolf-i` (192.168.1.36), provider `clawrium-glm51` (openrouter / z-ai/glm-5), DUMMY Discord channel tokens (bot is not expected to connect).

Branch: `e2e/555-lifecycle-three-agents` off `origin/main`. Run date: 2026-05-30.

## Test matrix

| Agent | Type | Install | Provider | Channel | Chat | Destroy |
|-------|------|---------|----------|---------|------|---------|
| e2e-hermes   | hermes   | ✅ | ✅ | ✅ | ❌ (#575) | ✅ |
| e2e-zeroclaw | zeroclaw | ✅ | ❌ (#576) | ✅ (file rendered correctly) | ❌ (cascade from #576) | ✅ |
| e2e-openclaw | openclaw | ✅ | ⚠️ (#577 — `--stage providers` blocked, `sync` worked) | ✅ | ✅ (real glm-5 reply) | ✅ |

Legend: ✅ pass · ❌ fail · ⚠️ partial / required workaround.

## Sub-issues filed

- **#575** — [E2E] hermes chat: Discord LoginFailure on dummy token crashes entire gateway, blocks `/v1` chat
- **#576** — [E2E] zeroclaw configure: `gateway.host` rendered as empty string, daemon refuses to start
- **#577** — [E2E] openclaw configure `--stage providers`: stale identity gate blocks despite `onboarding.identity = complete`

All three are linked as sub-issues under #555 via the GitHub sub-issues API and labelled `type:bug,agent-ready`.

## Detailed observations

### hermes (e2e-hermes)

- `clawctl agent create … --type hermes` succeeds end-to-end. AGENTS.md note that the unit ships **disabled** until configure runs is current behavior (`systemctl is-enabled hermes-e2e-hermes.service` → `disabled` immediately after install; flips to `enabled` after the first sync).
- `configure --stage providers --provider clawrium-glm51` works; `agent doctor` reports `Resolved provider: clawrium-glm51 (openrouter) api_key=present`.
- Channel plumbing is correct: on-host `~/.hermes/.env` has `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS=740723459344302120`, `DISCORD_REQUIRE_MENTION=true`.
- **Chat fails** because the dummy Discord token throws `discord.errors.LoginFailure: Improper token has been passed.`, which is **not isolated from the FastAPI gateway** — the entire process exits 1 and systemd restart-loops it, so the chat port (8679) never binds. `clawctl agent chat` shows `Connection failed: Failed to reach hermes at http://192.168.1.36:8679/v1`. Filed as **#575**.
- Destroy is clean: registry record gone, systemd unit `not-found`, `/home/e2e-hermes/.hermes` removed.

### zeroclaw (e2e-zeroclaw)

- Install succeeds; unit is dropped **disabled** (per AGENTS.md, by design).
- `configure --stage providers` returns `Configure playbook failed: failed`. On-host journal: `Error: [required_field_empty] gateway.host must not be empty (gateway.host)`. The rendered `~/.zeroclaw/config.toml` contains `host = ""` under `[gateway]`. Filed as **#576**.
- Channel plumbing **is** rendered correctly: `[channels.discord]` block has `bot_token`, `allowed_users`, `mention_only = true`. So the channel rendering pipeline is fine — only the daemon start is blocked by #576.
- Chat unreachable as a cascade: `clawctl agent chat e2e-zeroclaw` → `Gateway URL is missing. Re-run install/configure to capture gateway URL.`
- Destroy clean: registry record gone, unit `could not be found`, `/home/e2e-zeroclaw/.zeroclaw` removed.

### openclaw (e2e-openclaw)

- Install succeeds; openclaw is the only one of the three whose unit ships **enabled** out of the gate.
- `configure --stage providers --provider clawrium-glm51` fails: `agent 'e2e-openclaw' requires manual identity configuration ... tracked in #523`. Even after `configure --stage identity` runs successfully and `describe` shows `onboarding.identity complete`, the providers stage gate still refuses. `clawctl agent sync` works around the gate and writes the canonical config (`Resolved provider: clawrium-glm51 (openrouter) api_key=present`). Filed as **#577**.
- Channel plumbing on-host:
  - `~/.openclaw/env` → `DISCORD_BOT_TOKEN=…`
  - `~/.openclaw/openclaw.json` → `channels.discord` = `{ enabled: true, allowFrom: ["740723459344302120"], guilds: {} }`
- **Chat passes**: `clawctl agent chat e2e-openclaw` → `e2e-openclaw> Hey there! Nice to meet you.` after waiting ~30s for `0.0.0.0:41554` to bind. Real inference against `openrouter/z-ai/glm-5` confirmed.
- Destroy clean: registry record gone, unit `could not be found`, `/home/e2e-openclaw/.openclaw` removed.

## Cleanup confirmed

- All 3 test agents deleted (`clawctl agent get` shows no `e2e-*` entries).
- All 3 channel registry records deleted (`discord-e2e-hermes`, `discord-e2e-zeroclaw`, `discord-e2e-openclaw`).
- On-host `/home/e2e-*/.<type>/` directories all `No such file or directory`.
- On-host systemd units all `could not be found`.
- Worktree ready for removal.

## Callouts

1. **#576 is a hard blocker on zeroclaw onboarding from clean state.** Empty `gateway.host` should default to `0.0.0.0` per the documented `features.web_ui.bind: wildcard` in AGENTS.md. Until fixed, every new zeroclaw install needs a manual `config.toml` edit.
2. **#575 turns the Discord channel feature into a chat-killer on hermes.** The Discord client failure should be isolated from the FastAPI gateway (degraded platform, not process crash). Any stale token (rotated, revoked, fat-fingered) currently takes down chat — and `clawctl agent chat` surfaces only the symptom (`Failed to reach hermes`), not the cause.
3. **#577 is the surface bug behind #555's core thesis.** The provider stage gate consults different state than the onboarding ledger does — same pattern as the conditional-emit bug #555 documents. Fixing this with `build_render_inputs` (F1 in #555) would dissolve the gate entirely.
4. **Positive signal**: the canonical render pipeline (the F2/F3 layer of #555) **does write correct files** for all three agent types — channels, providers, env vars all match expectations on every agent. The remaining defects are at the boundaries: daemon startup contract (zeroclaw), platform isolation (hermes), and stage-gate state (openclaw). The render itself is sound.
5. **Operational note**: openclaw takes ~30s to bind its gateway port after `systemctl start`. Clients (including `clawctl agent chat`) need to either poll or implement a startup grace, otherwise a fresh sync → immediate chat will fail with `Connect call failed`.

## Final state

End-to-end is **partially passing**: 1 of 3 agent types (openclaw) clears all five lifecycle steps with real inference confirmed; the other two are blocked by isolable bugs filed as **#575**, **#576**, **#577**. No test-environment failures (wolf-i was reachable throughout, secrets resolved cleanly, OpenRouter inference returned a real model completion when the gateway was actually serving). The canonical render in #555 is correctly populating files across all three agent types — the failure modes here are downstream of render: daemon startup contracts and process supervision, not the configuration plumbing #555 itself fixed.

# Issue #817 — Re-UAT on wolf-i after renderer + chat client patch

## Result

**Steps 1–5: green.** The renderer + chat-client patch on this branch
brings `clawctl agent chat` back to a working end-to-end state
against a fresh zeroclaw 0.8.2 install on wolf-i.

**Step 6 (upgrade regression on a 0.7.5→0.8.2 upgrade): FAILED.**
Attachments (provider + channel + integration) were STRIPPED from
the agent record. Per operator instruction ("if Step 6 still fails
on upgrade, treat THAT as a separate blocker and do NOT ship") this
branch is NOT pushed.

wolf-i left clean: `test-817` and `test-817-legacy` both deleted.
`clawrium-d01` (a phantom-metadata entry unrelated to this work) is
untouched — see the Housekeeping section below.

## Steps 1–5: transcript excerpts (all green)

### Step 1 — `clawctl agent create test-817 --type zeroclaw --host wolf-i --yes`

Install picks 0.8.2 from the modified manifest and downloads the
correct URL with a matching sha256:

```
TASK [Download zeroclaw binary]
url: https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.8.2/zeroclaw-x86_64-unknown-linux-gnu.tar.gz
size: 26667537 bytes
TASK [Display install success]
msg: ZeroClaw 0.8.2 installed for agent 'test-817'.
```

### Step 2 — `configure --stage providers --provider clawrium-glm51` + `--stage validate`

Provider `clawrium-glm51` (openrouter, `z-ai/glm-5`) attached and
rendered. Both configure calls succeed. The rendered
`~/.zeroclaw/config.toml` now includes the three sub-tables added by
this branch:

```toml
[providers.models.openrouter.test-817]
model = "z-ai/glm-5"
api_key = "sk-or-…"

[agents.test-817]
model_provider = "openrouter.test-817"
risk_profile = "default"
runtime_profile = "default"

[risk_profiles.default]

[runtime_profiles.default]
```

### Step 3 — `clawctl agent start test-817`

Daemon up, `gateway_token_rotated` event fired with
`reason="start"`. Bearer prefix: `zc_d351e…`.

### Step 4 — chat with a single message ✅

`clawctl agent chat --once` is still a pre-existing CLI stub
(`Not implemented`). I fell back to invoking `ZeroClawChatBackend`
directly using the exact code path `_build_zeroclaw_backend` would
use — same URL, same token, same `agent_alias=<name>`:

```
$ uv run python <one-shot script>
EFFECTIVE_URL: ws://wolf.tailf7742d.ts.net:41529/ws/chat?agent=test-817
CONNECTED
REPLY: 'hello'
```

The daemon accepted the WebSocket upgrade, resolved the alias against
`[agents.test-817]`, resolved the model_provider dotted ref to
`[providers.models.openrouter.test-817]`, and returned a real
model-generated reply. This is the same code path
`clawctl agent chat <name>` will take in interactive mode once the
`--once` CLI stub is replaced.

### Step 5 — `agent get` READY, `agent doctor` green ✅

```
NAME       TYPE      HOST     PROVIDER          STATUS  AGE
test-817   zeroclaw  wolf-i   clawrium-glm51    ready   10m

$ clawctl agent doctor test-817
Status: ok
Resolved provider:
  name:           clawrium-glm51
  type:           openrouter
  default_model:  z-ai/glm-5
  api_key:        present
Rendered files (2):
  .zeroclaw/config.toml         bytes=17443
  .zeroclaw/zeroclaw-env.conf   bytes=94
```

On-host `ss -ltnp` shows gateway LISTEN on `0.0.0.0:41529`;
`zeroclaw --version` = `0.8.2`.

## Step 6 — upgrade regression: FAILED

Original target was `clawrium-d01` (the only zeroclaw agent already
on the fleet at 0.7.5). That entry is a phantom — the systemd unit,
`/home/clawrium-d01/`, and binary are all absent on wolf-i even
though local hosts.json still records the agent. `clawctl agent
sync` refuses to touch it and `clawctl agent delete` cannot complete
because an orphaned `dbus-daemon --session` still holds the `clawrium-d01`
Linux user open. Doctor and get both report `ready` because they
read local metadata without touching the host — a separate
housekeeping issue that pre-dates #817.

To run a real 0.7.5 → 0.8.2 upgrade I installed a fresh 0.7.5
zeroclaw (`test-817-legacy`) via `run_installation(..., version_override='0.7.5')`
with the manifest monkey-patched to expose only 0.7.5 platform
entries during the install call. That yielded a genuine 0.7.5 agent
on wolf-i with a valid systemd unit.

Then, on the LEGACY 0.7.5 agent, I:

1. Attached `clawrium-glm51` (provider), `discord-clawrium-d01`
   (channel), and `clawrium-d01-github` (integration) — all
   metadata-only mutations on hosts.json.
2. Ran `clawctl agent sync test-817-legacy --no-restart` to
   materialize the (0.8.2-shape) config on the host — the drift
   check on upgrade refuses to proceed without this.
3. Ran `clawctl agent upgrade test-817-legacy --yes`.

Pre-upgrade `describe`:

```
Name:       test-817-legacy
Version:    0.7.5
Provider:   clawrium-glm51
Integrations (1):
  clawrium-d01-github  (configured)
Channels (1):
  discord-clawrium-d01
```

Post-upgrade `describe`:

```
Name:       test-817-legacy
Version:    0.8.2               ← binary upgrade succeeded
Provider:   -                   ← STRIPPED
Integrations (0):               ← STRIPPED
Channels: none                  ← STRIPPED
Onboarding:
  providers  pending            ← reset
  identity   pending
  channels   pending
  validate   pending
```

The 0.8.2 binary landed correctly and the version in hosts.json
advanced, but every attachment and every onboarding stage was
wiped. This is the same defect the sibling openclaw work (#816)
uncovered and root-caused in commit `48fa82f` on branch
`issue-816-openclaw-2026-6-11`
(`fix(install): #816 preserve provider/channel/integration/skill on
reinstall`). That commit is NOT on main and NOT on this branch —
this branch was cut from main before #839 opened.

Root cause (per that commit message and my read of
`src/clawrium/core/install.py:set_installing()`): the function
overwrites the entire `hosts.json.agents[<name>]` dict with a fresh
one before reinstall, capturing only `onboarding`, `config.gateway`,
and per-instance listener ports. `providers`, `channels`,
`integrations`, `skills` are top-level lists on the agent record —
they get wiped on every `run_installation(force=True)`, which is
exactly the path `clawctl agent upgrade` takes.

## Disposition

Per operator instruction:

> "If Step 6 still fails on upgrade, treat THAT as a separate
> blocker and do NOT ship."

**This branch is not being pushed and no PR is being opened.** The
manifest + renderer + chat client + tests are all correct and would
ship a working `clawctl agent create --type zeroclaw` + `configure`
+ `start` + `chat` flow on 0.8.2. But shipping this without the
`install.py` fix means every existing 0.7.5 operator who runs
`clawctl agent upgrade` will silently lose their provider, channel,
and integration attachments — a real regression that would
compound the "openclaw upgrade strips attachments" incident on
wolf-i 2026-06-18.

Two paths forward:

1. **Land PR #839 (`fix(install): #816 preserve …`) first**, then
   push this branch and open the #817 PR. Confirm Step 6 passes
   against the merged fix before merging #817.
2. **Cherry-pick `48fa82f` onto this branch** and ship a single PR
   that covers both the version bump and the attachment-preservation
   fix. Downside: the PR now spans #816 + #817 fix scopes, which
   makes review noisier.

Recommendation: path 1 — keeps the fix reviewable in the PR where
it was root-caused, and lets #817 stay a scoped "0.7.5 → 0.8.2
compatibility" change.

## Housekeeping

- `test-817` and `test-817-legacy` were both `clawctl agent delete
  --yes`'d; wolf-i is clean of any #817 test artifacts.
- `clawrium-d01` (phantom) was NOT touched. `delete` fails on it
  because `userdel: user clawrium-d01 is currently used by process
  239583 (dbus-daemon --session)` — an orphaned user-session
  daemon from before the systemd unit was removed. That's a
  separate cleanup problem, unrelated to #817.
- The 0.7.5 → 0.8.2 test artifact on the host
  (`/home/test-817-legacy/`) is removed as part of `agent delete`.

## Prompt Log

## Re-UAT

**Stage**: re-uat
**Skill**: /itx-execute
**Timestamp**: 2026-07-02T05:15:00Z
**Model**: claude-opus-4-7[1m]

```prompt
extend this branch with the renderer + chat client fix (both files you
identified in .itx/817/02_UAT_WOLF_I.md — core/render.py for the zeroclaw
config alias field, and core/chat_zeroclaw.py::ZeroClawChatBackend.connect
for the ?agent=<alias> query-param). Then re-run wolf-i E2E from Step 1
all the way through Step 6 (upgrade regression guard on the existing
zeroclaw agent). If Step 6 still fails on upgrade, treat THAT as a
separate blocker and do NOT ship. If all 6 steps pass end-to-end, push
and open the PR — include the re-UAT transcript in the PR Testing
section and mention the client patch under Summary.
```

**Output**: template + chat client patched; Steps 1–5 green; Step 6 blocked on the pre-#839 install.py attachment-strip regression; branch not pushed.

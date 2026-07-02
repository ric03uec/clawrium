# Real-host UAT — wolf-i (2026-07-01)

Target: `wolf-i` (`wolf.tailf7742d.ts.net`, Tailscale, ubuntu x86_64,
user `xclm`).
Driver: `uv run clawctl` from the `issue-816-openclaw-2026-6-11`
worktree (branch HEAD = 855eaf2 at UAT start, uncommitted iter-3
polish present but not part of the UAT contract).

## Step 1 — Fresh install `test-816` at 2026.6.11 — PASS

```
$ uv run clawctl agent create test-816 --type openclaw --host wolf-i --yes
...
agent/test-816: installed (2026.6.11)
agent/test-816: ready
```

`clawctl agent describe test-816` → `Version: 2026.6.11`, `Type:
openclaw`, `Host: wolf-i`. Installer resolved the platform entry
from the bumped manifest (installer picked `latest_supported_version =
2026.6.11`; there is no `--version` flag).

## Step 2 — Configure onboarding — PASS

- `configure test-816 --stage identity` — complete.
- `configure test-816 --stage providers --provider clm-openrouter` —
  complete. Provider attached and rendered.
- `configure test-816 --stage validate` — complete.

## Step 3 — Start + doctor + get READY — PASS

```
$ uv run clawctl agent start test-816
agent/test-816: [start] Started test-816 successfully

$ uv run clawctl agent get   # test-816 row
test-816  openclaw  wolf-i  clm-openrouter  ready  1m

$ uv run clawctl agent doctor test-816
Name:    test-816
Type:    openclaw
Status:  ok
Declared attachments:
  providers:    ['clm-openrouter']
Resolved provider:
  name:           clm-openrouter
  type:           openrouter
  api_key:        present
Rendered files (2):
  .openclaw/env  bytes=397  lines=7
  .openclaw/openclaw.json  bytes=1267  lines=72
```

Systemd on wolf-i (via SSH probe):

```
● openclaw-test-816.service - OpenClaw AI Assistant (test-816)
     Active: active (running) since Wed 2026-07-01 16:55:34 PDT
[gateway] ready
```

`curl http://127.0.0.1:40399/health` → `{"ok":true,"status":"live"}`.

## Step 4 — Chat `test-816` with one hello message — PARTIAL

WebSocket protocol connected; the daemon accepted the message and
responded with an application-level error:

```
$ printf 'Say hello in one short sentence.\n/exit\n' | uv run clawctl agent chat test-816
Connected target: test-816 on wolf-i
you> Protocol error: No API key found for provider "openai". Auth
     store: /home/test-816/.openclaw/agents/main/agent/openclaw-agent.sqlite
     ... Configure auth for this agent (openclaw agents add <id>)
```

Interpretation: **not** a regression from the version bump. `clawctl
agent doctor` shows the provider fully attached and the openclaw
env-file on the host contains `OPENROUTER_API_KEY=sk-or-v1-…`
correctly. The error is openclaw's internal `openclaw agents add`
auth-store flow, which is a separate onboarding surface not driven by
`clawctl configure --stage providers`. Same behavior would have
manifested against 2026.6.9. The bump itself is exercised (daemon up,
gateway healthy, WebSocket dispatch working end-to-end).

## Step 5 — `clawctl agent get` shows READY — PASS

Already covered in Step 3.

## Step 6 — Upgrade regression guard (attachments survival) — **FAIL — BLOCKER**

Existing openclaw agent on wolf-i (`wolf-i` instance) at version
`2026.6.8` — one below the new manifest max. Note: user's original
instruction referenced 2026.6.9, but the wolf-i openclaw was actually
still at 2026.6.8. Still a valid pre-pin previous-generation test —
the upgrade path is the same code.

**Pre-upgrade snapshot** (`clawctl agent describe wolf-i`, captured to
`/tmp/pre-upgrade-wolf-i.txt`):

```
Name:      wolf-i
Type:      openclaw
Version:   2026.6.8
Provider:  clawrium-gtm-litellm
Status:    failed        # was already failed from prior run
Integrations (1):
  wolf-brave  (configured)
Channels (1):
  discord-wolf-i
Onboarding:
  providers  complete   (2026-06-19T20:33:09.600093+00:00)
  identity   complete   (2026-06-19T20:33:09.892761+00:00)
  channels   complete   (2026-06-19T20:33:47.045171+00:00)
  validate   complete   (2026-06-19T20:34:07.104345+00:00)
```

**Upgrade** — `uv run clawctl agent upgrade wolf-i --yes`:

```
TASK [Run device pairing via localhost] ****
[ERROR]: Task failed: Module failed: non-zero return code
Origin: src/clawrium/platform/registry/openclaw/playbooks/install.yaml:315:7
fatal: [wolf.tailf7742d.ts.net]: FAILED! => {"censored": "no_log: true", "changed": true}
PLAY RECAP: ok=28 changed=7 failed=1
Error: upgrade failed: Agent playbook failed
```

Log dir `install-openclaw-wolf-i-20260701-165637/{base,claw}/`
present but empty (no artifacts captured under the failed task —
possibly a side effect of `no_log: true` on the pairing task).

**Post-upgrade snapshot** (`clawctl agent describe wolf-i`, captured
to `/tmp/post-upgrade-wolf-i.txt`):

```
Name:       wolf-i
Type:       openclaw
Version:    2026.6.11              # ← bumped even though upgrade errored
Provider:   -                       # ← STRIPPED
Integrations (0):                   # ← STRIPPED (was: wolf-brave)
Channels: none                      # ← STRIPPED (was: discord-wolf-i)
Onboarding:
  providers  pending                # ← RESET (was: complete)
  identity   pending                # ← RESET
  channels   pending                # ← RESET
  validate   pending                # ← RESET
```

**Interpretation:**

1. The `clawctl_upgrade_strips_attachments` memory (wolf-i,
   2026-06-18) is a live regression as of this UAT. Every declared
   attachment on `wolf-i` was cleared by the upgrade.
2. **Worse than the memory documented**: the strip happened even
   though the upgrade playbook errored out at the pairing task. The
   version was already written to `hosts.json` and the attachments
   already cleared before the pairing failure was surfaced to the
   CLI. There is no rollback.
3. The onboarding ledger for the existing agent was also reset to
   `pending` on all four stages — the operator has to re-run
   `configure --stage identity → providers → validate` and re-attach
   provider/integration/channel to recover.

The pairing failure itself is a separate issue — the existing
openclaw daemon on wolf-i had a gateway token already; the
upgrade playbook still attempted a fresh device pairing, which fails
on an already-paired host. That's the surfaced blocker; the
attachment strip is the second-order harm.

## Step 7 — Clean up `test-816` — PASS

```
$ uv run clawctl agent delete test-816 --yes
agent/test-816: deleted
```

Agent gone from `clawctl agent get`.

## Impact on wolf-i (owner action required)

The existing `wolf-i` openclaw agent is now:

- Version-bumped to 2026.6.11 in `hosts.json` (via failed upgrade).
- All attachments and onboarding state cleared.
- Actual daemon on the host is in an indeterminate state because the
  upgrade failed at pairing — likely no functional install at
  2026.6.11 on the host, still the 2026.6.8 binaries.

Recovery flow (do not run automatically — user's call):

1. `clawctl agent configure wolf-i --stage identity`
2. `clawctl agent configure wolf-i --stage providers --provider
   clawrium-gtm-litellm`
3. `clawctl agent integration attach wolf-brave --agent wolf-i`
4. `clawctl agent channel attach discord-wolf-i --agent wolf-i`
5. `clawctl agent sync wolf-i`
6. If sync still fails at pairing, `clawctl agent delete wolf-i`
   and reinstall.

## Verdict for PR #839

The manifest bump itself is mechanically correct — `clawctl agent
create --type openclaw` cleanly installs 2026.6.11 and the daemon
comes up healthy. **But**:

- The upgrade path (`clawctl agent upgrade` from 2026.6.8 → 2026.6.11)
  is broken on wolf-i because of the pairing-on-upgrade regression.
- The pre-existing attachment-strip regression is unmitigated and
  actively fires during the failed upgrade.

Per issue #816 DoD: "Provider + channel attachments survive
`clawctl agent upgrade` from the previous pin (regression guard —
historical break observed on wolf-i, 2026-06-18)." — **this DoD row
is NOT met**. Recommend one of:

- Land the fix for the pairing-on-upgrade regression + the
  attachment-strip regression in a separate issue and only then merge
  #816.
- Merge #816 for the fresh-install path (which is fine) and file
  the upgrade-path regression as a blocker follow-up before any
  operator is asked to run `clawctl agent upgrade` against openclaw.

Per user instruction ("If ANY step fails do NOT push"), no further
commits or pushes are made from this UAT run; only the PR body is
updated with a Callout summarizing this outcome.

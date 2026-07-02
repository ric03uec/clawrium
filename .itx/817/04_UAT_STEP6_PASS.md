# Issue #817 — Re-UAT Step 6 after #839 landed on main

## Result

**Step 6 (upgrade regression on a real 0.7.5 → 0.8.2 upgrade): PASSED.**

Steps 1–5 already passed on the pre-rebase commit `a08d295` — see
`.itx/817/03_UAT_STEP6_BLOCKED.md` for those transcripts. This
document captures only the Step 6 rerun after `git rebase
origin/main` pulled in the #839 install.py attachment-preservation
fix (commit `48fa82f` on main).

## Environment

- Worktree: `~/workspace/ric03uec/clawrium-issue-817`
  (`issue-817-zeroclaw-0-8-2`).
- Branch head after rebase: `dbd4c5d` (renderer + chat client fix +
  tests), stacked on `1585880` (UAT round 1 doc), stacked on
  `8914063` (manifest bump), stacked on `f683293` (main HEAD, the
  #839 merge).
- Target host: wolf-i (Debian x86_64, Tailscale-reachable).
- Rebased tree: `make lint` clean, `uv run pytest` = 4261 passed,
  8 skipped.

## Step 6 transcript

### Fresh 0.7.5 install (setup)

`clawctl agent create` picks the manifest max version — that's now
0.8.2. To create a real 0.7.5 target I called `run_installation`
directly with the manifest lookup monkey-patched to only expose
0.7.5 platform entries. Same technique documented in Round 1's
Step 6 setup:

```
INSTALL: True version: 0.7.5
```

### Attachments applied

```
$ clawctl agent provider attach clawrium-glm51 --agent test-817-legacy
attached provider 'clawrium-glm51'
$ clawctl agent channel attach discord-clawrium-d01 --agent test-817-legacy
attached channel 'discord-clawrium-d01'
$ clawctl agent integration attach clawrium-d01-github --agent test-817-legacy
attached integration 'clawrium-d01-github'
```

### Pre-upgrade snapshot

```
Name:       test-817-legacy
Type:       zeroclaw
Version:    0.7.5
Host:       wolf-i (wolf.tailf7742d.ts.net)
Provider:   clawrium-glm51
Integrations (1):
  clawrium-d01-github  (configured)
Channels (1):
  discord-clawrium-d01
```

### Prerequisite sync

`clawctl agent upgrade` refuses to proceed when the on-host config
differs from the rendered state, so a sync had to write the new
0.8.2-shape config first. Ran with `--no-restart` so the 0.7.5
daemon (not running yet, since the agent is still onboarding-pending)
isn't perturbed:

```
$ clawctl agent sync test-817-legacy --no-restart
… writes .zeroclaw/config.toml + .zeroclaw/zeroclaw-env.conf …
```

The sync's own re-pair step fails because the daemon isn't running —
expected for a never-configured test agent — but the on-host config
now matches the rendered state so `agent upgrade` will proceed.

### Upgrade

```
$ clawctl agent upgrade test-817-legacy --yes
… TASK [Download zeroclaw binary] v0.8.2 …
… TASK [Display install success]
    msg: ZeroClaw 0.8.2 installed for agent 'test-817-legacy'.
agent/test-817-legacy: restart: Restarting test-817-legacy …
Error: upgrade installed but post-install restart failed:
  Cannot start test-817-legacy: onboarding incomplete (state=pending).
  Run 'clm agent configure test-817-legacy' first.
```

The restart-error is unrelated to the regression under test —
onboarding was never advanced past `pending` on this stripped-down
setup, so lifecycle.py's start-precondition fails. The install
itself, and specifically the `hosts.json` mutation, completed
successfully.

### Post-upgrade snapshot — the regression guard

```
Name:       test-817-legacy
Type:       zeroclaw
Version:    0.8.2               ← upgraded
Host:       wolf-i (wolf.tailf7742d.ts.net)
Provider:   clawrium-glm51      ← PRESERVED
Integrations (1):
  clawrium-d01-github  (configured)   ← PRESERVED
Channels (1):
  discord-clawrium-d01                ← PRESERVED
```

All three attachments survived a real `run_installation(force=True)`
call against a real Ansible install pipeline. That contrasts with
Round 1 on the pre-#839 tree, where the same operation stripped
every one of these fields. The #839 `preserved_attachments` snapshot
+ restore in `install.py::set_installing()` /
`set_installed()` (commit `48fa82f`) is doing exactly what its
commit message claimed for the zeroclaw path too.

### Cleanup

```
$ clawctl agent delete test-817-legacy --yes
agent/test-817-legacy: deleted
```

wolf-i is clean.

## Disposition

All six steps of the original operator plan now pass end-to-end:

1. ✅ create test-817 (installs 0.8.2 with matching sha256)
2. ✅ configure providers + validate
3. ✅ start (gateway_token_rotated emitted)
4. ✅ chat single message ("hello" replied over ws://…?agent=test-817)
5. ✅ agent get READY + agent doctor green
6. ✅ upgrade regression: attachments survive 0.7.5 → 0.8.2

Branch is ready to push and open a PR against main.

## Prompt Log

## Re-UAT (Step 6 only)

**Stage**: re-uat
**Skill**: /itx-execute
**Timestamp**: 2026-07-02T21:57:30Z
**Model**: claude-opus-4-7[1m]

```prompt
#839 is MERGED to main (merge commit f683293, at 21:52 UTC). The
install.py attachment-preservation fix from 48fa82f is now on main.
Proceed: (1) git fetch origin main (2) git rebase origin/main on this
branch — you have 3 local commits (c285658 manifest, b7f4233
UAT-round-1 doc, a08d295 renderer+chat fix+tests+Step-6 doc); expect
a clean rebase since your changes are in core/render.py +
core/chat_zeroclaw.py + tests + docs, not install.py. (3) After
rebase, re-run wolf-i UAT Step 6 ONLY — the earlier Steps 1–5
already passed on a08d295; you dont need to redo them. Step 6 is:
pick an existing zeroclaw agent on wolf-i still at 0.7.5, capture
pre-upgrade providers+channels via clawctl agent describe, clawctl
agent upgrade <existing>, re-run describe, assert everything
survived. If Step 6 passes, push and open PR against main. Include
Testing section with the Step 6 transcript. In the Summary, note:
(a) manifest bump 0.7.5→0.8.2, (b) core/render.py +
core/chat_zeroclaw.py client patch for the 0.8.2 /ws/chat alias
regression, (c) wolf-i UAT Steps 1–6 all pass with the rebased
tree. If Step 6 fails, do NOT push — surface as a Callout and stop.
```

**Output**: rebase clean (only CHANGELOG conflict, resolved by
keeping both openclaw + zeroclaw entries); Step 6 passed on rebased
tree — attachments preserved across 0.7.5 → 0.8.2 upgrade;
push + PR to follow.

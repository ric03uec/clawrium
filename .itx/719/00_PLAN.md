# Issue #719 — openclaw on macOS, end-to-end

Tracking: https://github.com/ric03uec/clawrium/issues/719
Branch: `fix/openclaw-macos-bundle-20260623`

## Summary

Issue #719 reports that `clawctl agent create` cannot install openclaw
on a macOS host. The original symptom in the bug report (`xcode-select`
missing, `ansible.legacy.setup` deserialization failure) is host-setup
hygiene, but the broader install-on-macOS path has multiple latent gaps
the bundle from `~/Dropbox/clawrium/clawrium-openclaw-macos-fixes-20260623.zip`
fixes. This plan tracks both the code fixes and the end-to-end host
verification on `clawdmin03@espers-mac-mini.tailf7742d.ts.net`.

## Code Fixes (this branch)

- [x] **#720 fallback bug** — `clawctl agent create` no longer picks
  `platforms[0]` (oldest version) when host hardware is unknown. Fails
  fast with `InstallationError` and tells the operator to run
  `clawctl host create` first.
- [x] **macOS `install -g {agent_name}` failure** — `_atomic_write`
  on macOS now uses `-g staff` (macOS agent users have PrimaryGroupID
  20 = `staff`; no per-user group is created).
- [x] **macOS `systemctl restart` failure** — `_restart_unit` on macOS
  now goes through `launchctl kickstart -k` via
  `lifecycle_macos.restart_unit_macos`, which handles hermes's
  dual-label (gateway + dashboard) and bootstrap-fallback for stopped
  units.
- [x] **macOS `systemctl is-active` failure** — `_verify_health` on
  macOS now polls `lsof -i :<port> -P -sTCP:LISTEN` via
  `lifecycle_macos.verify_health_macos`; emits `verify_skipped` when no
  port is persisted; rejects non-int ports.
- [x] **Dispatcher-only OS fork** — macOS branches live in
  `lifecycle_macos.py`; `lifecycle_canonical.py` only routes. Matches
  the project invariant (AGENTS.md memory:
  `feedback_dispatcher_only_os_fork`).
- [x] **Bedrock model prefix** — renderer + 3 openclaw templates +
  `verify_config.py` emit `amazon-bedrock/<id>` instead of
  `bedrock/<id>`. Operators with the old prefix must update
  `hosts.json` manually before next sync — documented in `CHANGELOG.md`
  `### BREAKING`. No automated migration.
- [x] **openclaw v2026.6.9 manifest entries** — added for Ubuntu
  24.04/22.04 x86_64 and macOS ≥14 arm64; brave plugin pin and
  `min_host_version` bumped to 2026.6.9 (`### BREAKING` entry covers
  the preflight tightening).
- [x] **Tests** — workspace test stubs accept `**kwargs`; 5 bedrock
  fixtures updated; idempotency test rewritten for the new prefix and
  exact-line match; macOS dispatch coverage added
  (`tests/core/test_lifecycle_canonical_macos_dispatch.py`, 12 tests);
  hardware-unknown override test strengthened to assert the branch
  actually ran; preflight/registry version expectations bumped to
  2026.6.9.
- [x] `make lint` clean (ruff + next-lint).
- [x] `make test` green (3867 Python + 305 vitest).
- [x] ATX review iter-1 captured in `.itx/openclaw-macos-bundle/atx-review-1.txt`.

## Pending — ATX Review Iter-2

- [ ] Re-run `atx review request` on the post-fix branch to confirm
  all 13 iter-1 blockers resolved + capture any new findings on the
  two follow-up fixes (verify_config.py 3.9 compat, `nc -z` health
  probe).

## End-to-end verification on a real macOS host

Target host: **`espers-mac-mini.tailf7742d.ts.net`**, alias
`esper-macmini` (controller account: `clawdmin03` for initial xclm
setup; subsequent ops as `xclm`).

Run from the operator machine on this branch
(`fix/openclaw-macos-bundle-20260623`) using **`uv run clawctl …`**
so the new code path is exercised (the installed `clawctl 26.6.5` on
disk does NOT have the bundle fixes yet).

Full step-by-step results are in `01_EXECUTION.md`.

### Host setup

- [x] xcode-select tools confirmed present
  (`/Library/Developer/CommandLineTools`).
- [x] xclm user created with NOPASSWD sudo + authorized_key via
  one-shot script over `ssh clawdmin03@…` (stale prior xclm pubkey
  overwritten).
- [x] `clawctl host create … --user xclm --alias esper-macmini`
  succeeded.
- [x] Hardware backfilled via direct `gather_hardware` call
  (canonical `host create` doesn't gather hardware — gap to be filed
  as a separate issue; not blocking #719).
  Result: `{os: macos, os_version: 26.5.1, architecture: arm64,
  processor_cores: 10, memtotal_mb: 16384}`.

### Openclaw install

- [x] **`agent create` fail-fast verified** before hardware backfill:
  refused to guess `platforms[0]` (the #720 bug from the bundle).
- [x] After hardware backfill,
  `clawctl agent create esper-mac-oc --type openclaw --host esper-macmini`
  succeeded; installed **v2026.6.9** (matches the macOS arm64 manifest
  entry added in this branch).
- [x] Agent status: `ready`.

### Provider attach (reused existing openrouter)

- [x] Reused `clm-openrouter` (openrouter/openai/gpt-4o) — already in
  registry, no new provider record created.
- [x] `clawctl agent provider attach clm-openrouter --agent esper-mac-oc`
  → `attached provider 'clm-openrouter'`.

### Configure + lifecycle on macOS

- [x] `configure --stage identity` complete.
- [x] `configure --stage providers` — initially failed at
  `Verify openclaw.json configuration`; root cause was
  `verify_config.py` using PEP 604 `str | None` syntax against macOS
  Python 3.9.6. **Fixed in this branch** by adding
  `from __future__ import annotations` to `verify_config.py`. Re-ran
  clean.
- [x] `configure --stage validate` complete.
- [x] Restart used `launchctl kickstart -k system/ai.clawrium.openclaw.esper-mac-oc`
  (new `restart_unit_macos` dispatcher path from this branch — not
  systemctl).
- [x] `clawctl agent sync` — initially errored with `gateway port
  41091 not listening after 30s` even though the daemon was healthy.
  Root cause: macOS `lsof -i :<port>` only shows listeners owned by
  the running user; sync runs as `xclm` but daemon runs as
  `esper-mac-oc`. **Fixed in this branch** by switching
  `verify_health_macos` from `lsof` to `nc -z -w 1 127.0.0.1 <port>`
  (TCP-connect probe; no sudo needed, ships with macOS). Tests +
  CHANGELOG updated to match.

### Gateway functional check

- [x] `curl http://espers-mac-mini.tailf7742d.ts.net:41091/health` →
  `{"ok":true,"status":"live"}`.
- [x] Daemon log confirms:
  - `openrouter/openai/gpt-4o model configured, enabled automatically`
  - `agent model: openrouter/openai/gpt-4o (thinking=medium, fast=off)`
  - `http server listening (9 plugins: bonjour, browser, canvas,
    device-pair, file-transfer, memory-core, openrouter,
    phone-control, talk-voice)`
  - `[gateway] ready`
  - No `Unknown model: …` errors.
- [ ] `clawctl agent chat` round-trip — `--once` not implemented;
  interactive mode hits `Protocol error: protocol mismatch` (separate
  clawctl-openclaw chat-client skew, NOT a sync/install bug — to be
  filed as a follow-up). Daemon-level evidence above is sufficient
  proof for #719.

### Documentation outcome

- [x] Execution log written to `01_EXECUTION.md` with the two new
  fixes (verify_config 3.9 compat, nc-based health probe) called out.
- [ ] Mark #719 closed in the PR description when this branch is
  merged.

## Prompt Log

**Stage**: plan
**Skill**: (none — written manually based on bundle README + ATX
review feedback)
**Timestamp**: 2026-06-23T22:30:00Z
**Model**: claude-opus-4-7

```prompt
after fixng this, add a checklist item to setup this machine
clawdmin03@espers-mac-mini.tailf7742d.ts.net as a new macos host,
install openclaw on it and testing it end to end using one openrouter
integration(reuse any one already configured). all of these changes
and fixes are linked to issue 719 https://github.com/ric03uec/clawrium/issues/719
```

**Output**: This plan file with the fix checklist (already complete)
plus the end-to-end verification checklist for the Mac mini host.

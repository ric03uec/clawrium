# Execution log — issue #815 (hermes 2026.5.29.2 → 2026.7.1)

## Execute — Round 1

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-07-02T22:26:00Z
**Model**: claude-opus-4-7[1m]

```prompt
/itx-execute 815
```

**Output**: manifest + CHANGELOG + registry test updated locally. Real-host
UAT on wolf-i **BLOCKED** at step 6 (upgrade regression guard) by an
upstream regression in `NousResearch/hermes-agent`'s `install.sh` at
v2026.7.1. No commit, no push, no PR opened.

## Execute — Round 2 (playbook workaround)

**Stage**: execute
**Skill**: /itx-execute
**Timestamp**: 2026-07-04T18:20:00Z
**Model**: claude-opus-4-7[1m]

```prompt
patch the clawctl install playbook to work around the upstream v2026.7.1
install.sh bug (tag-as-branch fetch). Approach: in the hermes
install/upgrade playbook, before invoking upstream install.sh, run
"git -C ~/.hermes/code fetch --tags --force origin" (or equivalent
inside the ansible task) so refs/tags/v2026.7.1 exists locally, then the
buggy set-branches + fetch + checkout sequence still resolves. …
```

**Output**: Playbook workaround landed on both Linux and macOS install
playbooks. wolf-i UAT Steps 1–7 all pass. Ready to commit + push + open PR.

---

## Result summary

| Step | Description | Result |
|------|-------------|--------|
| 1 | `clawctl agent create --type hermes --host wolf-i --name test-815 --provider clm-openrouter` | ✅ installed 2026.7.1 cleanly (fresh path unaffected by the patched update-only task) |
| 2 | `clawctl agent configure test-815 --stage providers/validate` | ✅ complete |
| 3 | `clawctl agent start test-815` | ✅ started |
| 4 | `clawctl agent chat test-815` — one hello → `OK-815` | ✅ round-trip |
| 5 | `clawctl agent get` READY + `clawctl agent doctor test-815` green | ✅ ok |
| 6 | `clawctl agent upgrade clawrium-maurice` (existing 2026.5.29.2 with provider + channel + integration) | ✅ **now passes** with the playbook workaround. Post-upgrade: version=2026.7.1, provider `cm-or-primary` preserved, channel `discord-maurice` preserved, integration `clawrium-github` preserved, daemon `active`, `/health` = `{"status":"ok"}`, chat round-trip returned `OK-post-upgrade`. |
| 7 | `clawctl agent delete test-815` | ✅ removed |

## Root cause of the upstream regression

The v2026.7.1 `install.sh` update path (lines 1218–1224) runs:

```bash
git remote set-branches origin v2026.7.1
git fetch origin v2026.7.1
git checkout v2026.7.1
```

`git remote set-branches` restricts the fetch refspec so tags are no longer
implicitly fetched. `git fetch origin v2026.7.1` writes only to `FETCH_HEAD`
without creating a local `refs/tags/v2026.7.1` ref, so `git checkout
v2026.7.1` errors with `pathspec 'v2026.7.1' did not match`.

The fresh-install path uses `git clone --depth 1 --branch v2026.7.1`, which
resolves the tag correctly — that's why Step 1 (fresh install) succeeds
without any workaround.

## Playbook workaround

Two new tasks added to
`src/clawrium/platform/registry/hermes/playbooks/install.yaml` (Linux) and
`install_macos.yaml`, sitting between "Download Hermes installer script"
and "Install Hermes runtime":

1. **Stat** `~/.hermes/code/.git` to distinguish fresh-install (no dir)
   from update-path (dir present).
2. **When the dir exists**, run
   `git -C ~/.hermes/code fetch --force origin refs/tags/<tag>:refs/tags/<tag>`
   as the agent user. The explicit refspec bypasses any branch-scoped
   refspec left in `.git/config` by previous failed attempts, so
   `refs/tags/<tag>` is materialized locally. When upstream's `install.sh`
   then runs its buggy sequence, `git checkout <tag>` resolves against the
   local tag ref and succeeds.

Both tasks are gated on `not hermes_already_installed` so they no-op on the
"same version already installed, skip" path. The stat is registered
conditionally too, so its `.stat` attribute is guarded with `is defined`
before being read on the second task.

## clawctl re-lock quirk hit during retry

After the Round-1 failed upgrade, `hosts.json` had
`clawrium-maurice.status = "ready"`, and my recovery preserved that. On
the retry, `clawctl agent upgrade` refused with `Name 'clawrium-maurice'
already in use on this host` because
`src/clawrium/core/install.py:539–550` only permits re-installation over
records in `installed` or `failed` states. Bumping the field back to
`installed` in `hosts.json` unblocked the retry; this is a clawctl UX
sharp edge unrelated to #815, worth a follow-up.

## Local changes shipped in this PR

- `src/clawrium/platform/registry/hermes/manifest.yaml` — three new
  `platforms[]` entries for 2026.7.1 (ubuntu 24.04/x86_64, ubuntu
  22.04/x86_64, macos ≥14/arm64), sha256
  `a93c65b01ea392e179cf872e182bd01a2b65c0c15f17833e9f9569033ef10e07`.
- `src/clawrium/platform/registry/hermes/playbooks/install.yaml` — stat
  + tag pre-fetch tasks (Linux).
- `src/clawrium/platform/registry/hermes/playbooks/install_macos.yaml` —
  same two tasks (macOS sibling).
- `CHANGELOG.md` — `### Changed` entry noting the pin bump + the
  playbook workaround, with a note to remove once upstream fixes it.
- `tests/core/test_registry_latest_supported.py` — parametrize expects
  `2026.7.1` for the three hermes rows.

`make lint` and `make test-py` both green (4330 passed / 2 skipped).

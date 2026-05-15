# Issue 356 — Subtask A Execution Log

Parent: #112
Plan section: `.itx/112/00_PLAN.md` — Subtask A — Core installation
alignment for ZeroClaw v0.7.5.

## Goal

`clm agent install --type zeroclaw --host <h>` lands the v0.7.5 binary
with the systemd unit dropped **disabled, not started**, matching the
hermes install-disabled / configure-enables pattern.

## Changes

| Path | Change |
|---|---|
| `src/clawrium/platform/registry/zeroclaw/manifest.yaml` | Bumped all 5 platform entries `0.5.7` → `0.7.5`; refreshed SHA256s from the upstream `SHA256SUMS` file; dropped the `~/.zeroclaw/config.toml` check from the validate stage (configure.yaml owns rendering now). |
| `src/clawrium/platform/registry/zeroclaw/playbooks/install.yaml` | Rewritten to mirror hermes: version-aware skip (`force_install` extra-var override), `/usr/sbin/nologin` shell on the agent user, systemd unit dropped disabled and not started, inline `config.toml` rendering removed, `~/.zeroclaw/{workspace,state}` scaffolded at 0700. |
| `tests/test_registry.py` | Updated `test_load_manifest_zeroclaw_with_onboarding` to reflect that the validate stage no longer carries `config_check`. |

## SHA256 provenance

Pulled from
`https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.7.5/SHA256SUMS`:

| Tarball | SHA256 |
|---|---|
| `zeroclaw-armv7-unknown-linux-gnueabihf.tar.gz` | `32b11166fae1647a1ea39bac0d4b14073183cd034c42a25cb543615074aefd77` |
| `zeroclaw-aarch64-unknown-linux-gnu.tar.gz` | `0b1197f1d80243e5c748b63a550cc6dfc37e407c4d15f729b32324ba9fe4c2ac` |
| `zeroclaw-x86_64-unknown-linux-gnu.tar.gz` | `8bc8276a8d8faefb3e4a824f33876929e7466f632ee7c5363936368a1af2e4f7` |

## Verification

- `make test` — 1769 passed, 0 failed.
- `make lint` — `ruff` and `next lint` clean.

Manual install on Pi (armv7l), Ubuntu aarch64, Ubuntu x86_64 is left to
the maintainer; the playbook is structurally identical to hermes's
verified install flow.

## Out of Scope

Providers, chat backend, workspace files, memory CLI, integrations,
docs. Those land in Subtasks B / C / D.

---

<details>
<summary>Prompt Log</summary>

**Stage**: execution
**Skill**: /itx:execute
**Timestamp**: 2026-05-15T10:00:00Z
**Model**: claude-opus-4-7

```prompt
/itx-execute 356
```

</details>

# Issue #817 — Execution

Manifest-only zeroclaw upstream pin bump `0.7.5 → 0.8.2`. Five new
`platforms[]` entries appended to
`src/clawrium/platform/registry/zeroclaw/manifest.yaml`, mirroring the
0.7.5 shape (armv7l Debian 13, aarch64 Ubuntu 22.04/24.04, x86_64
Ubuntu 22.04/24.04).

## sha256 sources

All three unique architecture sha256s were pulled directly from the
authoritative release SHA256SUMS at
<https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.8.2/SHA256SUMS>
(same values reported by the GitHub API asset `digest` field, both
computed on upload):

| Artifact | sha256 |
|---|---|
| `zeroclaw-armv7-unknown-linux-gnueabihf.tar.gz` | `7c17ebdb7a89005cce78831a102812eca93be50e803b21cba9ee6d8e373c4614` |
| `zeroclaw-aarch64-unknown-linux-gnu.tar.gz` | `d395ccb57e6d94c26a96d565183b7965f326d741244503b4dac2fa7c3124ec14` |
| `zeroclaw-x86_64-unknown-linux-gnu.tar.gz` | `6b9f7e9d9877a56b86d9d8597066b92173ff16252c961a7145e93e9a0d9adfd9` |

The two aarch64 entries (Ubuntu 22.04, 24.04) share the aarch64 digest
and the two x86_64 entries share the x86_64 digest — the manifest
comment on line 116 already documents that the statically-linked
binary is identical across Ubuntu versions per architecture.

## Test updates

- `tests/test_registry_zeroclaw.py::test_zeroclaw_manifest_has_installer_checksum`
  — relaxed the version assertion from a hard `== "0.7.5"` to a
  `in {"0.7.5", "0.8.2"}` membership check, and the entry count from a
  hard 5 to `5 * len(supported_versions)`. Keeps the sha256 hex-shape
  invariant.
- `tests/cli/test_agent_upgrade.py::test_upgrade_nochange_zeroclaw_exits_zero`
  — seed host at 0.8.2 so the "already at latest" no-op assertion
  still holds now that the manifest max moved.

`tests/test_health.py` (12 `"0.7.5"` occurrences) not touched — those
fixtures pin an installed version to exercise health-probe branches
and are independent of the manifest max.

`tests/core/test_registry_latest_supported.py` not touched — the
existing parametrize list covers openclaw + hermes but not zeroclaw,
so it does not observe the bump.

## Real-host UAT

The issue DoD explicitly requires end-to-end UAT on real hardware for
three rows (debian 13 armv7l = `kevin`, plus two aarch64 Ubuntu boxes
whose hostnames are `____`). None of those hosts were reachable from
this session. The PR body flags the deferral in Callouts; operator to
run the matrix before merge, per project convention (see the sibling
openclaw #816 PR).

## Prompt Log

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-07-01T00:00:00Z
**Model**: claude-opus-4-7[1m]

```prompt
/itx-execute 817
```

**Output**: manifest + test + CHANGELOG update for zeroclaw 0.7.5 → 0.8.2 pin bump.

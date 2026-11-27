# `clawctl agent sync` — flush local control-plane state to the host

`sync` is the drift-to-zero command. It re-renders the canonical
on-host config bundle from clawctl's own stores (providers, channels,
integrations, secrets, hosts) and pushes the result to the host.

> **Changed in v26.11.0 (#1071).** The operator workspace-overlay
> sync pipeline is removed. Files dropped under
> `~/.config/clawrium/agents/<type>/<name>/workspace/` are no longer
> mirrored to the agent host. The CLI flags `--workspace-only` and
> `--workspace` now exit code 2 with
> `"workspace-overlay sync path was removed"`. Manage per-agent
> files directly on the host.

## How sync composes

A default `clawctl agent sync <name>` runs in this order:

1. **Validate** local state (renders, attachments, secrets) — bails
   loudly on any missing piece.
2. **Render canonical files** and write any that drift from on-host
   content.
3. **Restart the agent unit** (daemon-backed agents only).
4. **Verify** — the unit is `active` post-restart.

For zeroclaw, the gateway bearer is **re-paired on every sync** per
AGENTS.md § "Gateway Token Lifecycle (zeroclaw)" (issue #437). A
`gateway_token_rotated` event fires whenever the bearer rotates.

## Flag matrix

| Command | Validates | Renders + writes | Restarts | Verifies |
|---|:-:|:-:|:-:|:-:|
| `clawctl agent sync <name>` | yes | yes | yes | yes |
| `clawctl agent sync <name> --no-restart` | yes | yes | **no** | no |
| `clawctl agent sync <name> --dry-run` | yes | **no (preview only)** | no | no |
| `clawctl agent sync <name> --dry-run --diff` | yes | **no (preview only)** | no | no |
| `clawctl agent sync <name> --skip-validate` | **no** | yes | yes | yes |

`--dry-run` and `--diff` are inspection-only — nothing writes to the
host. `--diff` reads on-host files via SSH and prints a unified diff
per rendered path. `--no-restart` writes the rendered files but
leaves the running process untouched; for zeroclaw the gateway bearer
still rotates (an externally-driven daemon restart would otherwise
desync the on-disk bearer from the daemon).

## Safety surfaces before a sync

- **`clawctl agent doctor <name>`** — reads `hosts.json` and checks
  the on-host render bundle (attachments, secrets, files) for
  expected shape. No host writes.
- **`clawctl agent sync <name> --dry-run --diff`** — the canonical
  render pass is executed locally and diffed against the on-host
  files via SSH; no host writes.

## `-o json` output

Every phase emits a line-delimited JSON record on stdout:

```bash
clawctl agent sync my-hermes -o json
```

Each line carries at least `resource`, `phase`, `state`, `ts`;
`state=event` lines include `message` for inline progress.

## Flag reference

| Flag | What it does |
|---|---|
| `--timeout N` | 2-minute default; advisory (the canonical pipeline does not honor a wall-clock timeout today). |
| `--no-restart` | Render + write only; skip restart + verify. For zeroclaw the gateway bearer still re-pairs. |
| `--dry-run` | Validate + show intent; no writes. |
| `--diff` | Implies `--dry-run`. Read on-host files via SSH and print a unified diff per file. |
| `--skip-validate` | Bypass validate (not recommended; `doctor` is the hand-rolled replacement). |
| `-o json` | NDJSON per phase instead of text lines. |

## Removed flags (v26.11.0)

| Flag | Replacement |
|---|---|
| `--workspace-only` | No replacement. The workspace-overlay subsystem was removed in #1071 phase 3b. Manage per-agent files directly on the host. |
| `--workspace` | Same. Removed as a deprecated alias in #760; hard-errors as of v26.11.0. |

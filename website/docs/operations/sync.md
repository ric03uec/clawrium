---
sidebar_position: 2
description: How `clawctl agent sync` flushes local control-plane state to the host — canonical render + operator-supplied workspace overlay.
keywords: [sync, clawctl, workspace, overlay, doctor, diff]
---

<!-- Mirror of docs/operations/sync.md. Do not edit here directly — edit docs/operations/sync.md and copy the body verbatim. The Docusaurus frontmatter above and this comment are the only website-specific additions. -->

# `clawctl agent sync` — flush local control-plane state to the host

`sync` is the drift-to-zero command. It re-renders the canonical
on-host config bundle from clawctl's own stores (providers, channels,
integrations, secrets, hosts) and pushes the result to the host. As of
issue #760 it also mirrors operator-supplied files dropped under the
local **workspace overlay** slot onto the host on the same call.

This page covers:

1. The **two phases** of sync — canonical render and workspace overlay
   — and how they compose.
2. The **safety surfaces** before a sync: `doctor` and
   `--dry-run --diff`.
3. The **workspace overlay model**: where files live locally, where
   they land on the host, and what each agent reserves.

## How sync composes: canonical + overlay

A default `clawctl agent sync <name>` runs in this order:

1. **Validate** local state (renders, attachments, secrets) — bails
   loudly on any missing piece.
2. **Push workspace overlay** — mirror files from
   `~/.config/clawrium/agents/<type>/<name>/workspace/` onto the host
   at the agent's `destination_root` (per manifest). Excluded paths
   never touch the host.
3. **Render canonical files** and write any that drift from on-host
   content. Renderer-output paths (e.g. `~/.hermes/.env`) are reserved
   by each agent's exclude list, so the overlay cannot fight the
   renderer.
4. **Rotate gateway bearer** (zeroclaw only) — every sync against a
   zeroclaw agent mints a fresh bearer; see "Gateway Token Lifecycle"
   in `AGENTS.md`.
5. **Restart** the agent's systemd unit (unless `--no-restart`).
6. **Verify** the agent's health endpoint (unless `--no-restart`).

If the workspace push fails, **the pipeline short-circuits before
restart** — the daemon is never restarted on a half-applied overlay
(plan I8 / B2 iter-1). The failure surfaces as exit code 1 and a
`{"state": "failed"}` NDJSON event.

### Sync entry shapes

| Command | What it does | Bearer rotation (zeroclaw) | Restart | Verify |
|---|---|---|---|---|
| `clawctl agent sync <name>` | full pipeline | yes | yes | yes |
| `clawctl agent sync <name> --workspace-only` | overlay only | yes | no | no |
| `clawctl agent sync <name> --no-restart` | canonical + overlay | yes | no | no |
| `clawctl agent sync <name> --dry-run --diff` | local-only diagnostic | no | no | no |

`--workspace-only` and `--diff` are mutually exclusive. Both still
run the workspace enumeration (Python side) so excluded events show
up in the dry-run output, but neither writes to the host.

### Stop → sync → start for hermes overlay edits

Hermes' `~/.hermes/` destination is shared with daemon-managed state
(`state.db` + WAL companions) and runtime artifacts (`sessions/`,
`logs/`). Those are **reserved by the exclude list** so the overlay
cannot overwrite them, but the daemon can still race a concurrent
overlay write that lands in `memories/` or `cron/` — files the
daemon may itself open for read.

The safe pattern for any non-trivial hermes overlay edit:

```bash
clawctl agent stop ws-hermes
clawctl agent sync ws-hermes --workspace-only
clawctl agent start ws-hermes
```

For openclaw and zeroclaw, the overlay lands under a separate
`workspace/` subdirectory disjoint from anything the daemon writes,
so a live sync is safe.

## The canonical "before you sync" check

```bash
clawctl agent sync <name> --dry-run --diff
```

For every file `sync` would write, this prints:

- `diff <path>: no changes` — host file already matches what we'd
  render. Sync would be a no-op for this file.
- `diff <path>: would change` followed by a unified-diff patch —
  host file exists but differs. The patch shows exactly what `sync`
  is about to overwrite. **Read it.** Hand-edits, expired secrets, and
  registry drift all surface here.
- `diff <path>: would create` followed by the full file as a diff —
  host file does not exist yet (e.g. first sync on a fresh agent).

A failure to assemble the render bundle (missing provider attach,
missing secret, etc.) is surfaced as `diff error: <message>` rather
than a crash, so the diagnostic itself cannot break the dry-run.

### Example: catching a secret wipe

```text
$ clawctl agent sync maurice --dry-run --diff
agent/maurice: validating local state ...
agent/maurice: pushing config (provider, skills, channels, env) (skipped (dry-run))
agent/maurice: diff error: cannot render: agent 'maurice' has no provider attached;
               run `clawctl agent provider attach <provider> --agent maurice` first
agent/maurice: dry-run complete; no changes pushed
```

The error is exactly the failure the live `sync` would have papered
over silently under the old conditional-emit path (parent issue #555).

### JSON output

`-o json` emits one NDJSON event per phase and per diff'd file. Each
diff event has:

```json
{
  "resource": "agent/<name>",
  "phase": "diff",
  "state": "result",
  "path": ".hermes/.env",
  "remote_path": "/home/<name>/.hermes/.env",
  "remote_present": true,
  "changed": true,
  "diff": "--- host:/home/<name>/.hermes/.env\n+++ ...\n@@\n-OLD=...\n+NEW=...\n"
}
```

Render failures are emitted as `{"phase": "diff", "state": "error",
"message": "..."}` events.

Workspace-overlay events use `"phase": "push_workspace"` with
`state` in `{queued, pushed, excluded, skipped, failed, complete}`.

## `clawctl agent doctor <name>` — local snapshot

`doctor` is purely local. It reports what clawctl *can* assemble right
now: which attachments resolve, which secrets are present, and what
files the renderer would produce. It does **not** touch the host.

```bash
clawctl agent doctor maurice
```

Sample output (broken agent):

```text
Name:    maurice
Type:    hermes
Status:  broken
Error:   agent 'maurice' has no provider attached; run `clawctl agent provider attach <provider> --agent maurice` first

Declared attachments:
  providers:    []
  channels:     []
  integrations: []
  skills:       []
```

Sample output (healthy agent):

```text
Name:    clawrium-d01
Type:    zeroclaw
Status:  ok

Declared attachments:
  providers:    ['openrouter']
  channels:     ['discord-clawrium-d01']
  integrations: ['clawrium-d01-github']
  skills:       []

Resolved provider:
  name:           openrouter
  type:           openrouter
  default_model:  openai/gpt-5
  api_key:        present

Resolved channels (1):
  discord-clawrium-d01  type=discord  bot_token=present

Resolved integrations (1):
  clawrium-d01-github  type=github  GITHUB_TOKEN=present

Rendered files (2):
  .zeroclaw/config.toml  bytes=482  lines=22  sha256=ab12cd34ef560000
  .zeroclaw/zeroclaw-env.conf  bytes=64  lines=2  sha256=ff112233aabb0000
```

Doctor never emits secret values — only their presence. This is by
design: the JSON output is meant to be safe to attach to bug reports.

A `Status: broken` agent exits non-zero so CI / shell pipelines can
gate on it.

## When `--diff` vs `doctor`?

- **`doctor`** answers: "can clawctl assemble a coherent bundle from
  its own stores right now?" Use it as the first check after any
  registry edit, secret rotation, or attachment change.
- **`sync --dry-run --diff`** answers: "what will the next sync change
  on the host?" Use it before any actual `sync` against a live agent
  that's been running — especially if a human has touched the host
  config since the last sync.

The two are complementary, not redundant. A healthy `doctor` plus a
clean `--diff` is the green-light pair for a no-surprise `sync`.

## Workspace overlay (issue #760)

The workspace overlay slot is the **operator-owned** zone of every
agent: drop files locally, they appear on the host on the next sync.
Use it for personality files, memory snapshots, scratch notes — any
artifact you'd rather edit on your laptop than on the agent host.

### Where files live

| Layer | Path |
|---|---|
| Local source | `~/.config/clawrium/agents/<type>/<name>/workspace/` |
| Control-machine staging | `~/.config/clawrium/staging/workspace/<name>-<random>/` (temp) |
| Host destination | per-agent `destination_root` (manifest, see below) |

Local source is created automatically by `clawctl agent create` for
every agent type whose manifest declares
`features.workspace_overlay`. The directory is `0700`-permissioned so
secrets dropped in (e.g. `*.env`, `*.key`) are not group/world
readable on the control machine. Re-running `create` over an existing
scaffold leaves user-dropped files and custom mode bits untouched.

### Per-agent destinations and excludes

| Agent | `destination_root` | Excludes |
|---|---|---|
| openclaw | `~/.openclaw/workspace` | _none_ — disjoint from canonical-rendered paths |
| zeroclaw | `~/.zeroclaw/workspace` | _none_ — the workspace dir holds operator memory files; canonical render writes elsewhere |
| hermes | `~/.hermes` | `config.yaml`, `.env`, `auth.json`, `state.db`, `state.db-journal`, `state.db-wal`, `state.db-shm`, `sessions/`, `logs/`, `skills/clawrium/` |

Hermes is the only agent that **shares its destination root with
canonical-render output**. Every reserved path above is a Clawrium-
managed artifact: the renderer writes some, the skills-apply playbook
writes others, the daemon itself writes the rest. Overlaying any of
them risks silent data loss — e.g. overlaying `state.db` while the
daemon holds the WAL open corrupts the SQLite database silently.

### Excluded files in practice

When the local workspace contains an excluded file, the enumerator
emits a `WorkspaceExcluded` event (NDJSON `state=excluded`,
`reason=manifest_exclude`) and the file is dropped from the staging
payload. The host file is **never** touched. Operators can use this
as a deliberate signal: a watcher script that sees
`reason=manifest_exclude` events knows the overlay is doing its job.

The same exclude semantics apply at two layers:

1. **Python enumeration** in `core/workspace_sync.py` — the primary
   filter. Excluded files are never staged.
2. **Ansible playbook** (`hermes/playbooks/workspace.yaml`) — the
   per-file `workspace_excluded` Jinja filter re-applies the same
   exclude semantics inside the `when:` clause as belt-and-suspenders,
   so a bypass at the Python boundary cannot overwrite reserved
   files. The filter mirrors `_is_excluded` exactly.

### Safety properties

The Python enumerator filters before staging:

- **Symlinks** are rejected unconditionally (`os.path.islink`); the
  link target is irrelevant. A hostile drop like
  `workspace/innocent.md → ../auth.json` is dropped with
  `reason=symlink`.
- **Path traversal** is rejected via `Path.resolve(strict=True)` +
  `relative_to(workspace_root_resolved)`.
- **Reserved dotfiles** (`.clawrium-*`) are skipped — these are
  reserved for future control-plane state.

Each enumerated file is staged into a managed
`tempfile.TemporaryDirectory` via `shutil.copy2`. The Ansible playbook
reads the staged copy, NOT the operator's original workspace path —
so a file matching an exclude pattern injected AFTER enumeration is
bounded by the staging-dir lifetime and never reaches the host.

Files matching the secret-pattern globs (`*.key`, `*.pem`, `*.env`,
`*credentials*`, `*secret*`, `*token*`, `*password*`) are floored to
`0600` mode regardless of local permissions, case-insensitive. The
exclude check runs **before** the mode floor, so an excluded file is
never even staged.

### Stop → sync → start for hermes `memories/` and `cron/` overlays

Operators editing hermes `memories/` or `cron/` overlay files should
prefer the stop → sync → start workflow above. The daemon may have
the file open for read at the moment the overlay copy task lands,
and while the copy is atomic at the filesystem layer (`copy` writes
to a tempfile and renames into place), the daemon may have already
read a stale snapshot. Stopping the daemon first removes the race.

For openclaw and zeroclaw, this concern does not apply — their
overlay destinations are disjoint from anything the daemon writes
or reads at runtime.

## Flags reference

| Flag | Effect |
|---|---|
| `--dry-run` | Print intended phases; no host writes. |
| `--diff` | Implies `--dry-run`. Read on-host files via SSH and print a unified diff per file. Mutually exclusive with `--workspace-only`. |
| `--workspace-only` | Push the overlay alone. Skip canonical render / restart / verify. For zeroclaw the bearer rotation still runs. Mutually exclusive with `--diff`. |
| `--no-restart` | Canonical + overlay, skip restart. For zeroclaw the bearer rotation still runs. |
| `--skip-validate` | Bypass the local-state validation phase. |
| `-o json` | NDJSON output (one event per phase and per diff'd file). |
| `--timeout N` | Sync timeout in seconds (default 120). |

The `--workspace` flag (Phase 1 of #760) has been **removed**. Use
`--workspace-only` for the overlay-only push and `--no-restart` for
canonical + overlay without restart.

## See also

- Parent issue [#760](https://github.com/ric03uec/clawrium/issues/760)
  — workspace overlay landing.
- Parent issue [#555](https://github.com/ric03uec/clawrium/issues/555)
  — why deterministic render matters; the silent-wipe regression that
  motivated `--diff` and `doctor`.
- `clawctl agent describe <name>` — high-level agent record summary
  (less diagnostic detail than `doctor`).
- `AGENTS.md` "Gateway Token Lifecycle (zeroclaw)" — why every sync
  rotates the zeroclaw bearer.
- `AGENTS.md` "Workspace Overlay" — engineering invariants for the
  overlay code path.

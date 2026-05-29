# `clawctl agent sync` — flush local control-plane state to the host

`sync` is the drift-to-zero command. It re-renders the canonical
on-host config bundle from clawctl's own stores (providers, channels,
integrations, secrets, hosts) and pushes the result to the host.

The two safety surfaces this page documents:

1. **`clawctl agent doctor <name>`** — local-only diagnostic. Shows
   what `sync` would render *before* it does anything.
2. **`clawctl agent sync --dry-run --diff <name>`** — host-vs-rendered
   unified diff. Reads the current file from the host (no writes).

> **Before you sync, run one of these.** They're the cheap way to find
> out that an attachment is missing, a secret was wiped, or someone
> hand-edited the host file. The actual `sync` overwrites without
> asking.

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

## Flags reference

| Flag | Effect |
|---|---|
| `--dry-run` | Print intended phases; no host writes. |
| `--diff` | Implies `--dry-run`. Read on-host files via SSH and print a unified diff per file. |
| `--workspace` | Skip the restart phase (workspace-only files). |
| `--skip-validate` | Bypass the local-state validation phase. |
| `-o json` | NDJSON output (one event per phase and per diff'd file). |
| `--timeout N` | Sync timeout in seconds (default 120). |

## See also

- Parent issue [#555](https://github.com/ric03uec/clawrium/issues/555)
  — why deterministic render matters; the silent-wipe regression that
  motivated `--diff` and `doctor`.
- `clawctl agent describe <name>` — high-level agent record summary
  (less diagnostic detail than `doctor`).

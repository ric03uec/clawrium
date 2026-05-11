# Memory Model

Clawrium's `memory` CLI inspects and edits the on-disk memory files of running agents. As of issue #68, the dispatcher is **manifest-driven**, so a single CLI surface works across openclaw, hermes, and any future claw type that opts in.

```bash
clm agent <name> memory show
clm agent <name> memory read <file>
clm agent <name> memory write <file> [--content "..."]
clm agent <name> memory edit <file>           # opens $EDITOR
clm agent <name> memory delete <file>
```

---

## How dispatch works

1. **Resolve the claw type.** `clm` looks up the agent in `hosts.json` (or scans candidates by name across all hosts when the user typed an ambiguous identifier) and reads the recorded `type`.
2. **Check the manifest.** `core/memory.py::claw_supports_memory(<type>)` loads `registry/<type>/manifest.yaml` and returns True iff `features.memory` is `true`.
3. **Resolve the workspace path.** Used for display — read from `manifest.workspace.memory_path` and expanded against the agent user's home directory (`~`).
4. **Dispatch the playbook.** The runner invokes `registry/<type>/playbooks/memory_<op>.yaml` (where `<op>` is `info`, `read`, `write`, or `delete`). Each claw ships its own playbooks targeting its own on-disk layout.

If `features.memory` is missing or `false`, the CLI exits non-zero with:

```
memory operations not supported for agent type '<type>'
```

For example, `clm agent <zeroclaw-name> memory show` produces that error today, since the zeroclaw manifest does not declare `features.memory: true`.

---

## Manifest schema

The relevant fields in `registry/<type>/manifest.yaml`:

```yaml
workspace:
  memory_path: "~/.<agent_workspace>/memory"   # required to display the path

features:
  memory: true                                  # required to enable the memory CLI
```

Both fields are optional in the `AgentManifest` TypedDict — legacy claws (e.g. zeroclaw) continue to validate without either. Declaring `features.memory: true` is the opt-in for memory CLI support.

---

## Per-claw on-disk layouts

The CLI surface is uniform, but each claw's on-disk model is different.

### Hermes

```
~/.hermes/memories/
├── MEMORY.md      # Agent notes / scratchpad     (≤ 2200 chars)
└── USER.md        # User profile                  (≤ 1375 chars)
```

Hard limits:

| File | Max chars |
|------|----------:|
| `MEMORY.md` | 2200 |
| `USER.md` | 1375 |

Other filenames are rejected on `memory write` with `"hermes memory accepts only MEMORY.md and USER.md"`. The limits are enforced **client-side in `core/memory.py`** (immediate, no Ansible roundtrip) AND defensively in `memory_write.yaml`. Identity files (`SOUL.md`, `AGENTS.md`) are explicitly excluded from memory by hermes itself and are not editable via the memory CLI.

### OpenClaw

```
~/.openclaw/workspace/memory/
├── SOUL.md          # Identity (top-level)
├── IDENTITY.md      # Identity (top-level)
├── USER.md          # User profile (top-level)
├── TOOLS.md         # Tools (top-level)
└── memory/
    └── YYYY-MM-DD.md  # Daily files (dynamic listing)
```

OpenClaw uses a daily-file model under `memory/`, plus a fixed set of top-level identity/profile files. There are no per-file character caps; the global cap is `MAX_MEMORY_CONTENT_BYTES = 5 MiB` (a transport safety bound, not a per-claw policy).

---

## Atomic-write safety

Both claws can be edited concurrently with the running daemon. Memory writes use a stage-then-rename pattern:

1. Write the new content to a sibling temp file in the same directory (`.<file>.tmp`).
2. `fsync` the temp file.
3. `rename(2)` the temp file over the target.

Because `rename(2)` within a single filesystem is atomic on Linux, the daemon never observes a partial or torn file — it sees either the old content or the new content. This is implemented identically in `registry/hermes/playbooks/memory_write.yaml` and `registry/openclaw/playbooks/memory_write.yaml`.

---

## What's NOT in scope

The following are explicitly deferred for issue #68 and tracked as separate follow-ups (see `.itx/68/00_PLAN.md` → "Out of scope"):

- **Pluggable memory backends.** Hermes upstream supports Holographic, Honcho, Hindsight, Mem0, Byterover, and OpenViking. clm's `memory` CLI only sees the default markdown backend in this iteration.
- **Session / transcript history (`~/.hermes/state.db`).** This is intentionally not exposed via `memory` — hermes treats `state.db` as transcript history, not memory.
- **Identity-file editing for hermes.** clm does not push `SOUL.md` / `AGENTS.md` into `~/.hermes/`; hermes manages them internally. Edit those files directly via SSH if needed.
- **Pluggable filesystem layouts.** The current schema assumes flat markdown files. Future backends (sqlite-backed, encrypted, network-mounted) would require a backend abstraction in `core/memory.py`.

---

## See also

- [Hermes Support Matrix](hermes.md) — full hermes user guide
- [OpenClaw Support Matrix](openclaw.md) — full openclaw user guide
- [Agent Onboarding](../agent-onboarding.md) — how stages interact with manifest

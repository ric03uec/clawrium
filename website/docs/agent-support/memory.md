# Memory Model

Clawrium's `memory` CLI inspects and edits the on-disk memory files of running agents. As of issue #68, the dispatcher is **manifest-driven**, so a single CLI surface works across openclaw, hermes, and any future claw type that opts in.

```bash
clawctl agent memory get --agent <name>                     # list memory files + sizes
clawctl agent memory edit <file> --agent <name>             # opens $EDITOR; atomic-write on save
clawctl agent memory delete <file> --agent <name> --yes     # delete one file
```

Note: in this iteration the CLI exposes `get`, `describe`, `edit`, and `delete`. `read` and `write` are not separate subcommands — use `edit` for both (read = view in `$EDITOR`; write = save in `$EDITOR`). The underlying `read_memory_file` / `write_memory_file` primitives in `core/memory.py` are wired for future expansion.

---

## How dispatch works

1. **Resolve the agent type.** `clawctl` looks up the agent in `hosts.json` (or scans candidates by name across all hosts when the user typed an ambiguous identifier) and reads the recorded `type`.
2. **Check the manifest.** `core/memory.py::claw_supports_memory(<type>)` loads `registry/<type>/manifest.yaml` and returns True iff `features.memory` is `true`.
3. **Resolve the workspace path.** Used for display — read from `manifest.workspace.memory_path` and expanded against the agent user's home directory (`~`).
4. **Dispatch the playbook.** The runner invokes `registry/<type>/playbooks/memory_<op>.yaml` (where `<op>` is `info`, `read`, `write`, or `delete`). Each agent type ships its own playbooks targeting its own on-disk layout.

If `features.memory` is missing or `false`, the CLI exits non-zero with:

```
memory operations not supported for agent type '<type>'
```

For example, `clawctl agent memory get --agent <zeroclaw-name>` produces that error today, since the zeroclaw manifest does not declare `features.memory: true`.

---

## Manifest schema

The relevant fields in `registry/<type>/manifest.yaml`:

```yaml
workspace:
  memory_path: "~/.<agent_workspace>/memory"   # required to display the path

features:
  memory: true                                  # required to enable the memory CLI
```

Both fields are optional in the `AgentManifest` TypedDict — legacy agent types (e.g. zeroclaw) continue to validate without either. Declaring `features.memory: true` is the opt-in for memory CLI support.

---

## Per-agent on-disk layouts

The CLI surface is uniform, but each agent type's on-disk model is different.

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
~/.openclaw/workspace/
├── SOUL.md             # Identity (top-level)
├── IDENTITY.md         # Identity (top-level)
├── USER.md             # User profile (top-level)
├── TOOLS.md            # Tools (top-level)
└── memory/
    └── YYYY-MM-DD.md   # Daily files (dynamic listing)
```

OpenClaw uses a daily-file model under `memory/`, plus a fixed set of top-level identity/profile files at the workspace root. There are no per-file character caps; the global cap is `MAX_MEMORY_CONTENT_BYTES = 5 MiB` (a transport safety bound, not a per-agent policy).

---

## Write safety

The two agent types use different write strategies:

**Hermes** (`registry/hermes/playbooks/memory_write.yaml`) uses a stage-then-rename pattern:

1. Write the new content to a sibling temp file in the same directory (`.<file>.tmp`).
2. `rename(2)` the temp file over the target (single `mv -f` within the same filesystem).

Because `rename(2)` within a single filesystem is visible-atomic on Linux, the hermes daemon never observes a partial or torn file — it sees either the old content or the new content. (Note: the playbook does not currently issue an explicit `fsync` before rename, so the new content is atomic from the daemon's perspective but not guaranteed durable across a hard-crash power loss until the kernel flushes the page cache. This is acceptable for the memory CLI's use case — content lost in a crash window can be re-written.)

**OpenClaw** (`registry/openclaw/playbooks/memory_write.yaml`) uses `ansible.builtin.copy` directly — no staging file, no rename. Concurrent writes between the openclaw daemon and `clawctl agent memory write` are not protected against torn reads. In practice this has not been observed as a problem because openclaw's memory model is daily-files (write contention is rare); a follow-up may align openclaw's write playbook with the hermes stage-then-rename pattern for consistency.

---

## What's NOT in scope

The following are explicitly deferred for issue #68 and tracked as separate follow-ups (see `.itx/68/00_PLAN.md` → "Out of scope"):

- **Pluggable memory backends.** Hermes upstream supports Holographic, Honcho, Hindsight, Mem0, Byterover, and OpenViking. clawctl's `memory` CLI only sees the default markdown backend in this iteration.
- **Session / transcript history (`~/.hermes/state.db`).** This is intentionally not exposed via `memory` — hermes treats `state.db` as transcript history, not memory.
- **Identity-file editing for hermes.** clawctl does not push `SOUL.md` / `AGENTS.md` into `~/.hermes/`; hermes manages them internally. Edit those files directly via SSH if needed.
- **Pluggable filesystem layouts.** The current schema assumes flat markdown files. Future backends (sqlite-backed, encrypted, network-mounted) would require a backend abstraction in `core/memory.py`.

---

## See also

- [Hermes Support Matrix](hermes.md) — full hermes user guide
- [OpenClaw Support Matrix](openclaw.md) — full openclaw user guide
- [Agent Onboarding](/docs/guides/agent-onboarding) — how stages interact with manifest

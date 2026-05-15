# Issue #358 — Subtask C — Execution Notes

Workspace MD files + memory CLI wiring for ZeroClaw.

## Choices

### Path α vs β — chose α (`~/.zeroclaw/workspace`)

The issue comment offered two paths:

- **α** `~/.zeroclaw/workspace` — workspace MD files ARE the memory surface.
  `clm agent memory show` lists the 7 personality files directly. Mirrors
  the openclaw pattern (`~/.openclaw/workspace`).
- **β** `~/.zeroclaw/memories` — a separate dir for arbitrary memory notes,
  workspace files kept out of the memory CLI.

**Chose α.** The user's earlier framing ("the memory I'm referring to is
the SOUL.md and personality MD and other similar files") makes α the
literal-intent reading. β would require renaming Subtask C and re-scoping.

Recorded in `manifest.yaml`:

```yaml
workspace:
  memory_path: "~/.zeroclaw/workspace"
features:
  memory: true
```

### Mirror openclaw playbooks, not hermes

Hermes splits its memory across two dirs (`~/.hermes/` for SOUL.md,
`~/.hermes/memories/` for MEMORY.md + USER.md) because the hermes daemon
treats them differently. Zeroclaw's workspace is a single flat dir like
openclaw's, so the openclaw playbooks (`memory_{read,write,delete,info}.yaml`)
are the right template. Only the target path differs.

### `MEMORY_TOP_LEVEL_FILES` is now per-claw (W8)

`core/memory.py` previously exposed a 4-tuple (openclaw shape). It's now a
mapping keyed by claw type:

```python
MEMORY_TOP_LEVEL_FILES = {
    "openclaw": (...4 files...),
    "hermes":   (...3 files...),
    "zeroclaw": (...7 files, no BOOTSTRAP.md...),
}
```

The constant is only consumed by tests today (verified via grep). The
authoritative file list at runtime is still the one each claw's
`memory_info.yaml` iterates — the Python mapping mirrors it for tests and
any future cross-claw inspection.

`BOOTSTRAP.md` is intentionally omitted from the zeroclaw set: the runtime
generates it on first boot and self-deletes after use. Surfacing it in
`clm agent memory show` would confuse operators.

### Workspace template render uses `force: no`

On first `clm agent configure`, the 7 templates seed `~/.zeroclaw/workspace/`.
On every subsequent run, `force: no` means Ansible only writes a template
if the destination is missing — user edits to `SOUL.md`, `USER.md`, etc.
are never clobbered.

This is the same trade-off `config.toml` makes in reverse: that file is
managed (force defaults to yes) because its provider/gateway keys must
match what `clm` thinks it configured. Workspace files are user-owned.

### `[personality]` block

Rendered with `name`, `timezone`, `communication_style` and sensible
defaults (`zeroclaw` / `UTC` / `direct, concise`). Operators can override
via `config.personality.{name,timezone,communication_style}` passed
through from clm. Deeper personality content lives in `SOUL.md` etc.

All values pass through the existing `toml_escape` macro — verified by a
new TOML-injection test in `test_configure_zeroclaw.py`.

## Files touched

```
src/clawrium/core/memory.py                                     (MEMORY_TOP_LEVEL_FILES → mapping)
src/clawrium/platform/registry/zeroclaw/manifest.yaml           (features.memory, workspace.memory_path)
src/clawrium/platform/registry/zeroclaw/templates/config.toml.j2 (+[personality] block)
src/clawrium/platform/registry/zeroclaw/templates/workspace/*.md.j2 (7 new files)
src/clawrium/platform/registry/zeroclaw/playbooks/configure.yaml (render workspace files)
src/clawrium/platform/registry/zeroclaw/playbooks/memory_{read,write,delete,info}.yaml (4 new)
tests/test_core_memory.py                                       (per-claw constant tests)
tests/test_configure_zeroclaw.py                                (personality block tests)
tests/test_registry_zeroclaw.py                                 (memory feature + playbook tests)
```

## Exit Criteria

- [x] 7 workspace templates render on configure (with `force: no`).
- [x] `features.memory: true` and `workspace.memory_path` in manifest.
- [x] `clm agent memory show <n>` → routes via existing CLI to zeroclaw
      `memory_info.yaml`; surfaces all 7 personality files.
- [x] `clm agent memory edit <n> SOUL.md` → routes through existing
      `read_memory_file` / `write_memory_file`.
- [x] `clm agent memory delete <n> --file SOUL.md` → routes through
      existing `delete_memory_files`.
- [x] `MEMORY_TOP_LEVEL_FILES["zeroclaw"]` covers 7 files; excludes
      `BOOTSTRAP.md`.
- [x] `[personality]` block rendered with name/timezone/style defaults +
      TOML-escape coverage.
- [ ] `make test` passes (run in next task).
- [ ] ATX rating > 3/5 (run in final task).

## Out of Scope

Daemon restart semantics on workspace changes — the runtime watches its
own workspace dir; clm doesn't need a notify handler for the template
renders. Integrations, hardware, tunnel, encrypted secrets, Composio,
docs all deferred to follow-up issues per the #112 plan.

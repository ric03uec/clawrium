# Execution Log — #755

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-06-24T19:55:00Z
**Model**: claude-opus-4-7

```prompt
755

Read the issue body first via gh issue view 755. Summary of the bug:
clawctl agent sync on openclaw does NOT install the
@openclaw/brave-plugin. That plugin install lives only in
playbooks/openclaw/configure.yaml:131 (Linux) and
configure_macos.yaml:153 (macOS). sync_agent_canonical in
src/clawrium/core/lifecycle_canonical.py:799-1167 does brave-version
preflight, writes diffs, restarts unit, and (zeroclaw only) re-pairs
— but never installs the plugin. Attaching a brave integration only
mutates inputs.integrations (used for preflight + env render); there
is no host-side action to materialize the plugin.

[Full prompt in conversation log.]
```

**Output**: PR opened against main, closes #755. Plugin install
lifted from `configure.yaml` + `configure_macos.yaml` into
`lifecycle_canonical._openclaw_install_plugins`. Driven by manifest
`plugins:` block (generalizes beyond brave). Idempotent via
per-version sentinel `.openclaw/.<plugin>-plugin-installed.<version>`.
Install via `openclaw plugins install --force --pin <pkg>@<ver>` so
the daemon's `plugins list` actually discovers the plugin (the
pre-#755 `npm install --prefix ~/.openclaw` approach was discovered
during UAT to write files the daemon never scanned). Wired between
brave preflight and `_restart_unit` — install failure short-circuits
before restart. Extravars `openclaw_brave_plugin_{package,version}`
stripped from `lifecycle.py`.

## UAT (esper-mac-oc, darwin/arm64)

1. Attached `wolf-brave` integration to esper-mac-oc.
2. `uv run clawctl agent sync esper-mac-oc` from this worktree:
   - First run revealed `sudo -n -u` was preserving SSH user's HOME
     so npm tried to write `/Users/xclm/.npm` (EACCES). Fixed with
     `sudo -n -H -u`.
   - Second run revealed `npm install --prefix ~/.openclaw` writes
     files but openclaw's `plugins list` doesn't scan that dir.
     Switched to `openclaw plugins install --force --pin <spec>`.
   - Third run: success. Plugin installed at
     `/Users/esper-mac-oc/.openclaw/npm/projects/openclaw-brave-plugin-<hash>/`,
     `openclaw plugins list --json` reports `brave@2026.6.9` with
     `status: loaded`, `webSearchProviders: ['brave']`.
3. Sentinel: `/Users/esper-mac-oc/.openclaw/.brave-plugin-installed.2026.6.9`
   present with mode 0600.
4. Idempotent: second sync emitted "already installed (sentinel
   present)" and skipped the install command.
5. Detach + sync: plugin remains (uninstall out of scope for #755).

## ATX

| Iter | Rating | Blockers | Cost | Time |
|---|---|---|---|---|
| 1 | 3.5/5 | B1, B2 | $4.98 | 9m 9s |
| 2 | 4/5 | None | $2.90 | 12m 52s |

Iter-1 B1 (vacuous T5) fixed by rewriting `test_t5_install_runs_before_restart_via_sync`
to drive `sync_agent_canonical` with stubbed IO + spy callbacks
asserting ordering. Iter-1 B2 (missing stamp-failure coverage) fixed
by `test_stamp_failure_after_successful_install_raises`.

Iter-2 W1 (paramiko stdout buffer deadlock on verbose npm output)
addressed by draining `i_out.read() + i_err.read()` before
`recv_exit_status()` — matches `_run_openclaw_version_probe`'s
established pattern.

Iter-2 W2, W3, S1-S5 left as follow-ups (hygiene improvements;
none cause production impact).

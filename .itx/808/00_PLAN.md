# Plan — #808: macOS support for `clawctl agent shell`

## Overview

Follow the dispatcher-only OS-fork convention already established for workspace overlay and lifecycle. Add `shell_macos.yaml` as a parallel playbook, route via a new `resolve_shell_playbook(os_family)` helper in `core/playbook_resolver.py`, and replace the darwin short-circuit at `agent_shell.py:232` with a runtime resolver call. Make the rc-file prepend OS-aware (`.bash_profile` first on macOS, then `.bashrc`).

No `if ansible_os_family == "Darwin"` branches inside `shell.yaml` — the dispatcher is the single source of truth (`core/playbook_resolver.py`).

## Files

### New

| Path | Purpose |
|---|---|
| `src/clawrium/platform/shell/shell_macos.yaml` | Parallel playbook — same task shape, BSD-friendly timeout |
| `tests/platform/test_shell_playbook_macos.py` | Static YAML invariants, mirroring `test_shell_playbook.py` |

### Modified

| Path | Change |
|---|---|
| `src/clawrium/core/playbook_resolver.py` | Add `resolve_shell_playbook(os_family) -> Path` |
| `src/clawrium/core/agent_shell.py` | Drop module-level `_PLAYBOOK`; resolve per-call; delete darwin preflight at L229–239; OS-aware rc-file prepend |
| `tests/core/test_agent_shell.py` | Replace `test_K20_macos_host_preflight_error` with `test_K20_macos_host_uses_macos_playbook`; add darwin rc-prepend test |
| `tests/core/test_playbook_resolver.py` | Add unit tests for `resolve_shell_playbook` (linux/darwin/unknown) |
| `CHANGELOG.md` | `### Added` entry under `[Unreleased]` |

## Steps

### Step 1 — Resolver helper

Add to `src/clawrium/core/playbook_resolver.py`:

```python
def resolve_shell_playbook(os_family: str) -> Path:
    """Return the path to the `clawctl agent shell` playbook for this OS family."""
    suffix = _suffix_for(os_family)
    path = _PLATFORM_ROOT / "shell" / f"shell{suffix}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"shell playbook for os_family={os_family!r} not found at {path}. "
            f"This OS family is not yet supported by this clawrium build."
        )
    return path
```

### Step 2 — `shell_macos.yaml`

Mirror `shell.yaml` task-for-task, with the following differences only:

- **Timeout discovery** (new pre-task, run as agent user):

  ```yaml
  - name: Discover gtimeout (coreutils)
    ansible.builtin.shell: |
      PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin which gtimeout || true
    args:
      executable: /bin/bash
    become: true
    become_user: "{{ agent_name }}"
    register: gtimeout_which
    changed_when: false
    failed_when: false
  ```

- **Run task** branches by whether `gtimeout` was found:
  - Found → `argv: [<resolved_gtimeout>, --kill-after=5, "{{ shell_timeout | int }}", /bin/bash, -lc, "{{ cmd_b64 | b64decode }}"]`
  - Missing → `argv: [/bin/bash, -lc, "{{ cmd_b64 | b64decode }}"]`. The `effective + _RUNNER_GRACE_S` runner-level timeout in `agent_shell.py` is the kill backstop; runner status `timeout` already maps to `rc=124` at L319–320, so the user-facing contract is unchanged. Cost: +25s kill window vs the gtimeout path.
- **Same** `become: true` / `become_user: "{{ agent_name }}"` / `no_log: true` / `failed_when: false` / `changed_when: false` / `SHELL_STDOUT=`, `SHELL_STDERR=`, `SHELL_RC=` emit tasks.
- **Same** defense-in-depth fail tasks for `agent_name`, `cmd_b64`, `shell_timeout` (#761 iter-3 W3 + B2).
- **No** `when: ansible_os_family == "Darwin"` guards — `gather_facts: false`, same comment as `exec_macos.yaml`.

### Step 3 — `agent_shell.py` dispatcher

- Delete L229–239 darwin short-circuit.
- Delete `_PLAYBOOK = Path(...)` module constant.
- After `host = get_host(hostname)` resolves, branch playbook per-call:

  ```python
  os_family = (host.get("os_family") or "linux").lower()
  try:
      playbook = playbook_resolver.resolve_shell_playbook(os_family)
  except (FileNotFoundError, ValueError) as e:
      return "", str(e), 255
  ```

- Replace the rc-file prepend at L268 with OS-aware logic:

  ```python
  if os_family == "darwin":
      rc_prepend = (
          '[ -f "$HOME/.bash_profile" ] && . "$HOME/.bash_profile";'
          ' [ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc";'
      )
  else:
      rc_prepend = '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc";'
  cmd_str = f"{rc_prepend} {user_cmd}"
  ```

- Pass `playbook=str(playbook)` to `ansible_runner.run` instead of the module constant.

### Step 4 — Tests

**`tests/platform/test_shell_playbook_macos.py`** — mirror every Linux playbook invariant:

- P1 `no_log: true` on each run-command task
- P2 `become_user == "{{ agent_name }}"`
- P3 each run task argv contains `/bin/bash -lc`
- P4 gtimeout-present run task uses the discovered `gtimeout` path as argv0
- W3 `cmd_b64` defined-and-non-empty guard task present
- B2 `shell_timeout >= 1` guard task present
- Both run branches emit `SHELL_STDOUT=`/`SHELL_STDERR=`/`SHELL_RC=` debug events

**`tests/core/test_agent_shell.py`**:

- Replace K20 with `test_K20_macos_host_uses_macos_playbook`:

  ```python
  captured = {}
  def fake_run(**kw):
      captured.update(kw)
      return _RUNNER_SUCCESS  # fixture mirroring the linux test
  monkeypatch get_host → os_family=darwin
  monkeypatch ansible_runner.run → fake_run
  agent_shell.run_agent_shell("wolf-i", "wolf-i", ["ls"])
  assert captured["playbook"].endswith("shell_macos.yaml")
  ```

- Add `test_darwin_rc_prepend_sources_bash_profile`: capture `inventory` extravars, base64-decode `cmd_b64`, assert it starts with the `.bash_profile`-then-`.bashrc` prepend on darwin.
- Add `test_linux_rc_prepend_unchanged`: same shape, asserts the linux prepend is unchanged.

**`tests/core/test_playbook_resolver.py`**:

- `test_resolve_shell_playbook_linux_returns_shell_yaml`
- `test_resolve_shell_playbook_darwin_returns_shell_macos_yaml`
- `test_resolve_shell_playbook_unknown_os_raises`

### Step 5 — CHANGELOG

Under `[Unreleased]` → `### Added`:

```
- `clawctl agent shell <name> -- <cmd>` now works against macOS hosts (#808).
  Discovers `gtimeout` (coreutils) when present; without it the
  ansible-runner outer timeout is the kill backstop.
```

### Step 6 — Real-host verification on `mac-test`

From the local clawrium worktree (`uv run clawctl …`):

| # | Command | Expected |
|---|---|---|
| 1 | `uv run clawctl agent shell <mac-agent> -- ls -la ~/` | listing of `/Users/<agent_name>`, rc=0 |
| 2 | `uv run clawctl agent shell <mac-agent> -- 'echo $HOME'` | `/Users/<agent_name>`, rc=0 |
| 3 | `uv run clawctl agent shell <mac-agent> -- 'echo $PATH'` | shims if `.bash_profile` exports them |
| 4 | `uv run clawctl agent shell <mac-agent> --timeout 2 -- sleep 5` | rc=124, stderr non-empty |
| 5 | `uv run clawctl agent shell <mac-agent> -- 'echo {{ lookup("env","HOME") }}'` | literal echo, no Jinja expansion |
| 6 | `uv run clawctl agent shell <mac-agent> -- false` | rc=1 |

## Test Strategy

- `make test` green (full suite)
- `make lint` green
- Real-host smoke list above on `mac-test` (100.120.88.97, darwin/arm64)
- No CI hardware for macOS — playbook tests use static YAML inspection; runtime tests use monkeypatched `ansible_runner`. Same envelope as the workspace-overlay macOS work (#770/#771/#772).

## Risks

- **`gtimeout` not installed** → wider kill window (+25s). Documented; suggest `brew install coreutils` in `--help`.
- **zsh-default operators** → `bash -lc` does not source `~/.zshrc`. Matches the Linux contract; documented as out of scope for v1.
- **Non-UTF-8 child output** → still lossy (Ansible decodes with `errors='replace'` before we see it). Matches Linux contract.

## Out of Scope

- zsh login-shell support
- Auto-installing coreutils on the host
- launchctl-based binary discovery

## Subtasks

None — single concern; 2 new files + 4 modified files.

---

<details>
<summary>Prompt Log</summary>

## Plan

**Stage**: plan
**Skill**: /itx-plan-create
**Timestamp**: 2026-06-24T15:50:21Z
**Model**: claude-opus-4-7

```prompt
808 in a worktree. dont commit anything. just show me the plan
```

**Output**: `.itx/808/00_PLAN.md` — high-level implementation plan for adding macOS support to `clawctl agent shell`, following the dispatcher-only OS-fork convention. No commits, no GitHub comment, no label change.

</details>

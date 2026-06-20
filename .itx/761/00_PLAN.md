# Issue #761 — `clawctl agent shell <name> -- <cmd>`

Add a new `clawctl agent` verb that runs an arbitrary command on the
agent's host as the agent's unix user, in a full login bash shell.

This is a **new self-contained flow**. It does NOT reuse the existing
`agent_exec.py` / per-type `exec.yaml` plumbing — keeping it independent
lets `shell` evolve without contaminating exec's ATX-hardened code path.

## 1. User-Centric Outputs

### Command surface

```
clawctl agent shell <name> [-- <cmd> [args...]] [--timeout SECONDS]
```

- `<name>` — agent name (as shown by `clawctl agent get`).
- Everything after `--` is passed verbatim to a **login bash shell** on
  the host (`/bin/bash -lc '<joined cmd>'`), so the agent user's
  `~/.bashrc`, `~/.profile`, PATH entries, `nvm`/`pyenv`/`uv` shims,
  virtualenv activations, etc. are all loaded before the command runs.
- `--timeout SECONDS` (default 120, `0` means "no client-side timeout").
  **A hard 30-minute (1800s) cap is applied unconditionally regardless
  of what the user passes** — values above 1800 are clamped to 1800,
  and `--timeout 0` resolves to 1800. This cap is hardcoded.
- Non-interactive only. No TTY allocated. Suitable for scripts/CI;
  documented in `--help` that interactive prompts will hang and TTY-only
  UIs (colors, progress bars) will not render.
- Exit code from the remote command propagates to local exit code.

### Example sessions

```bash
# Inspect the agent user's env
$ clawctl agent shell wolf-i -- 'env | grep -i path'
PATH=/home/wolf-i/.local/bin:/usr/local/bin:/usr/bin:/bin
PYENV_ROOT=/home/wolf-i/.pyenv
...

# Read a config file (tilde + $HOME work because login shell)
$ clawctl agent shell wolf-i -- 'cat ~/.hermes/config.yaml'
providers:
  - id: primary
    ...

# Run a build tool that needs the agent user's PATH shims
$ clawctl agent shell wolf-i -- 'make test'
pytest ...
========= 142 passed in 8.41s =========

# Long-running command with custom timeout (capped at 1800s)
$ clawctl agent shell wolf-i --timeout 600 -- 'pip install -r requirements.txt'
...

# Quick one-liners — pipes / redirects / && / || all work (login shell)
$ clawctl agent shell wolf-i -- 'ls -la ~/.hermes | head -5'
```

### Error UX

```bash
$ clawctl agent shell wolf-i
Error: no command provided
Hint:  clawctl agent shell <name> -- <cmd> [args...]

$ clawctl agent shell does-not-exist -- ls
Error: agent 'does-not-exist' not found
Hint:  clawctl agent get  to list agents

$ clawctl agent shell wolf-i --timeout 5 -- 'sleep 30'
Error: remote command timed out after 5s
# exit 124  (matches GNU `timeout`)

$ clawctl agent shell wolf-i -- 'exit 7'
# exits 7

$ clawctl agent shell wolf-i -- 'this-bin-does-not-exist'
/bin/bash: line 1: this-bin-does-not-exist: command not found
# exits 127  (shell's standard not-found code)
```

### `--help` excerpt

```
Usage: clawctl agent shell [OPTIONS] NAME [-- CMD...]

  Run an arbitrary command on the host in the agent user's login shell.

  The command runs as the agent's unix user with a full login bash
  shell (~/.bashrc, PATH shims, virtualenvs, etc. loaded), so tilde
  expansion, $HOME, pipes, redirects, and && / || all work as in
  an interactive ssh session.

  NON-INTERACTIVE ONLY. No TTY is allocated. Commands that prompt
  for input will hang; TTY-only UIs (colors, progress bars) will
  not render. For interactive sessions, ssh to the host directly.

  Examples:
    clawctl agent shell my-agent -- 'ls -la ~/'
    clawctl agent shell my-agent -- 'cat ~/.hermes/config.yaml'
    clawctl agent shell my-agent --timeout 600 -- 'make test'

Arguments:
  NAME              Agent name (from `clawctl agent get`).  [required]

Options:
  --timeout INT     Max seconds before the remote command is killed.
                    0 means "no client-side timeout"; the hard 30-min
                    cap still applies. [default: 120]
  --help            Show this help and exit. To forward --help to the
                    remote command, use:
                      clawctl agent shell NAME -- '<cmd> --help'
```

### How this differs from `exec` (one-line in docs)

| Verb | Runs on host | Use it when |
|---|---|---|
| `clawctl agent exec <name> -- <args>` | The agent's native binary (`hermes`, `openclaw`, …) | You want to drive the agent's own CLI. |
| `clawctl agent shell <name> -- <cmd>` | A login bash shell as the agent user | You want host-level ops: `ls`, `cat`, `make`, `pip`, `git`, etc. |

### CHANGELOG entry (under `### Added`)

> `clawctl agent shell <name> -- <cmd>` runs an arbitrary command on
> the host as the agent user in a full login bash shell — tilde
> expansion, PATH shims, virtualenvs, pipes, and redirects all work.
> Non-interactive; `--timeout` controls the kill window (default 120s,
> hard-capped at 1800s). Linux hosts only in v1 (macOS tracked in
> #<new-subissue>). Closes #761.

## 2. Technical Details

### Design constraints (locked)

- **No reuse of `agent_exec.py` plumbing.** New, self-contained flow.
- **Duplicate** rather than extract shared helpers — separate workflow.
- **Login shell semantics**: `/bin/bash -lc '<joined cmd>'`. Hardcoded
  to `bash` (not the agent user's `getent passwd` shell) for
  predictability.
- **Ansible-runner over SSH** as the backbone. SSH keys come from the
  existing `clawrium.core.keys` store keyed by host
  (`get_host_private_key`). Same key the rest of the fleet uses —
  zero new key surface.
- **Linux only in v1.** Subissue filed for macOS; #761 stays open
  until the subissue ships? **No — close #761 when v1 lands; the
  macOS subissue is independent and tracks its own scope.**
- **Non-interactive, one-off only.** No PTY, no streaming.
- **`--timeout 0` = no client-side timeout; hard 30-min cap always
  applied.** Values > 1800 clamp to 1800. Implemented as a single
  `effective_timeout = 1800 if user_timeout in (0, None) else min(user_timeout, 1800)`
  before extravars build.
- **stdout/stderr sanitization**: pipe through
  `clawrium.cli.output._sanitize.sanitize_passthrough` before writing
  to the local terminal, same as `exec`.

### Files to create

```
src/clawrium/cli/clawctl/agent/shell.py      # Typer command
src/clawrium/core/agent_shell.py             # run_agent_shell() — full new impl, no shared helpers
src/clawrium/platform/shell/__init__.py      # marker
src/clawrium/platform/shell/shell.yaml       # single playbook (not per-agent-type)
tests/cli/clawctl/agent/test_shell.py        # CLI-layer tests
tests/core/test_agent_shell.py               # core-layer tests
```

### Files to modify

- `src/clawrium/cli/clawctl/agent/__init__.py` — import
  `shell as _shell`; register the verb (mirroring `exec` registration,
  with its own `SHELL_CONTEXT_SETTINGS`). Add `shell` to the docstring's
  verb list.
- `CHANGELOG.md` → `## [Unreleased] → ### Added` — entry shown above.
- Clawctl skill / `.claude/skills/clawctl/SKILL.md` (or wherever the
  verb table lives) — add `shell` row with the one-line comparison to
  `exec`.

### Core implementation sketch (`agent_shell.py`)

Self-contained — does **not** import from `agent_exec.py`.

Function signature:

```python
def run_agent_shell(
    hostname: str,
    agent_name: str,
    cmd_argv: list[str],
    timeout: int = 120,
) -> tuple[str, str, int]:
    """Returns (stdout, stderr, rc)."""
```

Behavior:

1. Validate `agent_name` against `^[a-z][a-z0-9_-]{0,31}$`
   (defense-in-depth before extravars interpolation).
2. Validate `cmd_argv` is a non-empty list.
3. Resolve `effective_timeout`:
   `1800 if timeout in (0, None) else min(int(timeout), 1800)`.
4. `joined = shlex.join(cmd_argv)` — safe shell-quoted single string.
5. `host = get_host(hostname)`; resolve SSH key via
   `core_keys.get_host_private_key(host["key_id"] or hostname)`.
6. Build inventory exactly the same shape `agent_exec.py` does (one
   screen of code — duplicate rather than share).
7. Build extravars:
   `{"agent_name": agent_name, "cmd_str": joined, "shell_timeout": effective_timeout}`.
8. Create a per-call `private_data_dir` under `get_config_dir()/logs/`
   with timestamp + 8-char uuid suffix (collision-safe); `chmod 0o700`.
9. `ansible_runner.run(... timeout=effective_timeout + 30 ...)`. The
   `+30` gives the playbook time to clean up after the inner
   `timeout(1)` kills the command, so the runner-level timeout is
   never the one that fires under normal operation.
10. Parse three debug events: `SHELL_STDOUT=`, `SHELL_STDERR=`,
    `SHELL_RC=` (base64-tagged — distinct prefix from `EXEC_*` so
    a mis-shared parser cannot silently cross paths).
11. Map inner `timeout(1)` exit code `124` to a friendly "remote
    command timed out after Ns" message; propagate rc=124.
12. Clean up `private_data_dir` in `finally`.

Failure modes:

- Unknown / missing host → `("", err, 255)`.
- SSH key not found → `("", err, 255)`.
- Playbook missing → `("", err, 255)`.
- Runner exception → `("", f"ansible-runner error: {e}", 255)`.
- Runner timeout → `("", "remote command timed out after Ns", 124)`.
- Remote rc missing → propagate stdout + stderr, rc=255.
- Remote command nonzero rc → propagated verbatim.

### Playbook (`shell.yaml`) sketch

```yaml
- hosts: all
  gather_facts: false
  tasks:
    - name: Validate agent_name (defense-in-depth)
      ansible.builtin.fail:
        msg: "Invalid agent_name"
      when: agent_name is not match('^[a-z][a-z0-9_-]{0,31}$')

    - name: Run command in login shell as agent user
      # Use the `timeout` coreutil to enforce the kill window so the
      # remote process is reaped even if ansible-runner is killed.
      # `bash -lc` gives the full login-shell env.
      ansible.builtin.command:
        argv:
          - /usr/bin/timeout
          - "--kill-after=5"
          - "{{ shell_timeout }}"
          - /bin/bash
          - -lc
          - "{{ cmd_str }}"
      become: true
      become_user: "{{ agent_name }}"
      register: shell_result
      failed_when: false
      changed_when: false
      no_log: true

    - name: Emit stdout
      ansible.builtin.debug:
        msg: "SHELL_STDOUT={{ shell_result.stdout | default('') | b64encode }}"

    - name: Emit stderr
      ansible.builtin.debug:
        msg: "SHELL_STDERR={{ shell_result.stderr | default('') | b64encode }}"

    - name: Emit rc
      ansible.builtin.debug:
        msg: "SHELL_RC={{ shell_result.rc | default(255) }}"
```

Notes:

- `/usr/bin/timeout` from coreutils is universally present on the
  Linux distros we ship to. If absent on a host, the playbook fails
  loudly — acceptable v1 trade-off; macOS subissue revisits.
- `--kill-after=5` follows `SIGTERM` with `SIGKILL` 5s later if the
  process ignores TERM.
- `no_log: true` so `cmd_str` (may contain secrets in argv) never
  lands in artifacts.
- `become_user: agent_name` — same trust boundary as `exec`. No root.

### CLI implementation sketch (`shell.py`)

Mirrors `exec.py`'s shape with its own context-settings + handler:

- `SHELL_CONTEXT_SETTINGS = {"ignore_unknown_options": True, "allow_extra_args": True}`
- `--timeout INT` is a Typer option (default 120). Parsed before `--`.
- Empty `ctx.args` → friendly error (exit 2) suggesting the usage line.
- Resolves the agent via `safe_resolve_agent(name)` — only to get
  hostname + agent unix name. **Does not consult `SUPPORTED_CLAW_TYPES`**;
  any agent record is shellable since we're not delegating to a
  type-specific binary.
- Calls `run_agent_shell(...)`, writes stdout/stderr (each sanitized
  with `sanitize_passthrough`), exits with rc.

### Tests

**`tests/cli/clawctl/agent/test_shell.py`** (Typer `CliRunner`):

- no-args error (exit 2)
- `--` passthrough wiring
- `--timeout` parsed and forwarded to `run_agent_shell`
- `--timeout 0` resolves to 1800 in the call
- `--timeout 9999` clamps to 1800 in the call
- stdout/stderr passthrough wiring (uses `sanitize_passthrough`)
- exit-code propagation (including 124 timeout, 127 not-found)
- `--help` shows clawctl help (forwarding `--help` requires it inside
  the quoted cmd)

**`tests/core/test_agent_shell.py`** (mock `ansible_runner.run`):

- event parsing for `SHELL_STDOUT` / `SHELL_STDERR` / `SHELL_RC` only
  — assert `EXEC_*` events are NOT consumed
- base64 decode failures → empty stdout/stderr, rc preserved
- missing rc → rc=255 fallback
- runner timeout status → friendly message + rc 124
- unreachable host
- missing SSH key
- missing host record
- `_AGENT_NAME_RE` rejection
- artifact cleanup on success AND failure
- `shlex.join` correctness for argv with spaces, single + double quotes,
  `$VAR`, backticks, `&&`/`|`
- timeout clamp: `0 → 1800`, `9999 → 1800`, `60 → 60`

No shared fixtures with `test_agent_exec.py` — keep flows independent
end-to-end.

### Security recap

- **No new auth surface.** Same SSH key Ansible uses for
  `configure`/`sync`/`exec`. Key already stored under
  `clawrium.core.keys`; no new lookup mechanism.
- **No root.** `become_user: agent_name`.
- **`no_log: true`** so secrets in argv don't leak to Ansible artifacts.
- **`timeout(1)` wrapper** + hard 30-min ceiling prevent runaway
  processes even if ansible-runner crashes.
- **Defense-in-depth regex** on `agent_name` before extravars
  interpolation.
- **`shlex.join`** on the client side so we never construct shell
  strings with `' '.join` or f-string interpolation of user input.

### macOS subissue (to file at execution time)

Title: **[Parent #761] Add macOS support for `clawctl agent shell`**

Body sketch:

> `clawctl agent shell` shipped in #761 supports Linux hosts only.
> macOS needs:
>
> - Default shell is `zsh` (or `bash` for older macOS); login-shell
>   flag is the same (`-l`) but startup files differ (`~/.zprofile`,
>   `~/.zshrc`).
> - Home directory is `/Users/<user>`, not `/home/<user>` (only
>   relevant if the playbook later assumes a path).
> - `/usr/bin/timeout` is **not** present on stock macOS. Need either
>   `gtimeout` (coreutils via brew) or a pure-shell timeout shim.
>
> Likely shape: detect host OS once (cached on the host record) and
> pick `shell.yaml` vs `shell_macos.yaml` via the dispatcher pattern
> documented in CLAUDE memory `dispatcher-only OS fork`.

Labels: `enhancement`. Linked as sub-issue of #761. Stays open after
v1 ships.

### Steps (execution order, for `/itx:execute`)

1. Create the macOS subissue and link it as a sub-issue of #761.
2. Write `shell.yaml` playbook.
3. Write `core/agent_shell.py` (self-contained, no helper imports).
4. Write `cli/clawctl/agent/shell.py`.
5. Register `shell` verb in `cli/clawctl/agent/__init__.py`.
6. Tests: core then CLI.
7. `make lint && make test`.
8. Real-host smoke against `wolf-i` (or whichever agent you point at)
   — paste the canonical examples + a timeout case into the PR body.
9. Update `CHANGELOG.md` + clawctl skill docs.
10. Request ATX review via `mcp__atx__request_review` (repo policy:
    `mcp.review_enabled = true`).
11. Stop. Wait for explicit ask before committing or opening the
    implementation PR.

## Prompt Log

### Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-20T00:00:00Z
**Model**: claude-opus-4-7

```prompt
761 plan only no file creation
```

Follow-up directives (same stage, additional turns):

```prompt
dont use any exising plubmginn cretew a new flow for this.
1. full shell i need all the evns to be loaded before eeucing the
command. the user must get the ful cli experience for the agent.
im assuming this can still be non interactive for script runners.
it should support one off command eecution for those consumrs
2. duplicate. extract. this is a new separate workflow
3. no macos support fo rnow, add a subissue for mac support and
keep it open
4. yes, add a timeout. the backbone is ansible runner over ssh.
use keys to the sytem that're already stored in clawrium config.
update plan. show me the user cneterig outputs and THEN technical
details/file changes.
```

```prompt
bash is fine for now 2. yes, timeout 0 is no timeout but lways cap
it to 30 mins no matter wat. thi sis harcoded. sanitze pasthrough.
update plan write it in a plan file. commit and send a pr
```

**Output**: `.itx/761/00_PLAN.md` — high-level implementation plan
for `clawctl agent shell` v1 (Linux-only login-bash command runner
via ansible-runner over SSH).

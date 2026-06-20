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
tests/platform/test_shell_playbook.py        # YAML-parse invariants on shell.yaml
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
   (defense-in-depth before extravars interpolation — the CLI also
   validates the same regex to fail fast, but core re-validates so
   non-CLI callers cannot bypass).
2. Validate `cmd_argv` is a non-empty list.
3. Resolve `effective_timeout` (all clamping lives in CORE, not CLI;
   CLI passes the raw user value through unmodified):
   - `None`, `0`, negative → `1800` (no client-side timeout, hard cap)
   - positive → `min(int(timeout), 1800)`
   - matrix asserted in test K16
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
  A Typer **callback** rejects negative values with exit 2 + message
  `"--timeout must be >= 0 (use 0 for 'no client timeout')"` — fail
  fast before any agent resolution or SSH work (test C6).
- Empty `ctx.args` → friendly error (exit 2) suggesting the usage line
  (test C1); `run_agent_shell` is NOT called.
- Validate `name` against `_AGENT_NAME_RE` at the CLI seam before
  agent resolution (test C13) — fail fast even though core re-validates.
  Duplicate-by-design: belt-and-braces against a tampered hosts.json
  alias or a non-CLI caller bypass.
- Resolves the agent via `safe_resolve_agent(name)`. If it returns
  `None` → exit nonzero + `"agent '<name>' not found"` on stderr;
  `run_agent_shell` NOT called (test C12). **Does not consult
  `SUPPORTED_CLAW_TYPES`** — any agent record is shellable since
  we're not delegating to a type-specific binary.
- Calls `run_agent_shell(hostname=..., agent_name=..., cmd_argv=...,
  timeout=<raw user value>)` — CLI does NOT clamp; clamping is a
  core invariant (tests C4, C5, K16).
- Writes stdout/stderr each sanitized with `sanitize_passthrough`;
  exits with the returned rc.

### Tests

Test bullets are stated as **exact-args assertions**, not weak
`.assert_called()` shapes. The ATX iter-1 review correctly flagged that
"wiring works" prose can pass even when the timeout is silently
zeroed — so every CLI bullet below names the exact kwargs the mock
must see.

#### Host-record fixture (used by both CLI and core tests)

Minimum required keys (anything less raises `TypeError` /
`KeyError` at runtime — exhaustively listed here so test files can
copy this dict verbatim):

```python
HOST_FIXTURE = {
    "hostname": "wolf-i",       # required by inventory build
    "user": "xclm",             # ansible_user
    "port": 22,                 # ansible_port
    "key_id": "wolf-i",         # passed to core_keys.get_host_private_key
    "alias": "wolf-i",          # used in log_dir name (must pass _LOG_DIR_SAFE_RE)
}
```

Tests must NOT share fixtures with `test_agent_exec.py` — each flow
declares its own to keep the duplication intentional.

#### `tests/cli/clawctl/agent/test_shell.py` (Typer `CliRunner`)

| # | Case | Exact assertion |
|---|------|-----------------|
| C1 | no-args error | `result.exit_code == 2` AND `"no command provided" in result.stderr` AND `run_agent_shell` NOT called |
| C2 | basic passthrough | `run_agent_shell.assert_called_once_with(hostname="wolf-i", agent_name="wolf-i", cmd_argv=["ls","-la"], timeout=120)` |
| C3 | `--timeout 600 -- make test` | mock called with `timeout=600` (exact kwarg, not "any int") |
| C4 | `--timeout 0` | mock called with `timeout=0` — clamp lives in core, NOT CLI; CLI passes the raw user value through unmodified |
| C5 | `--timeout 9999` | mock called with `timeout=9999` — same reason as C4 |
| C6 | `--timeout -1` | `result.exit_code == 2` AND `"--timeout must be >= 0" in result.stderr` AND `run_agent_shell` NOT called (Typer callback rejects before core) |
| C7 | stdout passthrough | mock returns `("hello\n","",0)` → `result.stdout == "hello\n"` AND `sanitize_passthrough` called once with `"hello\n"` (assert via `patch("clawrium.cli.clawctl.agent.shell.sanitize_passthrough")`) |
| C8 | stderr passthrough | mock returns `("","oops\n",1)` → `result.stderr == "oops\n"` AND `result.exit_code == 1` |
| C9 | exit-code propagation: success | mock returns `("","",0)` → `result.exit_code == 0` |
| C10 | exit-code propagation: 124 timeout | mock returns `("","remote command timed out after 5s\n",124)` → `result.exit_code == 124` AND `"timed out after 5s" in result.stderr` (locks the documented UX wording from §1) |
| C11 | exit-code propagation: 127 not-found | mock returns `("","/bin/bash: line 1: foo: command not found\n",127)` → `result.exit_code == 127` |
| C12 | agent not found | `safe_resolve_agent` returns `None` → `result.exit_code != 0` AND `"agent 'foo' not found" in result.stderr` AND `run_agent_shell` NOT called (no SSH work attempted) |
| C13 | CLI-layer agent-name regex rejection | invalid name (`"FOO"`, `"agent name"`, `"../etc"`) → `result.exit_code == 2` AND `run_agent_shell` NOT called (fail-fast at CLI before any inventory/SSH work, even though core also re-validates) |
| C14 | `--help` shows clawctl help | `result.stdout` contains `"NON-INTERACTIVE ONLY"` from the docstring; does NOT call `run_agent_shell` |

#### `tests/core/test_agent_shell.py` (mock `ansible_runner.run`)

| # | Case | Exact assertion |
|---|------|-----------------|
| K1 | event parsing | result with `SHELL_STDOUT=aGk=` / `SHELL_STDERR=` / `SHELL_RC=0` → returns `("hi","",0)`. Also include a stray `EXEC_STDOUT=...` event in the stream and assert it is NOT consumed (return tuple stdout stays empty for that prefix) |
| K2 | base64 decode failure (stdout) | `SHELL_STDOUT=not-base64!!!` → `stdout == ""`, rc still propagated from `SHELL_RC` |
| K3 | base64 decode failure (stderr) | symmetric to K2 |
| K4 | missing rc | events emit STDOUT+STDERR but no `SHELL_RC=` → returns `(stdout, stderr, 255)` |
| K5 | runner timeout status | mock `result.status == "timeout"` → returns `("", "remote command timed out after Ns", 124)` (assert message text exactly, including the `N` substitution) |
| K6 | unreachable host | inject `runner_on_unreachable` event → returns `("", err_with_"unreachable", 255)` |
| K7 | missing host record | `get_host` returns `None` → returns `("", "host 'h' not found", 255)`; `ansible_runner.run` NOT called |
| K8 | missing SSH key | `core_keys.get_host_private_key` returns `None` → returns `("", err_with_"SSH key", 255)`; `ansible_runner.run` NOT called |
| K9 | `_AGENT_NAME_RE` rejection | invalid name → `AgentShellError` raised before any I/O |
| K10 | playbook missing | playbook path does not exist → returns `("", "Playbook not found: ...", 255)`; `ansible_runner.run` NOT called |
| K11 | artifact cleanup on success | after success, assert `private_data_dir` no longer exists on disk |
| K12 | artifact cleanup on failure (`finally` branch) | mock `ansible_runner.run` raises `RuntimeError("boom")` → returns `("", "ansible-runner error: boom", 255)` AND `private_data_dir` does NOT exist on disk (cleanup runs in `finally`) |
| K13 | `private_data_dir` mode | after run, assert `os.stat(saved_path).st_mode & 0o777 == 0o700` (capture path before cleanup via `side_effect` that records the call kwargs) |
| K14 | runner timeout buffer | for `effective_timeout` of `120`, `60`, `1800` → `ansible_runner.run` was called with `timeout=150`, `90`, `1830` respectively (the documented `+30` buffer is invariant, not magic) |
| K15 | `shlex.join` correctness | for each of `["echo","a b"]`, `["echo","it's"]`, `['echo','"x"']`, `["echo","$HOME"]`, `["sh","-c","ls | head"]`, `["a","&&","b"]` → assert the `cmd_str` extravar matches `shlex.join(input)` and parses to the same argv under `shlex.split` |
| K16 | timeout clamp matrix | `(None,0,-1,1,60,1800,1801,9999) → (1800,1800,1800,1,60,1800,1800,1800)` — assert via extravar `shell_timeout` AND via the `ansible_runner.run(timeout=...)` arg (which is `effective+30`) |
| K17 | TOCTOU on `private_data_dir` create | monkeypatch `Path.mkdir` to raise `FileExistsError` on first call → returns `("", err_with_"workdir", 255)` AND no orphan directory left on disk |
| K18 | large stdout round-trip (64KB) | base64-encode 64KB of `os.urandom`-style bytes, assert byte-exact decode back |
| K19 | non-UTF-8 in stdout (documented lossy boundary) | Ansible decodes `stdout` upstream as utf-8 with `errors='replace'`, so non-UTF-8 bytes become U+FFFD by the time we b64-encode them. This test asserts the **documented behavior**: input `b'\xff\xfe hi'` arrives as the replacement-char string, not byte-exact. The plan acknowledges this as a known boundary, not a regression. |

#### `tests/platform/test_shell_playbook.py` (YAML-parse, no runner)

Loads `src/clawrium/platform/shell/shell.yaml` with `yaml.safe_load`
and asserts security invariants directly on the parsed structure —
this catches regressions where a future edit silently drops `no_log`
or changes the kill-path. No ansible-runner invocation; pure static
inspection.

| # | Case | Exact assertion |
|---|------|-----------------|
| P1 | `no_log: true` on the command task | the task whose name starts with `"Run command"` has `no_log` exactly `True` |
| P2 | `become_user: "{{ agent_name }}"` on the command task | same task has `become: true` AND `become_user == "{{ agent_name }}"` |
| P3 | `/usr/bin/timeout` is argv[0] | `task["ansible.builtin.command"]["argv"][0] == "/usr/bin/timeout"` (regressions that swap to `shell:` or drop the wrapper fail here) |
| P4 | `bash -lc` is the inner shell | argv contains `["/bin/bash","-lc"]` in order |
| P5 | `agent_name` regex validation task is present | a task with `ansible.builtin.fail` and `when` referencing `agent_name is not match(...)` exists |
| P6 | `failed_when: false` AND `changed_when: false` | command task does not let nonzero rc bubble up to Ansible (we propagate rc ourselves via `SHELL_RC`) |

### Known boundaries (documented, not bugs)

- **Non-UTF-8 stdout/stderr from the remote command is lossy.**
  Ansible's `command` module decodes child output as UTF-8 with
  `errors='replace'` before handing it to us, so any non-UTF-8 byte
  sequences arrive as U+FFFD replacement chars by the time the
  playbook b64-encodes them. Test K19 asserts this documented
  behavior so a future Ansible upgrade that changes the contract
  surfaces immediately as a test failure, not a silent corruption.
  Operators needing byte-exact binary output should redirect to a
  file remotely and `scp` it down — out of scope for `shell` v1.
- **`/usr/bin/timeout` must exist on the host.** Linux distros we
  ship to all include coreutils; if a host doesn't, the playbook
  fails loudly. macOS subissue revisits.
- **No streaming.** Output arrives at task completion. `make test`
  may feel unresponsive; documented in `--help`.

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

### Planning — ATX iter 2 (test-plan sharpening)

**Stage**: planning
**Skill**: Stop-hook ATX review on plan file
**Timestamp**: 2026-06-20T00:00:00Z
**Model**: claude-opus-4-7

Iter 1 rated 3/5 with 4 warnings + 5 suggestions (no blockers).
Iter 2 addresses all of them in the plan itself (no code yet):

| # | Type | Issue | Resolution |
|---|------|-------|------------|
| W1 | Warning | No regression test for `no_log: true` on the shell command task | New test file `tests/platform/test_shell_playbook.py` (cases P1–P6) asserts `no_log: true`, `become_user`, `/usr/bin/timeout` argv[0], `bash -lc`, agent_name regex task, `failed_when/changed_when: false` via YAML parse |
| W2 | Warning | No test for `private_data_dir` mode 0o700 or the `+30` runner timeout buffer | New core cases K13 (mode 0o700 via `os.stat`) and K14 (assert `ansible_runner.run(timeout=effective+30)` for `120/60/1800 → 150/90/1830`) |
| W3 | Warning | CLI test bullets too vague — `.assert_called()` would pass under silent zeroing | Whole CLI table restated as **exact-args assertions** (`run_agent_shell.assert_called_once_with(..., timeout=600)` etc.); 14 cases C1–C14 |
| W4 | Warning | CLI test list omits "agent not found" and CLI-layer regex rejection | C12 (`safe_resolve_agent` returns None → friendly error, `run_agent_shell` NOT called) and C13 (CLI-layer `_AGENT_NAME_RE` rejection) added; CLI sketch updated to spell out the fail-fast checks |
| S1 | Suggestion | No race/TOCTOU test for `private_data_dir` create + cleanup-on-raise | K12 (`finally`-branch cleanup when `ansible_runner.run` raises) and K17 (`Path.mkdir` raises `FileExistsError` → clean failure, no orphan) added |
| S2 | Suggestion | No large-stdout or non-UTF-8 test | K18 (64KB byte-exact round-trip) and K19 added; the lossy U+FFFD boundary for non-UTF-8 explicitly documented under new "Known boundaries" section |
| S3 | Suggestion | Timeout clamp test missing `None`, `-1`, `1800` boundary | Clamp matrix K16 now covers `(None,0,-1,1,60,1800,1801,9999) → (1800,1800,1800,1,60,1800,1800,1800)`; clamp behavior spec in core sketch updated; CLI rejects negative with exit 2 (C6) before even reaching core |
| S4 | Suggestion | Plan didn't enumerate the minimum host-record fixture shape | "Host-record fixture" subsection added with the exact dict (hostname/user/port/key_id/alias) for verbatim copy into test files |
| S5 | Suggestion | No assertion on the 124-timeout friendly message text | C10 now asserts `"timed out after 5s" in result.stderr` AND `exit_code == 124`; K5 asserts the exact message string with the `N` substitution |

Additional plan tightening prompted by the review:

- Clamp location explicitly pinned to **core, not CLI** (was
  ambiguous in iter 1). C4/C5 and K16 are now consistent.
- "Known boundaries" section added so non-UTF-8 and missing-`timeout`
  cases are documented design choices, not future bugs.
- CLI sketch grew explicit bullets for negative-timeout callback,
  agent-name fail-fast, and "no clamping at CLI" — each linked to
  its test case ID for traceability.

```prompt
Stop hook feedback: ATX Review — .itx/761/00_PLAN.md
Test-Coverage Rating: 3/5
No blocking issues. 4 warnings and 5 suggestions.
[full review pasted in PR thread]
```

**Output**: in-place revision of `.itx/761/00_PLAN.md` — 14 CLI
cases, 19 core cases, 6 YAML-parse cases, explicit host fixture,
"known boundaries" section.

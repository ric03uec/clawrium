# Issue #413: User can run agent-native commands on remote hosts using `clawctl agent exec`

URL: https://github.com/ric03uec/clawrium/issues/413

> Note: The issue body uses the older command name `clm agent pt`. Implementation wires the feature into the existing `clawctl agent exec` placeholder stub (`clm` is now `clawctl`; the `exec` command name supersedes `pt`). Issue body will be updated when the PR opens.

## Overview

Replace the existing `clawctl agent exec` placeholder stub with a real implementation that executes commands against an installed agent's native CLI on the remote host, using ansible. stdout, stderr, and the remote exit code are propagated to the local terminal.

## Approach

Three per-type ansible playbooks (`exec.yaml` under each agent type's playbook directory) hardcode the binary path and workspace directory for that type. A shared core dispatcher (`core/agent_exec.py`) runs the type-appropriate playbook via `ansible_runner`, parses base64-encoded stdout/stderr/rc from debug events, and returns a `(stdout, stderr, rc)` tuple. The CLI command writes streams to the local terminal and exits with the remote rc.

No live streaming in v1: ansible's `command` module returns output at task completion, not character-by-character. The original AC wording "streamed live" is revised to "returned at command completion" for v1.

## Per-Type Paths

Convention matches existing `install.yaml` and `memory_info.yaml` per type. Paths are baked into each playbook; not persisted in `hosts.json`.

| Type | Binary | Workspace (`chdir`) |
|---|---|---|
| hermes | `/home/<agent_name>/.local/bin/hermes` | `/home/<agent_name>/.hermes` |
| zeroclaw | `/home/<agent_name>/bin/zeroclaw` | `/home/<agent_name>/.zeroclaw/workspace` |
| openclaw | `/home/<agent_name>/.openclaw/bin/openclaw` | `/home/<agent_name>/.openclaw/workspace` |

## CLI Surface

```
clawctl agent exec <agent-name> -- <cmd> [args...]
```

Examples:
```bash
clawctl agent exec wolf-i -- openclaw --version
clawctl agent exec my-hermes -- hermes config show
clawctl agent exec my-zeroclaw -- zeroclaw status
```

### Behavior

| Aspect | Value |
|---|---|
| Working directory | Per-type default workspace, hardcoded in playbook. Not user-configurable in v1. |
| TTY | None (`ansible.builtin.command` module, non-interactive). |
| Output | stdout → local stdout, stderr → local stderr, returned at command completion. |
| Exit code | Remote `rc` → `clawctl` exit. SSH/setup failure → 255. Unknown agent → 2. |
| `--` separator | Mandatory; everything after is `argv` to the remote binary. |

### Help Text

```
Usage: clawctl agent exec [OPTIONS] AGENT_NAME [COMMAND]...

  Execute a command against the agent's native CLI on its host.

  The command runs as the agent's user in the agent's workspace directory.
  Use `--` to separate clawctl flags from the remote command:

      clawctl agent exec my-agent -- hermes --version

  Non-interactive only: no TTY is allocated, so commands that prompt
  for input or render TTY-only UI (progress bars, colors) will not work.
  stdout and stderr are returned to the local terminal when the remote
  command completes. The remote exit code is propagated.

Arguments:
  AGENT_NAME      Agent name (as shown by `clawctl agent ps`).  [required]
  COMMAND...      Command and args to run on the agent host (after `--`).

Options:
  --help          Show this message and exit.
```

## Files

| File | Change |
|---|---|
| `src/clawrium/platform/registry/hermes/playbooks/exec.yaml` | New per-type passthrough playbook (hermes constants). |
| `src/clawrium/platform/registry/zeroclaw/playbooks/exec.yaml` | New, zeroclaw constants. |
| `src/clawrium/platform/registry/openclaw/playbooks/exec.yaml` | New, openclaw constants. |
| `src/clawrium/core/agent_exec.py` | New. `run_agent_exec(hostname, agent_name, claw_type, cmd_argv) -> (stdout: str, stderr: str, rc: int)`. Builds extra_vars, runs `ansible_runner.run` against `<type>/playbooks/exec.yaml`, parses events for `EXEC_STDOUT=`/`EXEC_STDERR=`/`EXEC_RC=` markers. |
| `src/clawrium/cli/clawctl/agent/exec.py` | Replace `echo_not_implemented` body. Resolve agent → call `run_agent_exec` → write streams → `raise typer.Exit(rc)`. Help text updated. |
| `tests/core/test_agent_exec.py` | New. Unit tests for event parsing + extra_vars construction. |
| `tests/cli/clawctl/agent/test_exec.py` | New (or extended if exists). CLI command tests. |
| `AGENTS.md` Quickstart | Add one example line. |

**Estimated diff**: ~120 LOC core + ~15 LOC CLI + 3 × ~30 LOC playbooks + ~130 LOC tests + docs.

## Playbook Shape (each `exec.yaml`)

```yaml
- hosts: all
  gather_facts: false
  vars:
    binary: "/home/{{ agent_name }}/.local/bin/hermes"   # per-type constant
    workdir: "/home/{{ agent_name }}/.hermes"            # per-type constant
  tasks:
    - name: Run agent exec command
      ansible.builtin.command:
        argv: "{{ [binary] + cmd_argv }}"
        chdir: "{{ workdir }}"
      become: true
      become_user: "{{ agent_name }}"
      register: exec_result
      failed_when: false
      changed_when: false

    - name: Emit stdout
      ansible.builtin.debug:
        msg: "EXEC_STDOUT={{ exec_result.stdout | default('') | b64encode }}"

    - name: Emit stderr
      ansible.builtin.debug:
        msg: "EXEC_STDERR={{ exec_result.stderr | default('') | b64encode }}"

    - name: Emit rc
      ansible.builtin.debug:
        msg: "EXEC_RC={{ exec_result.rc | default(255) }}"
```

Base64-encoding stdout/stderr through the debug event avoids YAML/multiline-quoting issues when parsing `runner_on_ok` events. `agent_exec.py` decodes back before writing to the local terminal.

## Argument Safety

`argv:` list bypasses shell entirely. Args travel through `extra_vars` as a typed list. No shell metachar interpretation anywhere. No `shlex.quote` needed.

## TTY Implications (v1: no PTY)

- Interactive prompts will hang/fail — out of scope per issue.
- Color output disabled by most CLIs that detect no TTY.
- TTY-dependent progress bars / spinners won't render.
- Help text documents these limits.

---

## Testing Process

### Unit tests (must pass in `make test`)

**`tests/core/test_agent_exec.py`**
- `test_run_agent_exec_success` — mock `ansible_runner.run` with synthetic events containing base64-encoded `EXEC_STDOUT=`, `EXEC_STDERR=`, `EXEC_RC=0`; assert returned tuple matches decoded values.
- `test_run_agent_exec_nonzero_rc` — same shape, `EXEC_RC=42`; assert tuple `[2]` == 42.
- `test_run_agent_exec_unreachable` — `ansible_runner.run` returns `status='failed'` with no events; assert tuple = `("", <error-msg>, 255)`.
- `test_extra_vars_construction` — assert `cmd_argv` is passed through as a typed list, not stringified.
- `test_unknown_claw_type` — passing an unsupported claw_type raises a clear error before invoking ansible_runner.

**`tests/cli/clawctl/agent/test_exec.py`** (Typer `CliRunner` + mocks)
- `test_exec_success` — mock agent resolver + `run_agent_exec` → assert stdout written, exit code 0.
- `test_exec_nonzero_exit_propagation` — mock `run_agent_exec` returning rc=7; assert `result.exit_code == 7`.
- `test_exec_unknown_agent` — resolver raises `AgentNameResolutionError`; assert exit 2 + error message on stderr.
- `test_exec_unreachable_host` — `run_agent_exec` returns rc=255 + error message; assert stderr contains it, exit 255.
- `test_exec_requires_dash_dash` — `clawctl agent exec foo` (no command tail) → assert exit != 0 + help-style message.
- `test_exec_stderr_separation` — both stdout and stderr in result; assert each lands on the correct local stream.
- `test_exec_help_documents_double_dash` — `clawctl agent exec --help` output contains the `--` convention.

### Lint
- `make lint` clean.

### Coverage
- `make test-cov` shows `core/agent_exec.py` ≥ 90% lines and `cli/clawctl/agent/exec.py` ≥ 90%.

### Manual integration test (executed before opening PR, recorded in PR Testing section)

Against `wolf-i` (existing openclaw agent in `hosts.json`):

1. `clawctl agent exec wolf-i -- openclaw --version` — expect version string, exit 0.
2. `clawctl agent exec wolf-i -- openclaw bogus-subcommand` — expect non-zero exit, stderr from openclaw surfaced locally.
3. `clawctl agent exec does-not-exist -- echo hi` — expect exit 2, clear "agent not found" message, no ansible invocation.
4. Against a hermes agent if available; if not, document gap and rely on unit tests for hermes/zeroclaw playbook coverage.

Each manual step's copy-pasted output goes into the PR Testing section.

### Acceptance-Criteria Mapping

| AC | Verified by |
|---|---|
| Runs `<cmd>` against agent's native CLI on correct host | Unit `test_exec_success` + manual #1 |
| stdout/stderr returned to local terminal | Unit `test_exec_stderr_separation` + manual #1, #2 |
| Remote exit code propagated | Unit `test_exec_nonzero_exit_propagation` + manual #2 |
| Works for hermes, zeroclaw, openclaw | 3 per-type playbooks + manual #1 (openclaw) + #4 (hermes if available); zeroclaw covered by unit tests |
| Clear error on unknown agent / unreachable | Unit `test_exec_unknown_agent`, `test_exec_unreachable_host` + manual #3 |
| Help documents `--` convention | Unit `test_exec_help_documents_double_dash` |
| Tests cover all four scenarios | All four covered in `tests/cli/clawctl/agent/test_exec.py` |
| AGENTS.md updated | Quickstart edit included in this plan |

**Note on revised AC**: "streamed live" → "returned at command completion" for v1. Original wording will be edited in the issue body when the PR opens, with a one-line note explaining the ansible constraint.

## Subtasks

None — single-PR execution.

---

<details>
<summary>Prompt Log</summary>

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-18
**Model**: claude-opus-4-7

```prompt
Create a new feature request. Add support for a CLI command, called CLM agent PT
options. PT stands for pass through. This is a way for users to send agent
specific commands to the agent without logging into the host machine. This is
there to support native commands on the agents without getting SSH access to
the host. Users might need to configure Hermes, Zeroclaw or Openclaw based on
the respective agent's CLI. This option is not supported right now, but the
passthrough option in CLM will allow users to do that.
```

### Clarifications captured

- **Syntax**: `clm agent pt <name> -- <cmd>` (Unix `--` separator convention) — superseded: now uses existing `clawctl agent exec <name> -- <cmd>` placeholder.
- **Output**: Stream live (stdout/stderr) to local terminal — revised: returned at command completion (ansible constraint).
- **Interactivity**: Non-interactive only in v1 (no TTY)
- **Agent types in v1**: hermes, zeroclaw, openclaw (nemoclaw out of scope)
- **Exit code propagation**: Required (must propagate remote exit code as `clawctl` exit code)

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-05-26T01:21:17Z
**Model**: claude-opus-4-7

```prompt
413. dont create plan files yet. (clm is now called clawctl). give me a high level plan first before macking any file chnages
```

**Output**: `.itx/413/00_PLAN.md` — implementation plan for wiring up `clawctl agent exec` via three per-type ansible playbooks and a shared core dispatcher. Single-PR execution, no subtasks.

</details>

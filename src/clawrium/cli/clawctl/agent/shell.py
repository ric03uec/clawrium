"""`clawctl agent shell <name> -- <cmd>` -- run an arbitrary command
on the agent's host in a login bash shell.

Differs from `exec`: `exec` invokes the agent's native binary
(`hermes`, `openclaw`, ...); `shell` runs a full login bash shell as
the agent user, so `~/.bashrc`, PATH shims, virtualenv activations,
pipes, redirects, and `&&`/`||` all work as in an interactive ssh
session. Use `shell` for host-level ops (`ls`, `cat`, `make`, `git`,
...); use `exec` to drive the agent's own CLI.

Self-contained — does NOT reuse `agent/exec.py` plumbing. The flow
talks to `core.agent_shell.run_agent_shell` directly.
"""

from __future__ import annotations

import re
import sys

import typer

from clawrium.cli.clawctl.agent._shared import safe_resolve_agent
from clawrium.cli.output._sanitize import sanitize_passthrough
from clawrium.cli.output.errors import emit_error
from clawrium.core.agent_shell import AgentShellError, run_agent_shell
from clawrium.core.names import RESERVED_UNIX_NAMES

SHELL_CONTEXT_SETTINGS = {
    "ignore_unknown_options": True,
    "allow_extra_args": True,
}

# Mirrors `core.agent_shell._AGENT_NAME_RE`. Duplicated by design:
# fail-fast at the CLI seam so a malformed name never reaches inventory
# build or SSH; core re-validates so non-CLI callers cannot bypass.
_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _reject_negative_timeout(value: int) -> int:
    if value < 0:
        emit_error(
            "--timeout must be >= 0 (use 0 for 'no client timeout')",
            hint="clawctl agent shell --help",
            exit_code=2,
        )
    return value


def shell(
    ctx: typer.Context,
    name: str = typer.Argument(
        ..., help="Agent name (from `clawctl agent get`)."
    ),
    timeout: int = typer.Option(
        120,
        "--timeout",
        help=(
            "Max seconds before the remote command is killed. 0 is an "
            "alias for the hard 1800s (30-min) cap; no value disables "
            "that cap."
        ),
        callback=_reject_negative_timeout,
    ),
) -> None:
    """Run an arbitrary command on the host in the agent user's login shell.

    The command runs as the agent's unix user via `bash -lic` (login
    + interactive), which sources `~/.bash_profile` / `~/.profile`
    AND `~/.bashrc` — PATH shims (pyenv, nvm, asdf), virtualenv
    activations, aliases, and function definitions are all loaded
    before the command runs. Tilde expansion, $HOME, pipes,
    redirects, and && / || all work as in an interactive ssh session.

    LINUX HOSTS ONLY in v1. macOS hosts return a clear error;
    support is tracked in a separate issue.

    NON-INTERACTIVE ONLY. No TTY is allocated. Commands that prompt
    for input will hang; TTY-only UIs (colors, progress bars) will
    not render. For interactive sessions, ssh to the host directly.

    Examples:

        clawctl agent shell my-agent -- 'ls -la ~/'
        clawctl agent shell my-agent -- 'cat ~/.hermes/config.yaml'
        clawctl agent shell my-agent --timeout 600 -- 'make test'

    The remote exit code is propagated. `--timeout 0` disables the
    client-side wait but the hard 30-min cap still applies remotely.
    To forward `--help` to a remote command, use:

        clawctl agent shell my-agent -- '<cmd> --help'
    """
    cmd = list(ctx.args)
    if not cmd:
        emit_error(
            "no command provided",
            hint="clawctl agent shell <name> -- <cmd> [args...]",
            exit_code=2,
        )

    if not _AGENT_NAME_RE.match(name):
        emit_error(
            f"invalid agent name: {name!r}",
            hint="agent names must match ^[a-z][a-z0-9_-]{0,31}$",
            exit_code=2,
        )

    host, _agent_key, claw_record = safe_resolve_agent(name)
    unix_name = claw_record.get("agent_name") or name

    # Defense-in-depth: refuse to run the shell as a reserved system
    # account even if a tampered hosts.json record lists one. Core
    # re-validates so non-CLI callers cannot bypass.
    if unix_name in RESERVED_UNIX_NAMES:
        emit_error(
            f"refusing to run shell as reserved system user: {unix_name!r}",
            hint="agent records must not name system accounts",
            exit_code=2,
        )

    try:
        stdout, stderr, rc = run_agent_shell(
            hostname=host["hostname"],
            agent_name=unix_name,
            cmd_argv=cmd,
            timeout=timeout,
        )
    except AgentShellError as exc:
        emit_error(
            str(exc), hint="clawctl agent shell --help", exit_code=2
        )

    # Infrastructure failures (host unreachable, missing SSH key,
    # missing playbook, runner exception) come back with rc=255 and
    # empty stdout. Route them through `emit_error` so operators see
    # the canonical `Error:` / `Hint:` framing instead of a raw stderr
    # dump that's hard to distinguish from a remote command's own
    # diagnostics (#761 iter-3 W7).
    if rc == 255 and not stdout and stderr:
        emit_error(
            sanitize_passthrough(stderr).rstrip(),
            hint="clawctl agent shell --help",
            exit_code=255,
        )

    if stdout:
        clean = sanitize_passthrough(stdout)
        sys.stdout.write(clean)
        if not clean.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
    if stderr:
        clean = sanitize_passthrough(stderr)
        sys.stderr.write(clean)
        if not clean.endswith("\n"):
            sys.stderr.write("\n")
        sys.stderr.flush()

    raise typer.Exit(code=rc)

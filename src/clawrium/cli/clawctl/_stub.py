"""Shared helpers for the `clawctl` stub group commands.

The wording `Not implemented: <group> <verb>` is the single contract
asserted in tests (see plan §"Specific Outcomes to Validate"). Keeping
it in one place means bundles 3/4 can replace stubs verb-by-verb
without drifting the message.
"""

import typer

__all__ = ["echo_not_implemented", "register_stub"]


def echo_not_implemented(
    group: str,
    verb: str,
    *,
    hint: str | None = None,
    exit_code: int = 0,
) -> None:
    """Print the canonical placeholder line, optionally exit non-zero.

    `hint`, when set, is printed on its own line after the canonical
    `Not implemented: ...` line. `exit_code`, when non-zero, raises
    `typer.Exit(code=exit_code)` after printing — flips the stub from
    silent-success (which lets `<cmd> && next` chain past unimplemented
    verbs) to a hard failure. Both default to legacy behavior so
    stubs that have not opted in stay byte-identical.
    """
    typer.echo(f"Not implemented: {group} {verb}")
    if hint:
        typer.echo(hint)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def register_stub(
    app: typer.Typer,
    *,
    group: str,
    verb: str,
    help_text: str = "",
) -> None:
    """Register a `<verb>` command on `app` that emits the placeholder.

    Used by the per-group stub modules so the surface visible in
    `clawctl <group> --help` matches the planned §4 verb list, even
    before bundles 3-4 wire up the real logic.
    """

    def _stub() -> None:
        echo_not_implemented(group, verb)

    _stub.__doc__ = help_text or f"{verb} (not yet implemented)"
    app.command(name=verb)(_stub)

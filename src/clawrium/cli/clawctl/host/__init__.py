"""`clawctl host` — Pattern B target (fleet machines).

Plan §4 surface: create, get, describe, delete, edit, reset, alias,
address (nested), label, registry.

Each verb lives in its own module under this package; this
`__init__.py` only wires them onto the `host_app` Typer instance so
`clawctl host --help` lists the planned commands in the documented
order.

`clawrium.core.*` is the data plane; every verb delegates to existing
core functions (`core/hosts.py`, `core/reset.py`, etc.). The CLI layer
adds output formatting (via `clawrium.cli.output`), flag parsing, and
the non-interactive contract (plan §7).
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.host import (
    address as _address,
    alias as _alias,
    create as _create,
    delete as _delete,
    describe as _describe,
    edit as _edit,
    get as _get,
    label as _label,
    registry as _registry,
    reset as _reset,
)

__all__ = ["host_app"]


host_app = typer.Typer(
    name="host",
    help="Manage fleet machines (hosts).",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)


# Verb registration. Order matches plan §4.
host_app.command(
    name="create", help="Register a host after verifying SSH access to the xclm management user."
)(_create.create)
host_app.command(name="get", help="List hosts.")(_get.get)
host_app.command(name="describe", help="Describe a host.")(_describe.describe)
host_app.command(name="delete", help="Delete a host record.")(_delete.delete)
host_app.command(name="edit", help="Edit a host record in place.")(_edit.edit)
host_app.command(name="reset", help="Wipe remote `xclm` state on a host.")(_reset.reset)
host_app.command(name="alias", help="Manage host aliases (multi-value).")(_alias.alias)
host_app.command(name="label", help="Manage host labels (KEY=VALUE / KEY-).")(
    _label.label
)


# Sub-groups (nested verbs).
host_app.add_typer(_address.address_app, name="address")
host_app.add_typer(_registry.registry_app, name="registry")

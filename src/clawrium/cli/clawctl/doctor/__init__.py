"""`clawctl doctor` — read-only diagnostic probes.

This group hosts one probe per external substrate that Clawrium depends
on but does not own. Each probe fetches upstream metadata (release tag,
tarball URL, checksum) and reports whether Clawrium's pin matches
reality, without touching any host.

Probes shipped so far:

- ``clawctl doctor nemoclaw`` — verify the NemoClaw substrate pin in
  ``clawrium.core.nemoclaw`` against ``github.com/NVIDIA/NemoClaw``.
  Phase 1 of issue #11.

Note: agent-level diagnostics live under ``clawctl agent doctor <name>``
and remain the right entry point for a specific agent's health. Group
this ``doctor`` namespace by *substrate* rather than by agent.
"""

from __future__ import annotations

import typer

from clawrium.cli.clawctl.doctor.nemoclaw import doctor_nemoclaw

__all__ = ["doctor_app"]


doctor_app = typer.Typer(
    name="doctor",
    help="Read-only diagnostic probes for external substrates Clawrium depends on.",
    no_args_is_help=True,
    rich_markup_mode=None,
    add_completion=False,
)

doctor_app.command(
    name="nemoclaw",
    help="Verify the pinned NemoClaw upstream release is reachable and shas match.",
)(doctor_nemoclaw)

"""Guard tests for the per-agent-type template naming convention.

Issue #510 (Bundle 5 of #435) removes the historical `clawctl-` prefix from
Jinja2 templates under `src/clawrium/platform/registry/*/templates/`.
The convention going forward is that templates carry their agent-type
prefix (`zeroclaw-*`, `hermes-*`, etc.) so the source-vs-destination
file naming stays unambiguous at a glance.

This module enforces the regression-safe half of that convention: no
template anywhere under any registry's `templates/` tree may start with
`clawctl-`. The full `<type>-` / `<type>.` prefix convention is documented
in `.itx/435/00_PLAN.md` §10 but is not asserted here — pre-existing
unprefixed templates (`openclaw/templates/AGENTS.md.j2` etc.) remain
out of scope for this bundle per the explicit rename list in the
issue.
"""

from pathlib import Path

import pytest

REGISTRY_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "clawrium" / "platform" / "registry"
)


def _registry_templates() -> list[Path]:
    """Return every `*.j2` file under `registry/*/templates/`."""

    matches: list[Path] = []
    for registry_dir in REGISTRY_ROOT.iterdir():
        if not registry_dir.is_dir():
            continue
        templates_dir = registry_dir / "templates"
        if not templates_dir.exists():
            continue
        matches.extend(p for p in templates_dir.rglob("*.j2") if p.is_file())
    return matches


def test_template_root_resolves():
    """Smoke-test: the registry root the loader expects must exist."""

    assert REGISTRY_ROOT.is_dir(), f"Registry root not found: {REGISTRY_ROOT}"
    assert _registry_templates(), "No templates discovered — selector regressed?"


@pytest.mark.parametrize("template", _registry_templates(), ids=lambda p: str(p))
def test_no_clm_prefixed_templates(template: Path) -> None:
    """No template anywhere may carry the historical `clawctl-` prefix."""

    assert not template.name.startswith("clawctl-"), (
        f"Template {template} starts with the deprecated `clawctl-` prefix. "
        f"Rename per `.itx/435/00_PLAN.md` §10 (use `<type>-` or `<type>.`)."
    )


def _registry_playbooks() -> list[Path]:
    """Return every `*.yaml` file under `registry/*/playbooks/`."""

    matches: list[Path] = []
    for registry_dir in REGISTRY_ROOT.iterdir():
        if not registry_dir.is_dir():
            continue
        playbooks_dir = registry_dir / "playbooks"
        if not playbooks_dir.exists():
            continue
        matches.extend(p for p in playbooks_dir.rglob("*.yaml") if p.is_file())
    return matches


@pytest.mark.parametrize("playbook", _registry_playbooks(), ids=lambda p: str(p))
def test_no_clm_prefix_in_playbook_path_refs(playbook: Path) -> None:
    """Playbook `src:` and `dest:` path refs must not point at `clawctl-*` files.

    ATX #510 W5 — the `*.j2` filename scanner above does not catch a
    regression where a playbook re-introduces `10-clawctl-env.conf` as a
    `dest:` value (the rendered file on the agent host) even though the
    source template is correctly named. This test scans every YAML line
    that names a path field for the deprecated `clawctl-` prefix.

    The legacy filename `10-clawctl-env.conf` is also caught by this rule —
    even after `configure.yaml` learned to remove the orphan dropin in
    Bundle 5, re-introducing it as a managed `dest:` would land a stale
    file path back on every agent host.
    """

    text = playbook.read_text()
    offenders: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        # Only inspect lines that name a path-bearing field. Avoid
        # matching `dest:` inside a comment or a multi-line string by
        # requiring the key at the start of the (stripped) line.
        if not (stripped.startswith("src:") or stripped.startswith("dest:")):
            continue
        # The Bundle 5 (#510) cleanup task in zeroclaw/configure.yaml
        # legitimately references `10-clawctl-env.conf` as a `path:` (not
        # `src:`/`dest:`) — that legitimate ref is filtered out by the
        # startswith check above, but be explicit in case the cleanup
        # task ever changes shape.
        if "clawctl-" in line:
            offenders.append((lineno, line.rstrip()))

    assert not offenders, (
        f"{playbook}: src:/dest: line(s) reference deprecated `clawctl-*` paths "
        f"(reintroducing #510 W1 regression):\n"
        + "\n".join(f"  L{ln}: {ln_text}" for ln, ln_text in offenders)
    )

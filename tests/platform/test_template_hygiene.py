"""Cross-agent template hygiene guards.

#911: the zeroclaw config template shipped for months with a hardcoded
operator-specific home (`/home/clawrium-d01/…`) at seven daemon-owned
paths — a copy-paste from a real host that survived review because no
test looked at the raw template string, only at rendered output for
one agent name. This module walks every bundled agent's `templates/`
directory and asserts the same class of leak never resurfaces in any
agent (zeroclaw, openclaw, hermes, or future additions).
"""

from __future__ import annotations

from pathlib import Path

# Literal strings that must NEVER appear in a shipped template. These are
# real operator homes / hostnames pulled from prior copy-paste incidents.
# Add to this list when a new incident is discovered — the assertion is
# cheap and the false-positive rate is effectively zero for these names.
_FORBIDDEN_LITERALS = (
    "clawrium-d01",  # #911 — zeroclaw operator home
)


def _registry_root() -> Path:
    # tests/platform/test_template_hygiene.py → .../src/clawrium/platform/registry
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "clawrium"
        / "platform"
        / "registry"
    )


def _iter_template_files() -> list[Path]:
    root = _registry_root()
    assert root.is_dir(), f"registry root not found at {root}"
    files: list[Path] = []
    # Every `templates/` subdir under any agent-type folder.
    for template_dir in root.glob("*/templates"):
        if not template_dir.is_dir():
            continue
        for path in template_dir.rglob("*"):
            if path.is_file():
                files.append(path)
    assert files, "no template files discovered under registry/*/templates/"
    return files


def test_no_operator_specific_home_in_any_template():
    """No forbidden literal (operator-specific homes, hostnames) may appear
    in any bundled agent template. Prevents the #911 class of bug across
    zeroclaw, openclaw, hermes, and future agent types.
    """
    offenders: list[tuple[Path, str, int]] = []
    for path in _iter_template_files():
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary asset (e.g. a bundled image). Skip — the leak class
            # is a text-template concern.
            continue
        for literal in _FORBIDDEN_LITERALS:
            count = body.count(literal)
            if count:
                offenders.append((path, literal, count))
    assert not offenders, (
        "forbidden literals found in bundled templates:\n"
        + "\n".join(
            f"  {p.relative_to(_registry_root())}: {lit!r} × {n}"
            for (p, lit, n) in offenders
        )
    )

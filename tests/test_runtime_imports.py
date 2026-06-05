"""Guards runtime-vs-dev dependency declarations in pyproject.toml.

Bugs like #620 happen when a package is imported from production code paths
but only declared under `[dependency-groups].dev`. PEP 735 dev groups are
not part of wheel metadata, so `uv tool install clawrium` produces an env
that crashes on first use. These tests fail loudly if a known runtime dep
drifts back to dev-only.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def _runtime_deps() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    return data["project"]["dependencies"]


@pytest.mark.parametrize("package", ["jinja2"])
def test_runtime_import_declared_as_runtime_dep(package: str) -> None:
    joined = " ".join(_runtime_deps()).lower()
    assert package in joined, (
        f"{package!r} is imported from runtime code paths "
        f"(see #620 for jinja2 — core/render.py and core/launchd.py) "
        f"but is missing from [project].dependencies in pyproject.toml. "
        f"A fresh `uv tool install clawrium` will crash on first use."
    )

"""Regression test: built wheel must ship the staged GUI frontend.

Without this, `clm gui` after `uv tool install clawrium` returns 404 on every
non-API route because `mount_frontend()` short-circuits when
`clawrium/gui/frontend/index.html` is missing inside the installed package
(see issue #401).

The test is a no-op locally when the GUI hasn't been built (running `make
test-py` without `make build-ui` shouldn't fail for contributors who don't
have Node installed). It runs whenever the staged frontend exists, and CI
must build the GUI before invoking this test to catch wheel-config regressions.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGED_FRONTEND_INDEX = REPO_ROOT / "src" / "clawrium" / "gui" / "frontend" / "index.html"


pytestmark = [
    pytest.mark.skipif(
        not STAGED_FRONTEND_INDEX.exists(),
        reason="Staged GUI frontend missing — run `make build-ui` to enable this test",
    ),
    pytest.mark.skipif(
        shutil.which("uv") is None,
        reason="`uv` not on PATH — required to build the wheel",
    ),
]


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("wheel-out")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "uv build --wheel failed\n"
            f"stdout:\n{result.stdout.decode(errors='replace')}\n"
            f"stderr:\n{result.stderr.decode(errors='replace')}"
        )
    wheels = list(out_dir.glob("clawrium-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found: {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def wheel_names(built_wheel: Path) -> set[str]:
    with zipfile.ZipFile(built_wheel) as zf:
        return set(zf.namelist())


def test_wheel_includes_frontend_index(wheel_names: set[str]) -> None:
    assert "clawrium/gui/frontend/index.html" in wheel_names, (
        "Wheel is missing the staged Next.js frontend. "
        "Check `[tool.hatch.build.targets.wheel.force-include]` in pyproject.toml — "
        "without this, `clm gui` 404s on every non-API route after install (#401)."
    )


def test_wheel_includes_next_static_assets(wheel_names: set[str]) -> None:
    """Without `_next/`, every route would render HTML that 404s all its JS/CSS."""
    has_next_dir = any(n.startswith("clawrium/gui/frontend/_next/") for n in wheel_names)
    has_js_chunk = any(
        n.startswith("clawrium/gui/frontend/_next/static/chunks/") and n.endswith(".js")
        for n in wheel_names
    )
    has_css = any(
        n.startswith("clawrium/gui/frontend/_next/static/css/") and n.endswith(".css")
        for n in wheel_names
    )
    assert has_next_dir and has_js_chunk and has_css, (
        "Wheel is missing Next.js static assets under `_next/`. "
        "HTML pages would load but all JS/CSS would 404 post-install."
    )


def test_wheel_frontend_has_all_route_pages(wheel_names: set[str]) -> None:
    """Every top-level `.html` produced by the Next.js export must ship in the wheel.

    Enumerating the source tree (instead of a hardcoded list) makes this test
    track new routes automatically — adding a new page in the GUI shouldn't
    require updating this test, but a partial wheel that drops an existing
    page will still fail.
    """
    staged_frontend = STAGED_FRONTEND_INDEX.parent
    expected_pages = sorted(p.name for p in staged_frontend.glob("*.html"))
    assert expected_pages, "no staged HTML pages found — UI build is empty"
    missing = [
        page for page in expected_pages
        if f"clawrium/gui/frontend/{page}" not in wheel_names
    ]
    assert not missing, (
        f"Wheel is missing route exports: {missing}. "
        "UI build may be incomplete or wheel packaging is dropping files."
    )


def test_wheel_includes_all_skill_namespaces(wheel_names: set[str]) -> None:
    """Every namespace under `skills/` must land in `clawrium/_skills/` in the wheel.

    A previous assertion only checked that `clawrium/_skills/` had any entry,
    which `skills/README.md` alone would satisfy — letting three of four skill
    namespaces silently drop out of the wheel and break `clm skill list`
    post-install. This test enumerates the source tree so it stays accurate
    as namespaces are added or removed.
    """
    skills_root = REPO_ROOT / "skills"
    namespaces = sorted(
        p.name for p in skills_root.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )
    assert namespaces, "no skill namespaces found in source tree"
    missing = [
        ns for ns in namespaces
        if not any(n.startswith(f"clawrium/_skills/{ns}/") for n in wheel_names)
    ]
    assert not missing, (
        f"Wheel is missing skill namespaces: {missing}. "
        "Check `skills` force-include in `[tool.hatch.build.targets.wheel.force-include]`."
    )


def test_wheel_includes_canonical_skill_file(wheel_names: set[str]) -> None:
    """Pin the canonical clawrium/tdd SKILL.md path called out in AGENTS.md."""
    assert "clawrium/_skills/clawrium/tdd/SKILL.md" in wheel_names, (
        "Wheel is missing the canonical `clawrium/tdd` skill referenced in AGENTS.md."
    )


def test_sdist_includes_staged_frontend(tmp_path: Path) -> None:
    """Regression for the sdist→wheel roundtrip: the sdist must carry the staged
    frontend at its source path so the wheel build (which unpacks the sdist) can
    re-include it via the wheel-target force-include."""
    import tarfile

    out_dir = tmp_path
    result = subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "uv build --sdist failed\n"
            f"stderr:\n{result.stderr.decode(errors='replace')}"
        )
    sdists = list(out_dir.glob("clawrium-*.tar.gz"))
    assert len(sdists) == 1, f"expected exactly one sdist, found: {sdists}"
    with tarfile.open(sdists[0]) as tf:
        names = tf.getnames()
    assert any(
        n.endswith("/src/clawrium/gui/frontend/index.html") for n in names
    ), (
        "Sdist is missing the staged frontend. Without this in the sdist, uv's "
        "sdist→wheel roundtrip build fails because the wheel-target force-include "
        "can't find `src/clawrium/gui/frontend/`. Check the "
        "`[tool.hatch.build.targets.sdist.force-include]` block in pyproject.toml."
    )

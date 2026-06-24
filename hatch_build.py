"""Hatchling custom build hook — generates src/clawrium/_version.py at build time.

Writes ``__version__`` and ``__git_sha__`` into a standalone module that ships
inside the wheel.  At runtime ``clawrium/__init__.py`` imports from here when
available (installed package) and falls back to ``importlib.metadata`` for
editable installs.

Sdist builds include the generated ``_version.py`` so that wheel builds from
the sdist (e.g. ``uv tool install`` from PyPI) preserve the embedded SHA
instead of overwriting it with ``"unknown"``.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_VERSION_FILE = _ROOT / "src" / "clawrium" / "_version.py"
_UNKNOWN = "unknown"

# The hatchling import is only needed when this module is loaded by the
# hatchling build system.  Guard it so the module is importable for testing
# without hatchling installed (e.g. in CI where only test deps are present).
try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ImportError:  # pragma: no cover — hatchling not installed at test time
    BuildHookInterface = object  # type: ignore[assignment, misc]


def _get_version() -> str:
    """Return the package version string.

    Reads ``pyproject.toml`` first so that the *build* version is always used,
    not a stale previously-installed one (W1).
    """
    import tomllib

    pyproject = _ROOT / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
        return data.get("project", {}).get("version", "0.0.0")
    # Last resort — may return a previously-installed version, but at least
    # we don't fail entirely when pyproject.toml is absent.
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("clawrium")
    except PackageNotFoundError:
        return "0.0.0"


def _get_git_sha() -> str:
    """Return the short git commit SHA, or ``"unknown"`` on failure.

    * GIT_* env vars are scrubbed from the subprocess so CI environments with
      ``GIT_DIR``/``GIT_WORK_TREE`` don't resolve against the wrong repo (W3).
    * The output is validated as 4–40 hex chars (S1); anything else is
      treated as failure.
    * On every failure path a warning is emitted (W2). If the env var
      ``CLAWRIUM_REQUIRE_GIT_SHA`` is set, the build aborts instead.
    """
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(_ROOT),
                stderr=subprocess.DEVNULL,
                env=clean_env,
            )
            .decode()
            .strip()
        )
        if sha and re.fullmatch(r"[0-9a-f]{4,40}", sha):
            return sha
        # SHA format unexpected — treat as failure.
        _warn_git("git rev-parse returned unexpected output: {!r}".format(sha))
        return _UNKNOWN
    except FileNotFoundError:
        _warn_git("git binary not found on PATH")
        return _UNKNOWN
    except subprocess.CalledProcessError as exc:
        _warn_git("git rev-parse failed (exit {}): {}".format(exc.returncode, exc.output))
        return _UNKNOWN
    except OSError as exc:
        _warn_git("git rev-parse raised OSError: {}".format(exc))
        return _UNKNOWN


def _warn_git(message: str) -> None:
    """Emit a warning for git SHA resolution failure (W2).

    If ``CLAWRIUM_REQUIRE_GIT_SHA`` is set to a truthy value, raise
    ``RuntimeError`` instead so release builds abort rather than ship
    an unknown SHA silently.
    """
    full_msg = "clawrium build: could not determine git SHA — {}".format(message)
    if os.environ.get("CLAWRIUM_REQUIRE_GIT_SHA"):
        raise RuntimeError(full_msg)
    warnings.warn(full_msg, stacklevel=2)


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]
    """Hatchling build hook that generates ``_version.py`` before the build."""

    PLUGIN_NAME = "custom"

    def initialize(self, build_version: str, build_data: dict[str, Any]) -> None:
        # Prefer the version hatchling resolved (S1) — it is always the
        # correct build version.  Fall back to _get_version() only when
        # hatchling passes an empty string (should not happen in practice).
        pkg_version = build_version or _get_version()
        git_sha = _get_git_sha()

        # B1: If _version.py already exists (e.g. shipped inside the sdist)
        # and contains a real SHA, do not overwrite it — the sdist→wheel
        # roundtrip must preserve the embedded SHA rather than regenerating
        # it as "unknown" in a no-git temp directory.
        if _VERSION_FILE.exists():
            existing = _VERSION_FILE.read_text()
            # A real SHA is any value that is not the sentinel "unknown".
            match = re.search(r"^__git_sha__\s*=\s*['\"]([^'\"]+)['\"]", existing, re.MULTILINE)
            if match and match.group(1) != _UNKNOWN:
                git_sha = match.group(1)
            # Similarly preserve the version if it's already present and valid.
            ver_match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", existing, re.MULTILINE)
            if ver_match and ver_match.group(1):
                pkg_version = ver_match.group(1)

        content = (
            "# AUTO-GENERATED by hatch_build.py — do not edit.\n"
            "__version__ = {pkg_version!r}\n"
            "__git_sha__ = {git_sha!r}\n"
        ).format(pkg_version=pkg_version, git_sha=git_sha)

        # W3: If the existing file already has identical content, skip the
        # rewrite — avoids unnecessary mtime changes and bytecode invalidation.
        if _VERSION_FILE.exists():
            existing = _VERSION_FILE.read_text()
            if existing == content:
                return

        # W4: Atomic write — write to a temp file then os.replace() so that
        # a half-written file from Ctrl-C / OOM never exists on disk.
        fd, tmp_path = tempfile.mkstemp(dir=_VERSION_FILE.parent, suffix=".py")
        try:
            os.write(fd, content.encode())
        finally:
            os.close(fd)
        os.replace(tmp_path, _VERSION_FILE)

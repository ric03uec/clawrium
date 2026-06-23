"""Tests for ``hatch_build.py`` — the custom build hook (B4).

Covers:
- ``_get_git_sha()`` success and error branches (FileNotFoundError,
  CalledProcessError, OSError)
- ``_get_version()`` pyproject.toml fallback
- ``initialize()`` writing valid Python that passes ``compile()`` and yields
  expected ``__version__`` / ``__git_sha__``
- ``initialize()`` preserving existing real SHA from sdist (B1)
- ``initialize()`` skipping rewrite when content is identical (W3)
- ``_warn_git()`` warning vs RuntimeError with CLAWRIUM_REQUIRE_GIT_SHA
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# _get_git_sha
# ---------------------------------------------------------------------------

class TestGetGitSha:
    """Unit tests for ``_get_git_sha()``."""

    def test_returns_sha_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: b"a3f9c12\n")
        from hatch_build import _get_git_sha

        assert _get_git_sha() == "a3f9c12"

    def test_returns_unknown_on_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a: object, **kw: object) -> None:
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "check_output", _raise)
        from hatch_build import _get_git_sha

        assert _get_git_sha() == "unknown"

    def test_returns_unknown_on_called_process_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a: object, **kw: object) -> None:
            raise subprocess.CalledProcessError(128, "git", output=b"not a repo")

        monkeypatch.setattr(subprocess, "check_output", _raise)
        from hatch_build import _get_git_sha

        assert _get_git_sha() == "unknown"

    def test_returns_unknown_on_os_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a: object, **kw: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(subprocess, "check_output", _raise)
        from hatch_build import _get_git_sha

        assert _get_git_sha() == "unknown"

    def test_returns_unknown_on_non_hex_sha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: b"not-hex!\n")
        from hatch_build import _get_git_sha

        assert _get_git_sha() == "unknown"

    def test_scrubs_git_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """W3: GIT_* env vars must be removed from the subprocess env."""
        monkeypatch.setenv("GIT_DIR", "/some/other/repo/.git")
        captured_env: dict[str, str] = {}

        def _capture(*a: object, **kw: object) -> bytes:
            captured_env.update(kw.get("env", {}))  # type: ignore[arg-type]
            return b"abcd123\n"

        monkeypatch.setattr(subprocess, "check_output", _capture)
        from hatch_build import _get_git_sha

        assert _get_git_sha() == "abcd123"
        assert "GIT_DIR" not in captured_env


# ---------------------------------------------------------------------------
# _get_version
# ---------------------------------------------------------------------------

class TestGetVersion:
    """Unit tests for ``_get_version()``."""

    def test_reads_pyproject_toml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "99.9.9"\n')
        from hatch_build import _get_version

        monkeypatch.setattr("hatch_build._ROOT", tmp_path)
        assert _get_version() == "99.9.9"

    def test_falls_back_to_importlib(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """When pyproject.toml is absent, falls back to importlib.metadata."""
        from hatch_build import _get_version

        # _ROOT points at a dir without pyproject.toml.
        monkeypatch.setattr("hatch_build._ROOT", tmp_path)
        # The fallback may or may not find clawrium installed; just assert
        # it returns a string without crashing.
        result = _get_version()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# CustomBuildHook.initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    """Unit tests for ``CustomBuildHook.initialize()``."""

    @pytest.fixture()
    def _hook(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Create a CustomBuildHook instance with mocked paths."""
        version_file = tmp_path / "src" / "clawrium" / "_version.py"
        version_file.parent.mkdir(parents=True)
        monkeypatch.setattr("hatch_build._ROOT", tmp_path)
        monkeypatch.setattr("hatch_build._VERSION_FILE", version_file)
        monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: b"deadbee\n")
        from hatch_build import CustomBuildHook

        hook = CustomBuildHook.__new__(CustomBuildHook)
        return hook

    def test_writes_valid_python(self, _hook, tmp_path: Path) -> None:
        _hook.initialize("1.0.0", {})
        version_file = tmp_path / "src" / "clawrium" / "_version.py"
        content = version_file.read_text()
        # Must compile without error.
        compile(content, str(version_file), "exec")
        # Must contain expected constants when exec'd.
        ns: dict[str, object] = {}
        exec(content, ns)  # noqa: S102
        assert "__version__" in ns
        assert "__git_sha__" in ns
        assert ns["__git_sha__"] == "deadbee"

    def test_preserves_existing_sha(self, _hook, tmp_path: Path) -> None:
        """B1: if _version.py already has a real SHA, initialize must keep it."""
        version_file = tmp_path / "src" / "clawrium" / "_version.py"
        version_file.write_text(
            '# AUTO-GENERATED\n__version__ = "26.6.4"\n__git_sha__ = "a1b2c3d"\n'
        )
        _hook.initialize("0.0.0", {})
        content = version_file.read_text()
        # W2: use exec() to check actual values, not string matching.
        ns: dict[str, object] = {}
        exec(content, ns)  # noqa: S102
        assert ns["__git_sha__"] == "a1b2c3d"

    def test_overwrites_unknown_sha(self, _hook, tmp_path: Path) -> None:
        """If existing _version.py has 'unknown', initialize regenerates."""
        version_file = tmp_path / "src" / "clawrium" / "_version.py"
        version_file.write_text(
            '# AUTO-GENERATED\n__version__ = "26.6.4"\n__git_sha__ = "unknown"\n'
        )
        _hook.initialize("26.6.4", {})
        content = version_file.read_text()
        ns: dict[str, object] = {}
        exec(content, ns)  # noqa: S102
        assert ns["__git_sha__"] == "deadbee"

    def test_skips_rewrite_when_identical(self, _hook, tmp_path: Path) -> None:
        """W3: initialize must not rewrite _version.py when content is identical."""
        version_file = tmp_path / "src" / "clawrium" / "_version.py"
        version_file.write_text(
            '# AUTO-GENERATED by hatch_build.py — do not edit.\n'
            '__version__ = "1.0.0"\n'
            '__git_sha__ = "deadbee"\n'
        )
        original_mtime = version_file.stat().st_mtime_ns
        _hook.initialize("1.0.0", {})
        assert version_file.stat().st_mtime_ns == original_mtime

    def test_uses_build_version_param(self, _hook, tmp_path: Path) -> None:
        """S1: initialize must prefer build_version over _get_version()."""
        _hook.initialize("42.0.0", {})
        version_file = tmp_path / "src" / "clawrium" / "_version.py"
        content = version_file.read_text()
        ns: dict[str, object] = {}
        exec(content, ns)  # noqa: S102
        assert ns["__version__"] == "42.0.0"


# ---------------------------------------------------------------------------
# _warn_git
# ---------------------------------------------------------------------------

class TestWarnGit:
    """W2: _warn_git must warn normally but raise with CLAWRIUM_REQUIRE_GIT_SHA."""

    def test_warns_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAWRIUM_REQUIRE_GIT_SHA", raising=False)
        import warnings

        from hatch_build import _warn_git

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _warn_git("test message")
        assert len(w) == 1
        assert "test message" in str(w[0].message)

    def test_raises_with_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAWRIUM_REQUIRE_GIT_SHA", "1")
        from hatch_build import _warn_git

        with pytest.raises(RuntimeError, match="test message"):
            _warn_git("test message")

"""Tests for dependency detection."""

from pathlib import Path
from unittest.mock import patch

import pytest

from clawrium.core.deps import (
    DependencyStatus,
    check_ansible,
    check_ansible_runner,
    check_all_dependencies,
    check_python,
)


class TestDependencyStatus:
    """Tests for DependencyStatus dataclass."""

    def test_has_required_fields(self) -> None:
        """DependencyStatus should have all required fields."""
        status = DependencyStatus(
            name="test",
            found=True,
            version="1.0.0",
            path="/usr/bin/test",
            install_hint="",
        )
        assert status.name == "test"
        assert status.found is True
        assert status.version == "1.0.0"
        assert status.path == "/usr/bin/test"
        assert status.install_hint == ""


class TestCheckPython:
    """Tests for check_python function."""

    def test_python_always_found(self) -> None:
        """Python should always be found (we're running in it)."""
        result = check_python()
        assert result.found is True
        assert result.name == "python"

    def test_python_has_version(self) -> None:
        """Python check should include version."""
        result = check_python()
        assert result.version is not None
        assert "3." in result.version  # Python 3.x


class TestCheckAnsible:
    """Tests for check_ansible function."""

    def test_ansible_found_when_exists(self) -> None:
        """Should return found=True when ansible binary exists."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/ansible"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "ansible [core 2.15.0]"

                result = check_ansible()

                assert result.found is True
                assert result.name == "ansible"
                assert result.path == "/usr/bin/ansible"

    def test_ansible_missing_when_not_exists(self) -> None:
        """Should return found=False when ansible binary not found."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            result = check_ansible()

            assert result.found is False
            assert result.name == "ansible"
            assert result.path is None

    def test_ansible_install_hint_recommends_pipx(self) -> None:
        """Install hint should recommend pipx for Ubuntu compatibility."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            result = check_ansible()

            assert "pipx" in result.install_hint.lower()


class TestCheckAnsibleRunner:
    """Tests for check_ansible_runner function."""

    def test_ansible_runner_found_when_importable(self) -> None:
        """Should return found=True when ansible_runner is importable."""
        # ansible_runner is a project dependency, so it should be importable
        result = check_ansible_runner()
        assert result.found is True
        assert result.name == "ansible-runner"

    def test_ansible_runner_missing_when_not_importable(self) -> None:
        """Should return found=False when import fails."""
        with patch.dict("sys.modules", {"ansible_runner": None}):
            with patch("importlib.util.find_spec") as mock_find:
                mock_find.return_value = None

                result = check_ansible_runner()

                assert result.found is False
                assert (
                    "uv add" in result.install_hint
                    or "pip install" in result.install_hint
                )


class TestCheckAllDependencies:
    """Tests for check_all_dependencies function."""

    def test_returns_list_of_three(self) -> None:
        """Should return status for python, ansible, and ansible-runner."""
        result = check_all_dependencies()
        assert len(result) == 3
        names = [dep.name for dep in result]
        assert "python" in names
        assert "ansible" in names
        assert "ansible-runner" in names

    def test_all_are_dependency_status(self) -> None:
        """All items should be DependencyStatus objects."""
        result = check_all_dependencies()
        for dep in result:
            assert isinstance(dep, DependencyStatus)

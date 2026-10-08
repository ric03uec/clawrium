"""Tests for config directory management."""

import errno
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import config as config_module
from clawrium.core.config import get_config_dir, init_config_dir


class TestGetConfigDir:
    """Tests for get_config_dir function."""

    def test_returns_path_ending_in_clawrium(self, tmp_config_dir: Path) -> None:
        """Config dir path should end with 'clawrium'."""
        result = get_config_dir()
        assert result.name == "clawrium"

    def test_uses_xdg_config_home_when_set(self, tmp_config_dir: Path) -> None:
        """Should use XDG_CONFIG_HOME environment variable."""
        result = get_config_dir()
        assert result == tmp_config_dir / "clawrium"

    def test_falls_back_to_home_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should fall back to ~/.config when XDG_CONFIG_HOME not set."""
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = get_config_dir()
        assert result == Path.home() / ".config" / "clawrium"

    def test_ignores_relative_xdg_config_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should ignore XDG_CONFIG_HOME if it's a relative path."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
        result = get_config_dir()
        assert result == Path.home() / ".config" / "clawrium"


class TestInitConfigDir:
    """Tests for init_config_dir function."""

    def test_creates_directory(self, isolated_config: Path) -> None:
        """Should create the config directory."""
        assert not isolated_config.exists()
        init_config_dir()
        assert isolated_config.exists()
        assert isolated_config.is_dir()

    def test_returns_created_path(self, isolated_config: Path) -> None:
        """Should return the path to the created directory."""
        result = init_config_dir()
        assert result == isolated_config

    def test_idempotent(self, isolated_config: Path) -> None:
        """Should not error if directory already exists."""
        init_config_dir()
        # Second call should not raise
        result = init_config_dir()
        assert result == isolated_config
        assert isolated_config.is_dir()

    def test_creates_directory_with_0700_permissions(
        self, isolated_config: Path
    ) -> None:
        """Should create directory with restrictive 0700 permissions."""
        assert not isolated_config.exists()
        init_config_dir()
        assert isolated_config.exists()
        mode = isolated_config.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"

    def test_fixes_existing_permissive_directory(self, isolated_config: Path) -> None:
        """Should correct permissions on existing directory with wrong mode."""
        # Create directory with permissive 0755 permissions
        isolated_config.mkdir(parents=True, mode=0o755)
        # Fixture setup must not inherit a concurrent caller's process umask.
        os.chmod(isolated_config, 0o755)
        assert (isolated_config.stat().st_mode & 0o777) == 0o755

        # init_config_dir should correct permissions
        init_config_dir()
        mode = isolated_config.stat().st_mode & 0o777
        assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"

    def test_tightens_writable_config_leaf_beneath_private_ancestor(
        self, isolated_config
    ) -> None:
        """A private parent prevents other users from pre-seeding its leaf."""
        isolated_config.mkdir(parents=True)
        os.chmod(isolated_config, 0o775)

        assert init_config_dir() == isolated_config
        assert (isolated_config.stat().st_mode & 0o777) == 0o700

    def test_rejects_writable_config_leaf_beneath_public_ancestry(
        self, isolated_config, monkeypatch
    ) -> None:
        """A public sticky chain cannot make pre-existing leaf contents safe."""
        isolated_config.mkdir(parents=True)
        secret = isolated_config / "preseeded"
        secret.write_text("attacker-controlled")
        os.chmod(isolated_config, 0o777)
        leaf_inode = isolated_config.stat().st_ino
        tmp_inode = os.stat("/tmp").st_ino
        real_fstat = os.fstat

        def public_ancestry_fstat(fd):
            metadata = real_fstat(fd)
            if metadata.st_ino == leaf_inode:
                return metadata
            if metadata.st_ino == tmp_inode:
                return SimpleNamespace(
                    st_uid=0, st_mode=stat.S_IFDIR | stat.S_ISVTX | 0o777
                )
            return SimpleNamespace(st_uid=os.geteuid(), st_mode=stat.S_IFDIR | 0o755)

        monkeypatch.setattr(config_module.os, "fstat", public_ancestry_fstat)

        with pytest.raises(PermissionError, match="writable config directory"):
            init_config_dir()

        assert (isolated_config.stat().st_mode & 0o777) == 0o777
        assert secret.read_text() == "attacker-controlled"

    def test_rejects_parent_components_before_traversal(
        self, tmp_path, monkeypatch
    ) -> None:
        """A lexical parent component cannot discard private-ancestor trust."""
        private = tmp_path / "private"
        public = tmp_path / "public"
        config_dir = private / ".." / "public" / "clawrium"
        private.mkdir(mode=0o700)
        os.chmod(private, 0o700)
        public.mkdir(mode=0o755)
        config_leaf = public / "clawrium"
        config_leaf.mkdir(mode=0o777)
        os.chmod(config_leaf, 0o777)
        marker = config_leaf / "preseeded"
        marker.write_text("attacker-controlled")
        monkeypatch.setattr(config_module, "get_config_dir", lambda: config_dir)
        monkeypatch.setattr(
            config_module.os,
            "mkdir",
            lambda *_args, **_kwargs: pytest.fail("must reject before mkdir"),
        )
        monkeypatch.setattr(
            config_module.os,
            "chmod",
            lambda *_args, **_kwargs: pytest.fail("must reject before chmod"),
        )

        with pytest.raises(PermissionError, match="XDG_CONFIG_HOME"):
            init_config_dir()

        assert (config_leaf.stat().st_mode & 0o777) == 0o777
        assert marker.read_text() == "attacker-controlled"

    def test_creates_only_new_ancestors_privately(self, tmp_path) -> None:
        """New config ancestors stay private under a permissive caller umask."""
        existing_parent = tmp_path / "existing"
        existing_parent.mkdir(mode=0o755)
        os.chmod(existing_parent, 0o755)
        xdg_home = existing_parent / "new"
        config_dir = xdg_home / "clawrium"
        environment = {**os.environ, "XDG_CONFIG_HOME": str(xdg_home)}
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; from clawrium.core.config import init_config_dir; "
                "os.umask(0); init_config_dir()",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        assert (existing_parent.stat().st_mode & 0o777) == 0o755
        assert (config_dir.parent.stat().st_mode & 0o777) == 0o700
        assert (config_dir.stat().st_mode & 0o777) == 0o700

    def test_creates_private_ancestors_under_restrictive_umask(self, tmp_path) -> None:
        """A restrictive caller umask cannot prevent nested creation."""
        xdg_home = tmp_path / "new" / "config"
        config_dir = xdg_home / "clawrium"
        environment = {**os.environ, "XDG_CONFIG_HOME": str(xdg_home)}
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; from clawrium.core.config import init_config_dir; "
                "os.umask(0o777); init_config_dir()",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        assert (xdg_home.parent.stat().st_mode & 0o777) == 0o700
        assert (xdg_home.stat().st_mode & 0o777) == 0o700
        assert (config_dir.stat().st_mode & 0o777) == 0o700

    def test_recovers_when_concurrent_creator_wins_missing_ancestor(
        self, tmp_path, monkeypatch
    ) -> None:
        """A concurrent private-parent creator is accepted without chmod."""
        base = tmp_path / "base"
        base.mkdir()
        os.chmod(base, 0o755)
        config_dir = base / "new" / "clawrium"
        monkeypatch.setattr(config_module, "get_config_dir", lambda: config_dir)
        real_mkdir = os.mkdir
        raced = False

        def concurrent_mkdir(path, mode=0o777, *, dir_fd=None):
            nonlocal raced
            if path == "new" and not raced:
                raced = True
                real_mkdir(path, mode=0o755, dir_fd=dir_fd)
                raise FileExistsError(path)
            return real_mkdir(path, mode=mode, dir_fd=dir_fd)

        monkeypatch.setattr(config_module.os, "mkdir", concurrent_mkdir)
        assert init_config_dir() == config_dir
        assert (config_dir.parent.stat().st_mode & 0o777) == 0o755
        assert (config_dir.stat().st_mode & 0o777) == 0o700

    def test_rejects_regular_file_concurrent_collision(
        self, tmp_path, monkeypatch
    ) -> None:
        """A regular-file replacement loses a deterministic mkdir race."""
        base = tmp_path / "base"
        base.mkdir()
        os.chmod(base, 0o755)
        replacement = base / "new"
        monkeypatch.setattr(
            config_module, "get_config_dir", lambda: replacement / "clawrium"
        )
        real_mkdir = os.mkdir
        raced = False

        def regular_file_race(path, mode=0o777, *, dir_fd=None):
            nonlocal raced
            if path == "new" and not raced:
                raced = True
                replacement.write_text("attacker-controlled")
                raise FileExistsError(path)
            return real_mkdir(path, mode=mode, dir_fd=dir_fd)

        monkeypatch.setattr(config_module.os, "mkdir", regular_file_race)

        with pytest.raises(FileExistsError):
            init_config_dir()

        assert raced
        assert replacement.read_text() == "attacker-controlled"

    def test_allows_config_leaf_owned_by_nonroot_caller(
        self, isolated_config, monkeypatch
    ) -> None:
        """A normal user can initialize their own pre-existing config leaf."""
        isolated_config.mkdir(parents=True)
        os.chmod(isolated_config, 0o700)
        monkeypatch.setattr(config_module.os, "geteuid", os.getuid)

        assert init_config_dir() == isolated_config

    def test_rejects_other_owned_leaf_before_chmod_when_running_as_root(
        self, tmp_path, monkeypatch
    ) -> None:
        """Simulated root leaves an attacker-owned existing config leaf untouched."""
        config_dir = tmp_path / "config" / "clawrium"
        config_dir.mkdir(parents=True)
        leaf_inode = config_dir.stat().st_ino
        real_fstat = os.fstat
        monkeypatch.setattr(config_module, "get_config_dir", lambda: config_dir)
        monkeypatch.setattr(config_module.os, "geteuid", lambda: 0)
        monkeypatch.setattr(
            config_module.os,
            "fstat",
            lambda fd: SimpleNamespace(
                st_uid=501 if real_fstat(fd).st_ino == leaf_inode else 0,
                st_mode=stat.S_IFDIR | 0o755,
            ),
        )
        monkeypatch.setattr(
            config_module.os,
            "fchmod",
            lambda *_args: pytest.fail("must validate ownership before chmod"),
        )

        with pytest.raises(
            PermissionError, match="config directory owned by another user"
        ):
            init_config_dir()

    def test_rejects_writable_nonsticky_ancestor_when_running_as_root(
        self, tmp_path, monkeypatch
    ) -> None:
        """Simulated root rejects a writable ancestor even when root owns it."""
        directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            monkeypatch.setattr(config_module.os, "geteuid", lambda: 0)
            monkeypatch.setattr(
                config_module.os,
                "fstat",
                lambda _fd: SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o777),
            )

            with pytest.raises(PermissionError, match="writable config ancestor"):
                config_module._validate_directory_owner(
                    directory_fd, is_config_leaf=False, created=False
                )
        finally:
            os.close(directory_fd)

    def test_rejects_writable_nonsticky_operator_ancestor(
        self, tmp_path, monkeypatch
    ) -> None:
        """Other UIDs cannot replace paths beneath a permissive operator directory."""
        directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            monkeypatch.setattr(config_module.os, "geteuid", os.getuid)
            monkeypatch.setattr(
                config_module.os,
                "fstat",
                lambda _fd: SimpleNamespace(
                    st_uid=os.getuid(), st_mode=stat.S_IFDIR | 0o777
                ),
            )

            with pytest.raises(PermissionError, match="writable config ancestor"):
                config_module._validate_directory_owner(
                    directory_fd, is_config_leaf=False, created=False
                )
        finally:
            os.close(directory_fd)

    def test_rejects_foreign_owned_nonsticky_ancestor_for_nonroot_user(
        self, tmp_path, monkeypatch
    ) -> None:
        """An unrelated user's ancestor can redirect later pathname writes."""
        directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            monkeypatch.setattr(config_module.os, "geteuid", os.getuid)
            monkeypatch.setattr(
                config_module.os,
                "fstat",
                lambda _fd: SimpleNamespace(st_uid=501, st_mode=stat.S_IFDIR | 0o755),
            )

            with pytest.raises(PermissionError, match="ancestor owned by another user"):
                config_module._validate_directory_owner(
                    directory_fd, is_config_leaf=False, created=False
                )
        finally:
            os.close(directory_fd)

    def test_rejects_foreign_owned_sticky_ancestor_before_child_creation(
        self, tmp_path, monkeypatch
    ) -> None:
        """A foreign sticky owner could replace a newly-created child."""
        base = tmp_path / "base"
        foreign = base / "foreign"
        target = tmp_path / "target"
        foreign.mkdir(parents=True)
        os.chmod(base, 0o700)
        target.mkdir(mode=0o755)
        os.chmod(target, 0o755)
        foreign_inode = foreign.stat().st_ino
        real_fstat = os.fstat
        monkeypatch.setattr(
            config_module, "get_config_dir", lambda: foreign / "new" / "clawrium"
        )
        monkeypatch.setattr(config_module.os, "geteuid", os.getuid)
        monkeypatch.setattr(
            config_module.os,
            "fstat",
            lambda fd: (
                SimpleNamespace(
                    st_uid=501,
                    st_mode=stat.S_IFDIR | stat.S_ISVTX | 0o777,
                )
                if real_fstat(fd).st_ino == foreign_inode
                else real_fstat(fd)
            ),
        )
        monkeypatch.setattr(
            config_module.os,
            "fchmod",
            lambda *_args: pytest.fail("must reject ancestor before child chmod"),
        )

        with pytest.raises(PermissionError, match="ancestor owned by another user"):
            init_config_dir()

        assert not (foreign / "new").exists()
        assert (target.stat().st_mode & 0o777) == 0o755

    def test_allows_root_owned_sticky_ancestor_when_running_as_root(
        self, tmp_path, monkeypatch
    ) -> None:
        """A sticky directory such as /tmp protects root's child name."""
        directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            monkeypatch.setattr(config_module.os, "geteuid", lambda: 0)
            monkeypatch.setattr(
                config_module.os,
                "fstat",
                lambda _fd: SimpleNamespace(
                    st_uid=0, st_mode=stat.S_IFDIR | stat.S_ISVTX | 0o777
                ),
            )

            config_module._validate_directory_owner(
                directory_fd, is_config_leaf=False, created=False
            )
        finally:
            os.close(directory_fd)

    def test_canonicalizes_trusted_macos_var_symlink(self, monkeypatch) -> None:
        """macOS's root-owned /var compatibility link remains supported."""
        monkeypatch.setattr(config_module.sys, "platform", "darwin")
        monkeypatch.setattr(
            config_module.os,
            "lstat",
            lambda _path: SimpleNamespace(st_uid=0, st_mode=stat.S_IFLNK),
        )
        monkeypatch.setattr(config_module.os, "readlink", lambda _path: "private/var")

        path = Path("/var/folders/example/T/config/clawrium")
        assert config_module._canonicalize_darwin_var(path) == Path(
            "/private/var/folders/example/T/config/clawrium"
        )

    def test_does_not_trust_noncanonical_macos_var_symlink(self, monkeypatch) -> None:
        """Only macOS's root-owned /var -> private/var link is exempted."""
        monkeypatch.setattr(config_module.sys, "platform", "darwin")
        monkeypatch.setattr(
            config_module.os,
            "lstat",
            lambda _path: SimpleNamespace(st_uid=501, st_mode=stat.S_IFLNK),
        )
        monkeypatch.setattr(config_module.os, "readlink", lambda _path: "private/var")

        path = Path("/var/folders/example/T/config/clawrium")
        assert config_module._canonicalize_darwin_var(path) == path

    def test_rejects_symlinked_missing_ancestor(self, tmp_path, monkeypatch) -> None:
        """Symlink substitution cannot redirect the config directory."""
        base = tmp_path / "base"
        target = tmp_path / "target"
        base.mkdir()
        os.chmod(base, 0o755)
        target.mkdir(mode=0o755)
        os.chmod(target, 0o755)
        config_dir = base / "new" / "clawrium"
        monkeypatch.setattr(config_module, "get_config_dir", lambda: config_dir)
        real_mkdir = os.mkdir
        raced = False

        def symlink_race(path, mode=0o777, *, dir_fd=None):
            nonlocal raced
            if path == "new" and not raced:
                raced = True
                os.symlink(str(target), path, dir_fd=dir_fd)
                raise FileExistsError(path)
            return real_mkdir(path, mode=mode, dir_fd=dir_fd)

        real_open = os.open
        rejected_errnos: list[int] = []

        def recording_open(*args, **kwargs):
            try:
                return real_open(*args, **kwargs)
            except OSError as exc:
                rejected_errnos.append(exc.errno)
                raise

        monkeypatch.setattr(config_module.os, "mkdir", symlink_race)
        monkeypatch.setattr(config_module.os, "open", recording_open)
        with pytest.raises(FileExistsError):
            init_config_dir()
        assert raced
        # O_NOFOLLOW|O_DIRECTORY rejects the injected symlink with ENOTDIR
        # on Linux and ELOOP on platforms that report the nofollow violation.
        assert rejected_errnos[-1] in {errno.ENOTDIR, errno.ELOOP}
        assert (target.stat().st_mode & 0o777) == 0o755

    def test_never_changes_process_umask(self, isolated_config, monkeypatch) -> None:
        """Config initialization must not mutate process-wide filesystem state."""
        monkeypatch.setattr(
            config_module.os,
            "umask",
            lambda _mode: pytest.fail("init_config_dir must not change process umask"),
        )

        assert init_config_dir() == isolated_config

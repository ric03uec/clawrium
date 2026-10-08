"""Configuration directory management for Clawrium."""

import errno
import os
import stat
import sys
from pathlib import Path

__all__ = ["get_config_dir", "init_config_dir"]


def get_config_dir() -> Path:
    """Get the Clawrium configuration directory path.

    Respects XDG_CONFIG_HOME if set to an absolute path,
    otherwise falls back to ~/.config/clawrium.

    Returns:
        Path to the clawrium configuration directory.
    """
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config and Path(xdg_config).is_absolute():
        base = Path(xdg_config)
    else:
        base = Path.home() / ".config"
    return base / "clawrium"


def _canonicalize_darwin_var(path: Path) -> Path:
    """Map macOS's trusted /var compatibility link without following user links."""
    var = Path("/var")
    if sys.platform != "darwin" or not path.is_relative_to(var):
        return path
    try:
        metadata = os.lstat(var)
    except OSError:
        return path
    if (
        metadata.st_uid == 0
        and stat.S_ISLNK(metadata.st_mode)
        and os.readlink(var) == "private/var"
    ):
        return Path("/private/var") / path.relative_to(var)
    return path


def _validate_directory_owner(
    directory_fd: int,
    *,
    is_config_leaf: bool,
    created: bool,
    has_trusted_private_ancestor: bool = False,
) -> None:
    """Reject directories whose ownership cannot safely protect config secrets."""
    metadata = os.fstat(directory_fd)
    owner = metadata.st_uid
    effective_user = os.geteuid()
    if is_config_leaf and owner != effective_user:
        raise PermissionError(
            "refusing config directory owned by another user; "
            "set XDG_CONFIG_HOME to a directory owned by the invoking user"
        )
    if effective_user == 0 and not created and owner != 0:
        raise PermissionError(
            "refusing user-owned config ancestor while running as root; "
            "set XDG_CONFIG_HOME to a root-owned absolute directory"
        )
    if not created and owner not in {effective_user, 0}:
        raise PermissionError(
            "refusing config ancestor owned by another user; "
            "set XDG_CONFIG_HOME to a private absolute directory"
        )
    writable_by_others = metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if (
        not created
        and is_config_leaf
        and writable_by_others
        and not has_trusted_private_ancestor
    ):
        raise PermissionError(
            "refusing writable config directory; "
            "set XDG_CONFIG_HOME to a private absolute directory"
        )
    if (
        not created
        and not is_config_leaf
        and writable_by_others
        and not metadata.st_mode & stat.S_ISVTX
    ):
        raise PermissionError(
            "refusing writable config ancestor; "
            "set XDG_CONFIG_HOME to a private absolute directory"
        )


def init_config_dir() -> Path:
    """Create and return the configuration directory.

    Creates missing directories with private permissions without changing the
    process-wide umask. Existing parent directories are left unchanged while
    the config directory itself is always corrected to 0700.

    Returns:
        Path to the created configuration directory.
    """
    config_dir = _canonicalize_darwin_var(get_config_dir())
    if not config_dir.is_absolute():  # Defensive: get_config_dir promises this.
        raise ValueError("configuration directory must be absolute")
    if ".." in config_dir.parts:
        raise PermissionError(
            "refusing configuration path containing '..'; "
            "set XDG_CONFIG_HOME to a real absolute directory without '..'"
        )

    nofollow = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    has_trusted_private_ancestor = False
    try:
        components = config_dir.parts[1:]
        for index, component in enumerate(components):
            created = False
            collision: FileExistsError | None = None
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory_fd)
                created = True
            except FileExistsError as exc:
                # A concurrent creator may have won. Validate the replacement
                # without following symlinks before continuing.
                collision = exc

            if created:
                # Correct an arbitrarily restrictive caller umask before
                # opening the child: mode 000 would otherwise prevent the
                # descriptor-relative validation below.
                # This is descriptor-relative and happens only beneath a
                # validated private or sticky parent. The subsequent nofollow
                # open rejects a replacement before it can be used.
                os.chmod(component, 0o700, dir_fd=directory_fd)

            try:
                child_fd = os.open(component, nofollow, dir_fd=directory_fd)
            except OSError as exc:
                if collision is not None and exc.errno in {errno.ENOTDIR, errno.ELOOP}:
                    raise collision from None
                raise
            os.close(directory_fd)
            directory_fd = child_fd
            is_config_leaf = index == len(components) - 1
            _validate_directory_owner(
                directory_fd,
                is_config_leaf=is_config_leaf,
                created=created,
                has_trusted_private_ancestor=has_trusted_private_ancestor,
            )
            metadata = os.fstat(directory_fd)
            if (
                not is_config_leaf
                and metadata.st_uid in {os.geteuid(), 0}
                and not metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
            ):
                has_trusted_private_ancestor = True
            if created:
                # mkdir is filtered through the caller's umask; correct only
                # directories created by this invocation before descending.
                os.fchmod(directory_fd, 0o700)

        # Correct the config leaf even when it predated this invocation.
        os.fchmod(directory_fd, 0o700)
    finally:
        os.close(directory_fd)
    return config_dir

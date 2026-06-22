"""Clawrium - CLI tool for managing AI assistant fleets."""

_UNKNOWN = "unknown"

try:
    from clawrium._version import __git_sha__, __version__
except (ImportError, SyntaxError):  # W4: also catch half-written _version.py
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("clawrium")
    except PackageNotFoundError:
        __version__ = "0.0.0"
    __git_sha__ = _UNKNOWN


def format_version() -> str:
    """Return the user-facing version string (B2 + W5).

    When the git SHA is the ``"unknown"`` sentinel (e.g. editable install
    or sdist→wheel rebuild without ``.git``), the ``(git: …)`` suffix is
    suppressed so the output is clean instead of showing implementation
    noise like ``clawctl 26.6.4 (git: unknown)``.
    """
    if __git_sha__ == _UNKNOWN:
        return f"clawctl {__version__}"
    return f"clawctl {__version__} (git: {__git_sha__})"

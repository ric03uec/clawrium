"""Clawrium - CLI tool for managing AI assistant fleets."""

try:
    from clawrium._version import __git_sha__, __version__
except ImportError:
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("clawrium")
    except PackageNotFoundError:
        __version__ = "0.0.0"
    __git_sha__ = "unknown"

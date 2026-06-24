"""Normalize the operator's `sys.platform` value for openclaw pairing.

Python `sys.platform` returns versioned strings on some POSIX flavors:

- Linux         → `linux`
- macOS         → `darwin`
- Windows       → `win32`
- FreeBSD 13.x  → `freebsd13`   (versioned!)
- FreeBSD 14.x  → `freebsd14`   (versioned!)
- AIX 7.x       → `aix7`        (versioned!)
- OpenBSD       → `openbsd6.9`  (versioned!)

Node's `process.platform` returns BARE family names on the same OSes
(`freebsd`, `aix`, `openbsd`). The openclaw daemon stores whatever
string the pair script (Node) sends on the device record and rejects
any subsequent connect that reports a different `platform` value as
"device identity changed".

Without normalization, a Python interpreter upgrade on a FreeBSD
operator (3.11 on freebsd13 → 3.12 on freebsd14, both perfectly fine)
would trigger the exact "device identity changed" rejection the
operator-platform threading was written to prevent.

`normalize()` strips trailing version digits and the optional `.minor`
suffix so Python's value matches Node's bare family name. The known
safe set (`linux`, `darwin`, `win32`) passes through unchanged.
"""

from __future__ import annotations

import re
import sys

# Strip trailing major[.minor[.patch]] version suffix off platform
# names like "freebsd13", "aix7", "openbsd6.9". Anchored at the end
# so a legitimate `linux` or `darwin` is left alone.
_VERSION_SUFFIX_RE = re.compile(r"\d+(\.\d+)*$")

# Values that must pass through verbatim — either already bare-family
# (linux/darwin) OR a special name where the trailing digit is part of
# the identifier itself (win32: the "32" is the Win32 API family, not
# a version). Node's `process.platform` also returns `win32`, so the
# two sides agree.
_PASSTHROUGH = frozenset({"linux", "darwin", "win32", "cygwin"})


def normalize(value: str | None = None) -> str:
    """Return the bare platform family for `value` (default `sys.platform`).

    Examples:
        >>> normalize("linux")        # passes through
        'linux'
        >>> normalize("darwin")       # passes through
        'darwin'
        >>> normalize("win32")        # passes through (Node also returns 'win32')
        'win32'
        >>> normalize("freebsd13")    # strip version
        'freebsd'
        >>> normalize("openbsd6.9")   # strip version
        'openbsd'

    A non-string `value` falls back to `sys.platform` so callers can
    pass `os.environ.get(...)` results without an extra guard.
    """
    raw = value if isinstance(value, str) and value else sys.platform
    if raw in _PASSTHROUGH:
        return raw
    return _VERSION_SUFFIX_RE.sub("", raw)


__all__ = ["normalize"]

"""STATUS column formatter.

Plan §6.13:

| Token         | TTY color |
|---------------|-----------|
| running       | green     |
| degraded      | yellow    |
| stopped       | red       |
| pending       | yellow    |
| onboarding    | cyan      |
| ready         | blue      |
| installing    | yellow    |
| failed        | red       |
| unknown       | yellow    |

Coloring rules:

- On a TTY → wrap with the matching ANSI color sequence.
- Non-TTY (pipe / file) → emit the raw token, no ANSI.
- `NO_COLOR=1` (de-facto standard) → emit the raw token regardless.
- `force_color=True` overrides the TTY check (used by tests).

Unknown tokens are returned uncolored. This is a deliberate choice —
the status vocabulary is the source of truth; surfacing an unrecognized
token without color makes the gap visible in fleet output.
"""

import os
import sys
from typing import IO, Optional

from clawrium.cli.output._sanitize import sanitize

_COLORS = {
    "running": "32",  # green
    "degraded": "33",  # yellow
    "stopped": "31",  # red
    "pending": "33",  # yellow
    "onboarding": "36",  # cyan
    "ready": "34",  # blue
    "installing": "33",  # yellow
    "failed": "31",  # red
    "unknown": "33",  # yellow
}


def _color_enabled(
    stream: Optional[IO[str]],
    *,
    force_color: bool,
) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if force_color:
        return True
    target = stream if stream is not None else sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


def format_status(
    token: str,
    *,
    stream: Optional[IO[str]] = None,
    force_color: bool = False,
) -> str:
    """Return `token` wrapped in the matching ANSI color, or raw.

    Unknown tokens pass through sanitize() before returning (#507 ATX
    iter-2 W7): a compromised agent host writing a crafted `status`
    field to hosts.json could otherwise smuggle bidi overrides into
    the terminal via the "unknown token" fallthrough.
    """
    code = _COLORS.get(token)
    if code is None:
        return sanitize(token)
    if not _color_enabled(stream, force_color=force_color):
        return token
    return f"\x1b[{code}m{token}\x1b[0m"

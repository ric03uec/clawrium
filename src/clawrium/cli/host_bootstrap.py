"""OS-family detection for host bootstrap.

Single small helper, called from `cli/clawctl/host/create.py:_run_bootstrap`
right before dispatching to the per-OS bootstrap implementation.

Kept separate from `cli/host.py` (Linux bootstrap) and `cli/host_macos.py`
(Mac bootstrap, added in step 3) because OS detection itself is OS-agnostic
and shouldn't live inside either.
"""

from __future__ import annotations

import getpass
from typing import Literal

import paramiko

OSFamily = Literal["linux", "darwin"]


class OSDetectionError(Exception):
    """Raised when the remote `uname -s` returns an unsupported family."""


def detect_remote_os_family(hostname: str, user: str | None, *, timeout: int = 10) -> OSFamily:
    """SSH to `user@hostname` with the local user's default keys and run `uname -s`.

    Returns "linux" or "darwin". Anything else raises `OSDetectionError` so
    the caller can fail with a clear message rather than guessing.

    Connection failures (auth, host key, network) propagate as paramiko
    exceptions — the caller already handles them in the bootstrap flow.
    """
    connection_user = user or getpass.getuser()
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=hostname, username=connection_user, timeout=timeout)
        _, stdout, _ = client.exec_command("uname -s", timeout=timeout)
        raw = stdout.read().decode().strip()
    finally:
        client.close()

    if raw == "Linux":
        return "linux"
    if raw == "Darwin":
        return "darwin"
    raise OSDetectionError(
        f"unsupported remote OS: uname -s returned {raw!r}. "
        f"clawrium supports Linux and macOS targets."
    )

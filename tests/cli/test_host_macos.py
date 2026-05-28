"""Unit tests for cli/host_macos.py (issue #469, step 3).

E2E lives separately (tests/integration/test_macos_e2e_real.py, step 11).
These tests cover the pure-Python helpers that don't require an SSH
session against a real Mac:
  - `_pick_free_uid`: parses `dscl . -list /Users UniqueID` output
  - module import + symbol surface (so the dispatcher's lazy import works)
"""

from io import StringIO

from clawrium.cli import host_macos
from clawrium.cli.host_macos import (
    _XCLM_UID_MIN,
    _existing_user_uid,
    _pick_free_uid,
)


class _FakeChannelObj:
    def __init__(self, exit_status: int = 0):
        self._exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self._exit_status


class _FakeChannel:
    def __init__(self, output: str, exit_status: int = 0):
        self._out = output.encode()
        self.channel = _FakeChannelObj(exit_status)

    def read(self) -> bytes:
        return self._out


class _FakeSSHClient:
    """Minimal stand-in returning a single canned response per exec.

    For `_existing_user_uid`, the exit_status arg lets a test fake a
    "user missing" response (dscl returns non-zero).
    """

    def __init__(self, output: str, exit_status: int = 0):
        self._output = output
        self._exit = exit_status

    def exec_command(self, cmd):  # noqa: D401, ANN001
        stdin = StringIO()
        return (
            stdin,
            _FakeChannel(self._output, self._exit),
            _FakeChannel("", self._exit),
        )


def test_pick_free_uid_returns_floor_on_empty_host():
    client = _FakeSSHClient("")
    assert _pick_free_uid(client, _XCLM_UID_MIN) == _XCLM_UID_MIN


def test_pick_free_uid_skips_existing():
    raw = "\n".join(
        [
            "_appleeventsd  55",
            "_assetcache    235",
            "root           0",
            "devashish      501",
            "fake_user      600",
            "another        601",
        ]
    )
    client = _FakeSSHClient(raw)
    assert _pick_free_uid(client, 600) == 602


def test_pick_free_uid_ignores_garbage_lines():
    raw = "\n".join(
        [
            "# comment header",
            "single_col",
            "valid_user 600",
            "noisy junk_uid",  # non-int second col
        ]
    )
    client = _FakeSSHClient(raw)
    assert _pick_free_uid(client, 600) == 601


def test_pick_free_uid_above_floor_respects_lower_uids():
    raw = "root 0\nadmin 501\n"
    client = _FakeSSHClient(raw)
    # 0 and 501 are below floor and irrelevant
    assert _pick_free_uid(client, 600) == 600


def test_init_macos_is_importable_and_exported():
    """The dispatcher does `from clawrium.cli.host_macos import init_macos`.

    Regression: keep this importable so the lazy import in
    `_run_bootstrap` doesn't blow up the Linux code path.
    """
    assert hasattr(host_macos, "init_macos")
    assert callable(host_macos.init_macos)
    assert "init_macos" in host_macos.__all__


def test_xclm_uid_floor_avoids_apple_reserved_range():
    """macOS reserves 500–599 for Apple system accounts."""
    assert _XCLM_UID_MIN >= 600


def test_existing_user_uid_returns_uid_when_present():
    """`dscl -read /Users/<n> UniqueID` returns one line: 'UniqueID: 600'."""
    client = _FakeSSHClient("UniqueID: 600", exit_status=0)
    assert _existing_user_uid(client, "xclm") == 600


def test_existing_user_uid_returns_none_when_missing():
    """When the user doesn't exist, dscl exits non-zero."""
    client = _FakeSSHClient(
        "<dscl_cmd> DS Error: -14136 (eDSRecordNotFound)\n", exit_status=1
    )
    assert _existing_user_uid(client, "xclm") is None


def test_existing_user_uid_returns_none_when_uid_garbage():
    client = _FakeSSHClient("UniqueID: not-an-int", exit_status=0)
    assert _existing_user_uid(client, "xclm") is None

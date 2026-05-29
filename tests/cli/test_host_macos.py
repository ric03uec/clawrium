"""Unit tests for cli/host_macos.py (issue #469, step 3).

E2E lives separately (tests/integration/test_macos_e2e_real.py, step 11).
These tests cover the pure-Python helpers that don't require an SSH
session against a real Mac:
  - `_pick_free_uid`: parses `dscl . -list /Users UniqueID` output
  - module import + symbol surface (so the dispatcher's lazy import works)
"""

from io import StringIO

import pytest

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


# ===== Iteration 3 B6: rich_escape() regression coverage =====
# Verifies that markup-injection strings reach Console.print as escaped
# literals — not as active Rich tags. A regression removing any
# rich_escape() call would leave open a markup-injection vector
# (e.g. a hostname like `x[/cyan][red blink]pwned` could break the
# operator's terminal styling).


def test_init_macos_escapes_markup_in_hostname_on_keypair_load(monkeypatch, capsys):
    """When init_macos prints the early keypair-load line, a hostname
    containing Rich markup chars must appear literally, not be parsed
    as a markup tag.

    Strategy: stub get_host_private_key to short-circuit before the
    paramiko connect attempt. Capture stdout and assert the literal
    string `[red]` appears (which would otherwise be silently dropped
    by Rich's parser).
    """
    from clawrium.cli import host_macos

    # Short-circuit immediately on the keypair check so we exercise
    # only lines 60-64 (the early prints).
    monkeypatch.setattr(
        host_macos, "get_host_private_key", lambda _h: None
    )

    def _fake_generate(_hostname):
        # Return any pair — actual content unimportant for this test.
        from pathlib import Path

        return Path("/tmp/fake_key"), Path("/tmp/fake_key.pub")

    monkeypatch.setattr(host_macos, "generate_host_keypair", _fake_generate)
    monkeypatch.setattr(host_macos, "read_public_key", lambda _h: "ssh-ed25519 KEYDATA")

    # Force the paramiko connect to raise so we exit before logging
    # things outside the scope of this test.
    class _BoomClient:
        def __init__(self):
            pass

        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, _):
            pass

        def connect(self, **kw):
            import paramiko

            raise paramiko.AuthenticationException("normal-auth-fail")

        def close(self):
            pass

    monkeypatch.setattr("paramiko.SSHClient", lambda: _BoomClient())

    import typer

    malicious = "evil[/cyan][red blink]pwned"
    with pytest.raises(typer.Exit):
        host_macos.init_macos(malicious, user="op")

    out = capsys.readouterr().out
    # ATX iter-3 W8: the test cares about TWO independent invariants,
    # both must hold simultaneously:
    #   (a) the literal tag string survives to the output (proves the
    #       text was treated as data, not markup);
    #   (b) Rich did NOT emit ANSI escape sequences for that tag.
    # The previous `[red blink] in out OR \[red blink] in out`
    # disjunction trivially passed if escaping failed and Rich
    # rendered the tag (because Rich strips the brackets but emits
    # ANSI). Asserting (a) AND (b) is unambiguous.
    assert "[red blink]" in out, (
        f"literal injected tag string missing — rich either rendered "
        f"it as markup or dropped it entirely: {out!r}"
    )
    assert "\x1b[31" not in out, (
        f"red ANSI escape leaked — rich_escape failed: {out!r}"
    )
    # And no blink ANSI sequence (\x1b[5m) emitted either.
    assert "\x1b[5m" not in out


def test_init_macos_escapes_markup_in_auth_exception(monkeypatch, capsys):
    """When paramiko raises with markup chars in the exception message,
    the message must reach the console escaped (not parsed)."""
    from clawrium.cli import host_macos
    from pathlib import Path

    monkeypatch.setattr(
        host_macos, "get_host_private_key", lambda _h: Path("/tmp/fake_key")
    )
    monkeypatch.setattr(host_macos, "read_public_key", lambda _h: "ssh-ed25519 KEYDATA")

    class _BoomClient:
        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, _):
            pass

        def connect(self, **kw):
            import paramiko

            raise paramiko.AuthenticationException("[bold]injected-by-attacker[/bold]")

        def close(self):
            pass

    monkeypatch.setattr("paramiko.SSHClient", lambda: _BoomClient())

    import typer

    with pytest.raises(typer.Exit):
        host_macos.init_macos("host.example.com", user="op")

    out = capsys.readouterr().out
    # ATX iter-3 W8: literal `[bold]` MUST appear AND no bold ANSI
    # sequence may be emitted. Together these prove rich_escape's
    # double-bracket-to-literal-bracket round trip worked end-to-end.
    assert "[bold]" in out, (
        f"literal injected tag string missing — rich either rendered "
        f"it as markup or dropped it entirely: {out!r}"
    )
    assert "\x1b[1m" not in out, (
        f"bold ANSI escape leaked — rich_escape failed: {out!r}"
    )

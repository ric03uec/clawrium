"""Darwin Pi remote ownership marker guard (#1038)."""

import shlex

import pytest

from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    _verify_pi_remote_ownership,
)


class _Channel:
    def __init__(self, status: int):
        self._status = status

    def recv_exit_status(self) -> int:
        return self._status


class _Output:
    def __init__(self, status: int):
        self.channel = _Channel(status)


class _Client:
    def __init__(self, status: int = 0):
        self.status = status
        self.commands: list[tuple[str, int]] = []

    def exec_command(self, command: str, timeout: int):
        self.commands.append((command, timeout))
        return None, _Output(self.status), None


def test_darwin_pi_marker_guard_uses_stock_perl_and_validates_all_bindings():
    client = _Client()

    _verify_pi_remote_ownership(client, agent_name="pi-demo", family="darwin")

    assert len(client.commands) == 1
    command, timeout = client.commands[0]
    assert timeout == 30
    assert command.startswith("sudo -n /usr/bin/perl -c ")
    assert "/usr/bin/python3" not in command
    assert "use Fcntl qw(O_RDONLY O_NOFOLLOW)" in command
    assert "use JSON::PP qw(decode_json)" in command
    assert "getpwnam($name)" in command
    assert "lstat($marker)" in command
    assert "sysopen(my $fh, $marker, O_RDONLY | O_NOFOLLOW)" in command
    assert "$before[4] == 0" in command
    assert "($before[2] & 07777) == 0600" in command
    assert "$data->{schema} == 2" in command
    assert "$data->{agent_name} eq $name" in command
    assert "$data->{home} eq $home" in command
    assert "$data->{uid} == $account[2]" in command
    assert "$account[7] eq $home" in command
    assert '$account[6] eq "clawrium-pi-$transaction"' in command


@pytest.mark.parametrize(
    "failure",
    [
        "account GECOS does not match the marker transaction",
        "marker account name, home, or UID does not match",
        "marker is a symlink",
        "marker is not root-owned",
        "marker mode is not 0600",
    ],
)
def test_darwin_pi_marker_guard_fails_closed_for_adversarial_marker(failure: str):
    client = _Client(status=1)

    with pytest.raises(CanonicalSyncError, match="ownership marker"):
        _verify_pi_remote_ownership(client, agent_name="pi-demo", family="darwin")

    assert len(client.commands) == 1, failure


def test_darwin_pi_marker_guard_quotes_untrusted_agent_name():
    client = _Client()
    agent_name = "pi-demo; touch /tmp/pwned"

    _verify_pi_remote_ownership(client, agent_name=agent_name, family="darwin")

    command = client.commands[0][0]
    assert shlex.quote(agent_name) in command
    assert shlex.quote(f"/Users/{agent_name}") in command
    assert shlex.quote(
        f"/Library/Application Support/clawrium/pi/{agent_name}.json"
    ) in command


def test_linux_pi_marker_guard_preserves_python_implementation():
    client = _Client()

    _verify_pi_remote_ownership(client, agent_name="pi-demo", family="linux")

    command = client.commands[0][0]
    assert command.startswith("sudo -n /usr/bin/python3 -c ")
    assert "/usr/bin/perl" not in command

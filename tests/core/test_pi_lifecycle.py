"""Canonical Pi OpenRouter credential activation (#1038)."""

import pytest

from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    _sync_pi_openrouter,
    revoke_pi_openrouter,
    _pi_user_environment_operation,
)


class _Channel:
    def recv_exit_status(self):
        return 0


class _Output:
    channel = _Channel()


class _Stdin:
    channel = type("Channel", (), {"shutdown_write": lambda self: None})()

    def write(self, _body):
        pass

    def flush(self):
        pass


class _Client:
    def __init__(self):
        self.commands = []
        self.closed = False

    def exec_command(self, command, timeout):
        self.commands.append((command, timeout))
        return _Stdin(), _Output(), None

    def close(self):
        self.closed = True


def test_canonical_pi_sync_writes_only_account_private_environment(monkeypatch):
    client = _Client()
    writes = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )

    result = _sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "wolf-i", "os_family": "linux"},
        claw_record={"providers": ["router"]},
        workspace_only=False,
        dry_run=False,
        on_event=None,
    )

    assert result.success is True
    assert client.closed is True
    assert len(writes) == 1
    assert writes[0]["path"] == "/home/pi-demo/.pi/agent/clawrium-openrouter.env"
    assert writes[0]["body"] == "OPENROUTER_API_KEY=private-key\n"
    assert "private-key" not in client.commands[0][0]


def test_canonical_pi_sync_closes_ssh_when_private_write_fails(monkeypatch):
    client = _Client()
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CanonicalSyncError("write failed")
        ),
    )
    with pytest.raises(CanonicalSyncError, match="write failed"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["router"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )
    assert client.closed is True


def test_canonical_pi_sync_refuses_remote_ownership_validation_failure(monkeypatch):
    client = _Client()
    client_result = _Output()
    client_result.channel.recv_exit_status = lambda: 1
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda *_a, **_kw: pytest.fail("must not write"),
    )
    client.exec_command = lambda command, timeout: (None, client_result, None)
    with pytest.raises(CanonicalSyncError, match="ownership marker"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["router"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )
    assert client.closed


def test_pi_environment_write_streams_secret_only_on_stdin():
    events = []

    class Channel:
        def shutdown_write(self):
            events.append("shutdown")

        def recv_exit_status(self):
            return 0

    class Stdin:
        channel = Channel()

        def write(self, value):
            events.append(("write", value))

        def flush(self):
            events.append("flush")

    class Client:
        def exec_command(self, command, timeout):
            assert "private-key" not in command
            assert "sudo -n -u pi-demo" in command
            return Stdin(), type("Out", (), {"channel": Channel()})(), None

    _pi_user_environment_operation(
        Client(),
        agent_name="pi-demo",
        path="/home/pi-demo/.pi/agent/clawrium-openrouter.env",
        body="OPENROUTER_API_KEY=private-key\\n",
    )
    assert events == [
        ("write", "OPENROUTER_API_KEY=private-key\\n"),
        "flush",
        "shutdown",
    ]


def test_pi_revocation_fails_closed(monkeypatch):
    client = _Client()
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    # The first command validates ownership; revocation fails after it.
    calls = iter([0, 1])
    client.exec_command = lambda command, timeout: (
        None,
        type(
            "O",
            (),
            {
                "channel": type(
                    "C", (), {"recv_exit_status": lambda self: next(calls)}
                )()
            },
        )(),
        None,
    )
    with pytest.raises(CanonicalSyncError, match="remove Pi OpenRouter credential"):
        revoke_pi_openrouter(
            agent_name="pi-demo", host={"hostname": "wolf-i", "os_family": "linux"}
        )
    assert client.closed


def test_canonical_pi_sync_rejects_missing_provider_before_remote_io(monkeypatch):
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._open_ssh",
        lambda _: pytest.fail("must not open SSH"),
    )
    with pytest.raises(CanonicalSyncError, match="exactly one attached"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": []},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )

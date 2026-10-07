"""Security regression coverage for Pi Bedrock AWS cache revocation (#1039)."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    _clear_pi_bedrock_aws_caches,
    _pi_bedrock_cache_cleanup_program,
    _sync_pi_openrouter,
    revoke_pi_openrouter,
)


@pytest.fixture
def pi_home(tmp_path):
    home = tmp_path / "pi-demo"
    home.mkdir()
    return home


class _CleanupStream:
    def __init__(self, result):
        self._result = result
        self.channel = type(
            "Channel", (), {"recv_exit_status": lambda _self: result.returncode}
        )()

    def read(self):
        return self._result.stdout


class _ExecutingCleanupClient:
    """Execute the parsed remote cleanup invocation under test-local identity."""

    def __init__(self):
        self.commands = []
        self.closed = False

    def exec_command(self, command, timeout):
        argv = shlex.split(command)
        self.commands.append((argv, timeout))
        assert argv[:5] == ["sudo", "-n", "-u", argv[3], "--"]
        interpreter = sys.executable if argv[5] == "/usr/bin/python3" else argv[5]
        result = subprocess.run(
            [interpreter, *argv[6:]], capture_output=True, check=False
        )
        stream = _CleanupStream(result)
        return None, stream, stream

    def close(self):
        self.closed = True


def _run_cleanup(
    os_family: str,
    home,
    *,
    trusted_uid: int | None = None,
    foreign_name: str | None = None,
    foreign_descriptor: bool = False,
    race_branch: str | None = None,
    race_action: str | None = None,
    entry_race_action: str | None = None,
    listed_entry_race_action: str | None = None,
    outside: Path | None = None,
):
    interpreter, execution_flag, program = _pi_bedrock_cache_cleanup_program(os_family)
    if foreign_name is not None:
        if foreign_descriptor:
            # Splice after the real descriptor stat call: this must exercise
            # the ownership validation in opened(), not clear()'s pathname stat.
            if os_family == "darwin":
                marker = "my @st=stat($fh); exit 1 unless"
                replacement = (
                    "my @st=stat($fh); "
                    f"$st[4]++ if $name eq q{{{foreign_name}}}; exit 1 unless"
                )
            else:
                marker = "status = os.fstat(fd)\n    if not"
                replacement = (
                    "status = os.fstat(fd)\n"
                    f"    if name == {foreign_name!r}:\n"
                    "        values = list(status); values[4] += 1\n"
                    "        status = os.stat_result(values)\n"
                    "    if not"
                )
            assert program.count(marker) == 1
            program = program.replace(marker, replacement)
        elif os_family == "darwin":
            program = f'''BEGIN {{ *CORE::GLOBAL::lstat = sub {{ my @s=CORE::lstat($_[0]); $s[4]++ if @s && $_[0] =~ /{foreign_name}/; return wantarray ? @s : $s[0]; }}; }}\n''' + program
        else:
            program = f'''import os as _os
_def_lstat, _def_stat = _os.lstat, _os.stat
def _foreign_owner(fn):
    def wrapped(path, *args, **kwargs):
        result = fn(path, *args, **kwargs)
        if str(path).endswith("{foreign_name}"):
            values = list(result); values[4] += 1
            return _os.stat_result(values)
        return result
    return wrapped
_os.lstat = _foreign_owner(_def_lstat)
_os.stat = _foreign_owner(_def_stat)
''' + program
    environment = None
    if race_branch is not None:
        assert race_action in {"remove", "replace"}
        if race_action == "replace":
            assert outside is not None
            environment = {**os.environ, "PI_TEST_OUTSIDE": str(outside)}
        if os_family == "darwin":
            mutation = (
                "my $race_cache=\"$home/.aws/$branch/cache\"; "
                "unlink \"$race_cache/token\"; rmdir($race_cache) or exit 1; "
            )
            if race_action == "replace":
                mutation += "symlink $ENV{PI_TEST_OUTSIDE},$race_cache or exit 1; "
            marker = "$branch_fh=eval { opened($aws,$branch,$uid) }; exit 1 if $@ && $@ !~ /missing/; next if $@; "
            replacement = marker + f"if ($branch eq q{{{race_branch}}}) {{ {mutation}}} "
        else:
            mutation = (
                "import shutil; "
                "race_cache = os.path.join(home, '.aws', branch, 'cache'); "
                "shutil.rmtree(race_cache); "
            )
            if race_action == "replace":
                mutation += "os.symlink(os.environ['PI_TEST_OUTSIDE'], race_cache); "
            marker = (
                "try: branch_fd = opened(aws_fd, branch, uid)\n"
                "                except FileNotFoundError: continue\n"
                "                try:"
            )
            replacement = (
                "try: branch_fd = opened(aws_fd, branch, uid)\n"
                "                except FileNotFoundError: continue\n"
                f"                if branch == {race_branch!r}: {mutation}\n"
                "                try:"
            )
        assert program.count(marker) == 1
        program = program.replace(marker, replacement)
    if entry_race_action is not None:
        assert entry_race_action in {"remove", "replace"}
        if entry_race_action == "replace":
            assert outside is not None
            environment = {**(environment or os.environ), "PI_TEST_OUTSIDE": str(outside)}
        if os_family == "darwin":
            mutation = 'unlink "$home/.aws/sso/cache/bearer" or exit 1; '
            if entry_race_action == "replace":
                mutation += 'symlink $ENV{PI_TEST_OUTSIDE},"$home/.aws/sso/cache/bearer" or exit 1; '
            marker = "$cache=eval { opened($branch_fh,q{cache},$uid) }; exit 1 if $@ && $@ !~ /missing/; next if $@; clear($cache);"
            replacement = (
                "$cache=eval { opened($branch_fh,q{cache},$uid) }; exit 1 if $@ && $@ !~ /missing/; next if $@; "
                f"if ($branch eq q{{sso}}) {{ {mutation}}} clear($cache);"
            )
        else:
            mutation = "os.unlink(os.path.join(home, '.aws', 'sso', 'cache', 'bearer')); "
            if entry_race_action == "replace":
                mutation += "os.symlink(os.environ['PI_TEST_OUTSIDE'], os.path.join(home, '.aws', 'sso', 'cache', 'bearer')); "
            marker = (
                "try: cache_fd = opened(branch_fd, \"cache\", uid)\n"
                "                    except FileNotFoundError: continue\n"
                "                    try:"
            )
            replacement = (
                "try: cache_fd = opened(branch_fd, \"cache\", uid)\n"
                "                    except FileNotFoundError: continue\n"
                f"                    if branch == 'sso': {mutation}\n"
                "                    try:"
            )
        assert program.count(marker) == 1
        program = program.replace(marker, replacement)
    if listed_entry_race_action is not None:
        assert listed_entry_race_action in {"remove", "replace"}
        if listed_entry_race_action == "replace":
            assert outside is not None
            environment = {**(environment or os.environ), "PI_TEST_OUTSIDE": str(outside)}
        if os_family == "darwin":
            mutation = 'unlink "$home/.aws/sso/cache/bearer" or exit 1; '
            if listed_entry_race_action == "replace":
                mutation += 'symlink $ENV{PI_TEST_OUTSIDE},"$home/.aws/sso/cache/bearer" or exit 1; '
            marker = "next if $name eq q{.} || $name eq q{..}; my @st=lstat($name);"
            replacement = (
                "next if $name eq q{.} || $name eq q{..}; "
                f"if ($name eq q{{bearer}}) {{ {mutation}}} my @st=lstat($name);"
            )
        else:
            mutation = "os.unlink(os.path.join(home, '.aws', 'sso', 'cache', 'bearer')); "
            if listed_entry_race_action == "replace":
                mutation += "os.symlink(os.environ['PI_TEST_OUTSIDE'], os.path.join(home, '.aws', 'sso', 'cache', 'bearer')); "
            marker = "for name in os.listdir(directory_fd):\n        status = os.stat"
            replacement = (
                "for name in os.listdir(directory_fd):\n"
                f"        if name == 'bearer': {mutation}\n"
                "        status = os.stat"
            )
        assert program.count(marker) == 1
        program = program.replace(marker, replacement)
    if interpreter.endswith("python3"):
        interpreter = sys.executable
    return subprocess.run(
        [
            interpreter,
            execution_flag,
            program,
            str(home),
            str(home.parent),
            str(os.getuid() if trusted_uid is None else trusted_uid),
        ],
        capture_output=True,
        check=False,
        env=environment,
    )


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_removes_both_caches_and_preserves_sibling(os_family, pi_home):
    sso_file = pi_home / ".aws/sso/cache/bearer.json"
    cli_file = pi_home / ".aws/cli/cache/role.json"
    sibling = pi_home.parent / "sibling" / ".aws/sso/cache/keep.json"
    for path in (sso_file, cli_file, sibling):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not read by cleanup")

    result = _run_cleanup(os_family, pi_home)

    assert result.returncode == 0
    assert not sso_file.exists()
    assert not cli_file.exists()
    assert sibling.read_text() == "not read by cleanup"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_accepts_absent_aws_directories(os_family, pi_home):
    result = _run_cleanup(os_family, pi_home)

    assert result.returncode == 0


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_rejects_mismatched_trusted_parent_uid_without_mutation(
    os_family, pi_home
):
    sso_sentinel = pi_home / ".aws/sso/cache/bearer"
    cli_sentinel = pi_home / ".aws/cli/cache/role"
    sibling = pi_home.parent / "sibling" / "keep"
    outside = pi_home.parent / "outside" / "keep"
    for path in (sso_sentinel, cli_sentinel, sibling, outside):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must survive")

    result = _run_cleanup(os_family, pi_home, trusted_uid=os.getuid() + 1)

    assert result.returncode != 0
    assert sso_sentinel.read_text() == "must survive"
    assert cli_sentinel.read_text() == "must survive"
    assert sibling.read_text() == "must survive"
    assert outside.read_text() == "must survive"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
@pytest.mark.parametrize("branch", ["sso", "cli"])
def test_cache_cleanup_accepts_cache_component_absent_before_open(os_family, branch, pi_home):
    (pi_home / f".aws/{branch}").mkdir(parents=True)
    other_sentinel = pi_home / f".aws/{'cli' if branch == 'sso' else 'sso'}/cache/sentinel"
    other_sentinel.parent.mkdir(parents=True)
    other_sentinel.write_text("cache")

    result = _run_cleanup(os_family, pi_home)

    assert result.returncode == 0
    assert not other_sentinel.exists()


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
@pytest.mark.parametrize("branch", ["sso", "cli"])
@pytest.mark.parametrize("action", ["remove", "replace"])
def test_cache_cleanup_fails_closed_on_component_replacement_during_traversal(
    os_family, pi_home, tmp_path, branch, action
):
    """Inject replacement after the branch fd is opened, before cache lookup."""
    sso_token = pi_home / ".aws/sso/cache/token"
    cli_token = pi_home / ".aws/cli/cache/token"
    sibling = pi_home.parent / "sibling" / "keep"
    outside = tmp_path / "outside"
    outside_keep = outside / "keep"
    for path in (sso_token, cli_token, sibling, outside_keep):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must survive")

    result = _run_cleanup(
        os_family,
        pi_home,
        race_branch=branch,
        race_action=action,
        outside=outside,
    )

    assert sibling.read_text() == "must survive"
    assert outside_keep.read_text() == "must survive"
    if action == "remove":
        assert result.returncode == 0
        assert not sso_token.exists()
        assert not cli_token.exists()
    else:
        assert result.returncode != 0
        raced_cache = pi_home / f".aws/{branch}/cache"
        assert raced_cache.is_symlink()
        if branch == "sso":
            assert cli_token.read_text() == "must survive"
        else:
            assert not sso_token.exists()


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_accepts_bearer_disappearance_before_enumeration(os_family, pi_home):
    bearer = pi_home / ".aws/sso/cache/bearer"
    cli_sentinel = pi_home / ".aws/cli/cache/sentinel"
    for path in (bearer, cli_sentinel):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cache")

    result = _run_cleanup(os_family, pi_home, entry_race_action="remove")

    assert result.returncode == 0
    assert not cli_sentinel.exists()


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
@pytest.mark.parametrize("action", ["remove", "replace"])
def test_cache_cleanup_fails_closed_when_listed_bearer_changes_before_stat(
    os_family, action, pi_home, tmp_path
):
    """A listed cache entry disappearing or changing must fail before CLI cleanup."""
    bearer = pi_home / ".aws/sso/cache/bearer"
    cli_sentinel = pi_home / ".aws/cli/cache/sentinel"
    sibling = pi_home.parent / "sibling" / "keep"
    outside = tmp_path / "outside"
    outside_keep = outside / "keep"
    for path in (bearer, cli_sentinel, sibling, outside_keep):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must survive")

    result = _run_cleanup(
        os_family,
        pi_home,
        listed_entry_race_action=action,
        outside=outside,
    )

    assert result.returncode != 0
    assert cli_sentinel.read_text() == "must survive"
    assert sibling.read_text() == "must survive"
    assert outside_keep.read_text() == "must survive"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_rejects_symlink_without_touching_target(os_family, pi_home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "bearer.json"
    secret.write_text("must survive")
    (pi_home / ".aws/sso").mkdir(parents=True)
    (pi_home / ".aws/sso/cache").symlink_to(outside, target_is_directory=True)

    result = _run_cleanup(os_family, pi_home)

    assert result.returncode != 0
    assert secret.read_text() == "must survive"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_rejects_symlinked_aws_ancestor_without_touching_outside(
    os_family, pi_home, tmp_path
):
    outside = tmp_path / "outside"
    secret = outside / "sso/cache/bearer.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("must survive")
    (pi_home / ".aws").symlink_to(outside, target_is_directory=True)

    result = _run_cleanup(os_family, pi_home)

    assert result.returncode != 0
    assert secret.read_text() == "must survive"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
@pytest.mark.parametrize("cache_root", [".aws/sso/cache", ".aws/cli/cache"])
@pytest.mark.parametrize("nested", [False, True])
def test_cache_cleanup_rejects_foreign_owned_cache_objects(
    os_family, cache_root, nested, pi_home
):
    hostile = pi_home / cache_root / ("nested/foreign" if nested else "foreign")
    hostile.parent.mkdir(parents=True)
    if nested:
        hostile.mkdir()
        (hostile / "retained").write_text("must survive")
    else:
        hostile.write_text("must survive")
    sibling = pi_home.parent / "sibling" / "keep"
    sibling.parent.mkdir()
    sibling.write_text("untouched")

    result = _run_cleanup(
        os_family,
        pi_home,
        foreign_name="foreign",
        foreign_descriptor=nested,
    )

    assert result.returncode != 0
    assert hostile.exists()
    if nested:
        assert (hostile / "retained").read_text() == "must survive"
    assert sibling.read_text() == "untouched"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_cache_cleanup_wrapper_uses_root_trusted_parent_by_default(os_family, pi_home):
    class Client:
        def __init__(self):
            self.command = ""

        def exec_command(self, command, timeout):
            self.command = command
            result = subprocess.CompletedProcess((), 0, b"", b"")
            stream = _CleanupStream(result)
            return None, stream, stream

    client = Client()
    _clear_pi_bedrock_aws_caches(
        client,
        agent_name="pi-demo",
        home=str(pi_home),
        os_family=os_family,
        trusted_parent=str(pi_home.parent),
    )

    argv = shlex.split(client.command)
    assert argv[-1] == "0"


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_remote_cache_cleanup_executes_exact_wrapper_argv(os_family, pi_home):
    sso = pi_home / ".aws/sso/cache/bearer"
    cli = pi_home / ".aws/cli/cache/role"
    for path in (sso, cli):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cache")
    client = _ExecutingCleanupClient()
    interpreter, execution_flag, program = _pi_bedrock_cache_cleanup_program(os_family)

    _clear_pi_bedrock_aws_caches(
        client,
        agent_name="pi-demo",
        home=str(pi_home),
        os_family=os_family,
        trusted_parent=str(pi_home.parent),
        trusted_parent_uid=os.getuid(),
    )

    assert client.commands == [
        (
            [
                "sudo",
                "-n",
                "-u",
                "pi-demo",
                "--",
                interpreter,
                execution_flag,
                program,
                str(pi_home),
                str(pi_home.parent),
                str(os.getuid()),
            ],
            30,
        )
    ]
    assert not sso.exists()
    assert not cli.exists()


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
def test_partial_cache_failure_clears_sso_but_retains_cli_sentinel(os_family, pi_home):
    sso = pi_home / ".aws/sso/cache/bearer"
    cli_sentinel = pi_home / ".aws/cli/cache/sentinel"
    cli_hostile = pi_home / ".aws/cli/cache/hostile"
    for path in (sso, cli_sentinel):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cache")
    cli_hostile.symlink_to(pi_home.parent, target_is_directory=True)

    result = _run_cleanup(os_family, pi_home)

    assert result.returncode != 0
    assert not sso.exists()
    assert cli_sentinel.read_text() == "cache"


def test_openrouter_sync_revokes_aws_caches_before_replacing_bedrock(monkeypatch):
    events = []
    client = type("Client", (), {"close": lambda self: None})()
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: events.append("ownership"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._clear_pi_bedrock_aws_caches",
        lambda *_args, **_kwargs: events.append("cache-cleanup"),
    )
    def environment(_client, **kwargs):
        if kwargs.get("clear_bedrock_caches"):
            events.append("cache-cleanup")
        events.append(("write", kwargs["path"]))

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation", environment
    )
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )

    _sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "host", "os_family": "linux"},
        claw_record={"providers": ["openrouter"]},
        workspace_only=False,
        dry_run=False,
        on_event=None,
    )

    assert events[:2] == ["ownership", "cache-cleanup"]
    assert [event[0] for event in events[2:]] == ["write", "write", "write"]


@pytest.mark.parametrize("os_family", ["linux", "darwin"])
@pytest.mark.parametrize("operation", ["sync", "revoke"])
def test_real_partial_cache_failure_stops_sync_and_revoke_before_managed_mutation(
    monkeypatch, os_family, operation
):
    """A real remote cleanup failure must precede every provider-file command."""
    with tempfile.TemporaryDirectory(dir="/tmp") as temporary_home:
        home = Path(temporary_home)
        agent_name = home.name
        sso = home / ".aws/sso/cache/bearer"
        cli_hostile = home / ".aws/cli/cache/00-hostile"
        cli_sentinel = home / ".aws/cli/cache/zz-sentinel"
        sso.parent.mkdir(parents=True)
        sso.write_text("cache")
        cli_sentinel.parent.mkdir(parents=True)
        cli_sentinel.write_text("cache")
        cli_hostile.symlink_to(home.parent, target_is_directory=True)
        client = _ExecutingCleanupClient()
        monkeypatch.setattr(
            "clawrium.core.lifecycle_canonical._open_ssh", lambda _: client
        )
        monkeypatch.setattr(
            "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            "clawrium.core.lifecycle_canonical.home_root_for", lambda _: "/tmp"
        )
        if operation == "sync":
            monkeypatch.setattr(
                "clawrium.core.providers.storage.get_provider",
                lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
            )
            monkeypatch.setattr(
                "clawrium.core.providers.get_provider_api_key", lambda _: "test-api-key"
            )
            def call():
                return _sync_pi_openrouter(
                    agent_name=agent_name,
                    host={"hostname": "host", "os_family": os_family},
                    claw_record={"providers": ["openrouter"]},
                    workspace_only=False,
                    dry_run=False,
                    on_event=None,
                )
        else:
            def call():
                return revoke_pi_openrouter(
                    agent_name=agent_name,
                    host={"hostname": "host", "os_family": os_family},
                )

        phase = "switching Pi provider" if operation == "sync" else "revoking Bedrock credentials"
        with pytest.raises(CanonicalSyncError, match=f"clean Pi Bedrock AWS cache while {phase}"):
            call()

        assert not sso.exists()
        assert cli_hostile.is_symlink()
        assert cli_sentinel.read_text() == "cache"
        assert len(client.commands) == 1
        assert "clawrium-pi-env" not in client.commands[0][0]
        assert client.closed is True


@pytest.mark.parametrize(
    ("failing_name", "expected_names"),
    [
        ("clawrium-aws-config", ["clawrium-aws-config"]),
        (
            "clawrium-aws-credentials",
            ["clawrium-aws-config", "clawrium-aws-credentials"],
        ),
    ],
)
def test_openrouter_removes_old_aws_files_before_new_activation(
    monkeypatch, failing_name, expected_names
):
    client = type(
        "Client",
        (),
        {"closed": False, "close": lambda self: setattr(self, "closed", True)},
    )()
    operations = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._clear_pi_bedrock_aws_caches",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "test-api-key"
    )

    def environment_operation(_client, **kwargs):
        operations.append(kwargs)
        if kwargs["path"].endswith(failing_name):
            raise CanonicalSyncError("old AWS file removal failed")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        environment_operation,
    )

    with pytest.raises(CanonicalSyncError, match="old AWS file removal failed"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "host", "os_family": "linux"},
            claw_record={"providers": ["openrouter"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )

    assert [operation["path"].rsplit("/", 1)[-1] for operation in operations] == expected_names
    assert all(operation["body"] is None for operation in operations)
    assert client.closed is True


def test_openrouter_dry_run_does_not_contact_or_clear_remote_cache(monkeypatch):
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr("clawrium.core.providers.get_provider_api_key", lambda _: "private-key")
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._open_ssh",
        lambda _: pytest.fail("dry run must not contact the remote host"),
    )

    result = _sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "host", "os_family": "linux"},
        claw_record={"providers": ["openrouter"]},
        workspace_only=False,
        dry_run=True,
        on_event=None,
    )

    assert result.files_written == ()


def test_provider_transition_revokes_aws_caches_before_managed_files(monkeypatch):
    events = []
    client = type("Client", (), {"close": lambda self: None})()
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: events.append("ownership"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._clear_pi_bedrock_aws_caches",
        lambda *_args, **_kwargs: events.append("cache-cleanup"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: events.append(("remove", kwargs["path"])),
    )

    revoke_pi_openrouter(
        agent_name="pi-demo", host={"hostname": "host", "os_family": "linux"}
    )

    assert events[:2] == ["ownership", "cache-cleanup"]
    assert [event[0] for event in events[2:]] == ["remove", "remove", "remove"]

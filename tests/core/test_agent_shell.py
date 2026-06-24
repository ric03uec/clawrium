"""Unit tests for core/agent_shell.py — login-shell command runner.

ansible_runner is mocked so tests run offline. Event lists model what
the real `shell.yaml` playbook emits: three debug events tagged
SHELL_STDOUT=/SHELL_STDERR=/SHELL_RC=.
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import agent_shell


HOST_FIXTURE = {
    "hostname": "wolf-i",
    "user": "xclm",
    "port": 22,
    "key_id": "wolf-i",
    "alias": "wolf-i",
}


def _ok_event(msg: str) -> dict:
    return {"event": "runner_on_ok", "event_data": {"res": {"msg": msg}}}


def _make_result(events: list[dict], status: str = "successful") -> SimpleNamespace:
    return SimpleNamespace(events=events, status=status)


@pytest.fixture
def patched_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(
        agent_shell,
        "get_config_dir",
        lambda: tmp_path / "config",
    )
    monkeypatch.setattr(
        agent_shell.core_keys,
        "get_host_private_key",
        lambda key_id: tmp_path / "fake-key",
    )
    (tmp_path / "fake-key").write_text("KEY")
    # Stub get_host
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(hosts_module, "get_host", lambda h: dict(HOST_FIXTURE))
    return tmp_path


def _ok_events_for(stdout: bytes = b"", stderr: bytes = b"", rc: int = 0) -> list[dict]:
    return [
        _ok_event("SHELL_STDOUT=" + base64.b64encode(stdout).decode()),
        _ok_event("SHELL_STDERR=" + base64.b64encode(stderr).decode()),
        _ok_event(f"SHELL_RC={rc}"),
    ]


# ----- K1: event parsing + EXEC_* event isolation --------------------


def test_K1_event_parsing_and_isolation_from_exec_events(monkeypatch, patched_env):
    """Parser consumes SHELL_* events; EXEC_* events on the same stream
    must not leak into the return tuple."""

    def fake_run(**kwargs):
        # Include a stray EXEC_STDOUT= event ahead of SHELL_* events to
        # prove the prefixes are independent.
        events = [
            _ok_event("EXEC_STDOUT=" + base64.b64encode(b"poison").decode()),
        ] + _ok_events_for(stdout=b"hi")
        return _make_result(events)

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["echo", "hi"]
    )
    assert (stdout, stderr, rc) == ("hi", "", 0)


# ----- K2 / K3: base64 decode failures --------------------------------


def test_K2_base64_decode_failure_stdout(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("SHELL_STDOUT=not-base64!!!"),
                _ok_event("SHELL_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("SHELL_RC=3"),
            ]
        ),
    )
    stdout, _stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert stdout == ""
    assert rc == 3


def test_K3_base64_decode_failure_stderr(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("SHELL_STDOUT=" + base64.b64encode(b"").decode()),
                _ok_event("SHELL_STDERR=not-base64!!!"),
                _ok_event("SHELL_RC=4"),
            ]
        ),
    )
    _stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert stderr == ""
    assert rc == 4


# ----- K4: missing rc -------------------------------------------------


def test_K4_missing_rc(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("SHELL_STDOUT=" + base64.b64encode(b"out").decode()),
                _ok_event("SHELL_STDERR=" + base64.b64encode(b"warn").decode()),
                # no SHELL_RC
            ]
        ),
    )
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert stdout == "out"
    assert stderr == "warn"


# ----- K5: runner timeout status -------------------------------------


def test_K5_runner_timeout_status(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result([], status="timeout"),
    )
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["sleep", "30"], timeout=5
    )
    assert (stdout, rc) == ("", 124)
    assert stderr == "remote command timed out after 5s"


# ----- K6: unreachable host ------------------------------------------


def test_K6_unreachable_host(monkeypatch, patched_env):
    unreach = {
        "event": "runner_on_unreachable",
        "event_data": {"res": {"msg": "ssh failed"}},
    }
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result([unreach], status="failed"),
    )
    _stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert "unreachable" in stderr.lower()


# ----- K7: missing host record ---------------------------------------


def test_K7_missing_host(monkeypatch, patched_env):
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(hosts_module, "get_host", lambda h: None)

    called = {"hit": False}

    def boom_run(**kw):
        called["hit"] = True
        raise AssertionError("ansible_runner.run must not be called")

    monkeypatch.setattr(agent_shell.ansible_runner, "run", boom_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "nope", "wolf-i", ["x"]
    )
    assert (stdout, rc) == ("", 255)
    assert "not found" in stderr
    assert called["hit"] is False


# ----- K8: missing SSH key -------------------------------------------


def test_K8_missing_ssh_key(monkeypatch, patched_env):
    monkeypatch.setattr(
        agent_shell.core_keys, "get_host_private_key", lambda key_id: None
    )

    called = {"hit": False}

    def boom_run(**kw):
        called["hit"] = True
        raise AssertionError("ansible_runner.run must not be called")

    monkeypatch.setattr(agent_shell.ansible_runner, "run", boom_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert "SSH key" in stderr
    assert called["hit"] is False


# ----- K9: invalid agent name ----------------------------------------


def test_K9_invalid_agent_name_raises(patched_env):
    for bad in ("Bad Name!", "FOO", "../etc", ""):
        with pytest.raises(agent_shell.AgentShellError):
            agent_shell.run_agent_shell("wolf-i", bad, ["x"])


# ----- K10: playbook missing ----------------------------------------


def test_K10_playbook_missing(monkeypatch, patched_env):
    def fake_resolve(os_family):
        raise FileNotFoundError(
            f"shell playbook for os_family={os_family!r} not found at /nonexistent/path/shell.yaml."
        )

    monkeypatch.setattr(
        agent_shell.playbook_resolver, "resolve_shell_playbook", fake_resolve
    )

    called = {"hit": False}

    def boom_run(**kw):
        called["hit"] = True
        raise AssertionError("ansible_runner.run must not be called")

    monkeypatch.setattr(agent_shell.ansible_runner, "run", boom_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert "shell playbook" in stderr
    assert "not found" in stderr
    assert called["hit"] is False


# ----- K11: artifact cleanup on success ------------------------------


def test_K11_artifact_cleanup_on_success(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        # Real ansible-runner would create these; emulate so cleanup
        # has something to remove.
        for sub in ("artifacts", "env", "inventory"):
            (Path(kw["private_data_dir"]) / sub).mkdir(parents=True, exist_ok=True)
        return _make_result(_ok_events_for(stdout=b"hi"))

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["echo", "hi"])
    assert not Path(captured["pd"]).exists()


# ----- K12: artifact cleanup on runner exception (finally branch) ----


def test_K12_artifact_cleanup_on_runner_exception(monkeypatch, patched_env):
    captured = {}
    original_run = agent_shell.ansible_runner.run

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        raise RuntimeError("boom")

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert (stdout, rc) == ("", 255)
    assert "ansible-runner error: boom" in stderr
    assert not Path(captured["pd"]).exists()
    _ = original_run


# ----- K13: private_data_dir mode 0o700 -----------------------------


def test_K13_private_data_dir_mode_0o700(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        captured["mode"] = os.stat(kw["private_data_dir"]).st_mode & 0o777
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["x"])
    assert captured["mode"] == 0o700


# ----- K14: runner timeout buffer (+30) -----------------------------


@pytest.mark.parametrize(
    "user_timeout,expected_runner_timeout",
    [
        (120, 150),
        (60, 90),
        (1800, 1830),
    ],
)
def test_K14_runner_timeout_buffer(
    monkeypatch, patched_env, user_timeout, expected_runner_timeout
):
    captured = {}

    def fake_run(**kw):
        captured["timeout"] = kw["timeout"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"], timeout=user_timeout
    )
    assert captured["timeout"] == expected_runner_timeout


# ----- K15: ssh-style space-join semantics ---------------------------


_BASHRC_PREFIX = '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"; '


def _decode_cmd_b64(extra_vars: dict) -> str:
    """Decode `cmd_b64` and strip the `.bashrc`-source prefix the
    Python caller prepends. Returns the user's raw joined command so
    tests assert on the intent, not the wrapper boilerplate."""
    full = base64.b64decode(extra_vars["cmd_b64"]).decode("utf-8")
    assert full.startswith(_BASHRC_PREFIX), full
    return full[len(_BASHRC_PREFIX) :]


@pytest.mark.parametrize(
    "argv,expected_cmd_str",
    [
        # Single shell-quoted CLI arg (the canonical --help example).
        (["ls -la ~/"], "ls -la ~/"),
        (["cat ~/.hermes/config.yaml"], "cat ~/.hermes/config.yaml"),
        # Multi-token argv — joined with single spaces. Users with
        # whitespace inside an arg must re-quote inside the outer
        # quoted string (`-- 'echo "hello world"'`).
        (["echo", "hi"], "echo hi"),
        (["sh", "-c", "ls | head"], "sh -c ls | head"),
        (["a", "&&", "b"], "a && b"),
    ],
)
def test_K15_space_join_passthrough(
    monkeypatch, patched_env, argv, expected_cmd_str
):
    captured = {}

    def fake_run(**kw):
        captured["vars"] = kw["inventory"]["all"]["vars"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", argv)
    assert _decode_cmd_b64(captured["vars"]) == expected_cmd_str


def test_K15b_docstring_examples_run_under_bash_lc(
    monkeypatch, patched_env, tmp_path
):
    """End-to-end: every --help/docstring example must run under
    `bash -lc <cmd_str>` without exit 127. Locks the contract that B1
    (shlex.join wrapper killing single-element argv) cannot regress.
    """
    captured = {}

    def fake_run(**kw):
        captured.setdefault("cmds", []).append(_decode_cmd_b64(kw["inventory"]["all"]["vars"]))
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    # The exact strings from the --help / plan examples (each is a
    # single Typer-positional after `--`, mirroring `--help`).
    examples = [
        ["ls -la /tmp"],
        ["echo $HOSTNAME"],
        ["true && echo ok"],
    ]
    for argv in examples:
        agent_shell.run_agent_shell("wolf-i", "wolf-i", argv)

    for cmd in captured["cmds"]:
        # Drive bash -lc with the decoded cmd_b64. Anything that exits
        # non-zero means the join broke the docstring contract.
        rc = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        assert rc == 0, f"`bash -lc {cmd!r}` exited {rc}"


# ----- K16: timeout clamp matrix ------------------------------------


@pytest.mark.parametrize(
    "user_in,effective",
    [
        (None, 1800),
        (0, 1800),
        (-1, 1800),
        (1, 1),
        (60, 60),
        (1800, 1800),
        (1801, 1800),
        (9999, 1800),
    ],
)
def test_K16_timeout_clamp_matrix(monkeypatch, patched_env, user_in, effective):
    captured = {}

    def fake_run(**kw):
        captured["vars"] = kw["inventory"]["all"]["vars"]
        captured["runner_timeout"] = kw["timeout"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"], timeout=user_in
    )
    assert captured["vars"]["shell_timeout"] == effective
    assert captured["runner_timeout"] == effective + 30


# ----- K17: TOCTOU on private_data_dir create -----------------------


def test_K17_mkdir_collision_clean_failure(monkeypatch, patched_env, tmp_path):
    # Force the workdir mkdir to collide. We monkeypatch Path.mkdir
    # only on the leaf log dir by capturing the path and raising
    # FileExistsError exactly once.
    real_mkdir = Path.mkdir
    called = {"raised": False}

    def patched_mkdir(self, *args, **kwargs):
        # The log_dir mkdir uses exist_ok=False. _logs_dir's mkdir
        # uses exist_ok=True. We trigger on the exist_ok=False call.
        if kwargs.get("exist_ok") is False and not called["raised"]:
            called["raised"] = True
            called["path"] = Path(str(self))
            raise FileExistsError(f"{self}")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", patched_mkdir)

    called_run = {"hit": False}

    def boom_run(**kw):
        called_run["hit"] = True
        raise AssertionError("ansible_runner.run must not be called")

    monkeypatch.setattr(agent_shell.ansible_runner, "run", boom_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert (stdout, rc) == ("", 255)
    assert "workdir" in stderr
    assert called_run["hit"] is False
    # Orphan dir must not exist (it never got created).
    assert not called["path"].exists()


# ----- K18: large stdout round-trip ---------------------------------


def test_K18_large_stdout_64kb_round_trip(monkeypatch, patched_env):
    # 64KB of repeating ASCII-safe bytes — base64 over UTF-8 round-trip
    # is byte-exact only for UTF-8-decodable input (see K19 for the
    # documented non-UTF-8 boundary).
    payload = (b"ABCDEFGH" * (8 * 1024))[:64 * 1024]
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(_ok_events_for(stdout=payload)),
    )
    stdout, _stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 0
    assert stdout.encode("utf-8") == payload


# ----- K19: documented non-UTF-8 lossy boundary ---------------------


def test_K19_non_utf8_stdout_documented_lossy(monkeypatch, patched_env):
    # Real Ansible decodes child output as utf-8 with errors='replace'
    # BEFORE handing the string to b64encode. We model the same
    # contract: encode the *replacement* string, not the raw bytes.
    raw = b"\xff\xfe hi"
    decoded = raw.decode("utf-8", errors="replace")
    encoded = base64.b64encode(decoded.encode("utf-8")).decode()
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event(f"SHELL_STDOUT={encoded}"),
                _ok_event("SHELL_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("SHELL_RC=0"),
            ]
        ),
    )
    stdout, _stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 0
    # Non-UTF-8 bytes arrive as U+FFFD by design.
    assert "�" in stdout
    assert stdout.endswith(" hi")


# ----- Empty argv guard ---------------------------------------------


def test_empty_cmd_argv_raises(patched_env):
    with pytest.raises(agent_shell.AgentShellError):
        agent_shell.run_agent_shell("wolf-i", "wolf-i", [])


# ----- iter2 B2: rc=124 must propagate verbatim, no synthetic msg ----


def test_rc_124_propagates_verbatim(monkeypatch, patched_env):
    """Apps that legitimately exit 124 must surface their real stderr.
    Only the ansible-runner-level `status == "timeout"` path (K5)
    synthesizes the "timed out" message; the inner playbook's rc=124
    is left untouched so curl/jq/custom-script callers don't get
    their stderr masked (#761 iter-2 B2)."""
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(
            _ok_events_for(stderr=b"real-app-stderr\n", rc=124)
        ),
    )
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["my-app"], timeout=60
    )
    assert (stdout, rc) == ("", 124)
    # The app's real stderr must NOT be replaced with a synthetic
    # "timed out" message.
    assert stderr == "real-app-stderr\n"
    assert "timed out" not in stderr


# ----- iter2 B1: reserved unix names rejected ------------------------


@pytest.mark.parametrize(
    "reserved",
    ["root", "daemon", "bin", "nobody"],
)
@pytest.mark.parametrize(
    "os_family",
    [None, "linux", "darwin"],
)
def test_iter2_B1_reserved_unix_names_rejected(
    monkeypatch, patched_env, reserved, os_family
):
    """Even if a regex-match name slips through, the denylist must
    refuse to `become_user` a privileged or system account — equally
    on Linux and macOS hosts. A future refactor that moves the check
    below the os_family branch would otherwise break darwin silently
    (W7 iter-1)."""
    from clawrium.core import hosts as hosts_module

    host = {**HOST_FIXTURE}
    if os_family is not None:
        host["os_family"] = os_family
    monkeypatch.setattr(hosts_module, "get_host", lambda h: dict(host))

    with pytest.raises(agent_shell.AgentShellError, match=r"reserved system user"):
        agent_shell.run_agent_shell("wolf-i", reserved, ["ls"])


# ----- iter2 B3: full private_data_dir is rmtree'd ------------------


def test_iter2_B3_full_workdir_rmtree_on_cleanup(monkeypatch, patched_env):
    """ansible-runner writes more than artifacts/, env/, inventory/ —
    project/, command*.json, daemon.log, and pid land directly in the
    workdir. The previous selective cleanup left them behind and the
    leaf dir survived. rmtree must sweep everything."""
    captured = {}

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        pd = Path(kw["private_data_dir"])
        # Emulate the broader set of runner artifacts.
        (pd / "artifacts").mkdir(parents=True, exist_ok=True)
        (pd / "env").mkdir(parents=True, exist_ok=True)
        (pd / "inventory").mkdir(parents=True, exist_ok=True)
        (pd / "project").mkdir(parents=True, exist_ok=True)
        (pd / "command_runner_12345.json").write_text("{}")
        (pd / "daemon.log").write_text("log")
        (pd / "pid").write_text("123")
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["x"])
    # No survivors — the leaf dir itself is gone.
    assert not Path(captured["pd"]).exists()


# ----- K20 (#808): macOS host routes to shell_macos.yaml ------------


def test_K20_macos_host_uses_macos_playbook(monkeypatch, patched_env):
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {**HOST_FIXTURE, "os_family": "darwin"},
    )

    captured = {}

    def fake_run(**kw):
        captured["playbook"] = kw["playbook"]
        return _make_result(_ok_events_for(stdout=b"hi"))

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["ls"]
    )
    assert (stdout, stderr, rc) == ("hi", "", 0)
    # Anchor on the leading `/` so a stray rename like
    # `legacy_shell_macos.yaml` cannot satisfy the assertion (W6 iter-1).
    assert captured["playbook"].endswith("/shell_macos.yaml")


def test_K20_linux_host_uses_linux_playbook(monkeypatch, patched_env):
    captured = {}

    def fake_run(**kw):
        captured["playbook"] = kw["playbook"]
        return _make_result(_ok_events_for(stdout=b"hi"))

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["ls"])
    # Linux uses the no-suffix shell.yaml — assert end-of-path is exactly
    # `/shell.yaml` so a future `_linux` rename can't slip past.
    assert captured["playbook"].endswith("/shell.yaml")
    assert not captured["playbook"].endswith("shell_macos.yaml")


def test_unsupported_os_family_returns_255(monkeypatch, patched_env):
    """A malformed hosts.json with `os_family: 'windows'` must round-
    trip to rc=255 with an actionable stderr — not crash with a
    ValueError up the call stack (iter-1 S6 / lifecycle-core S4)."""
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {**HOST_FIXTURE, "os_family": "windows"},
    )

    called = {"hit": False}

    def boom_run(**kw):
        called["hit"] = True
        raise AssertionError("ansible_runner.run must not be called")

    monkeypatch.setattr(agent_shell.ansible_runner, "run", boom_run)
    stdout, stderr, rc = agent_shell.run_agent_shell("wolf-i", "wolf-i", ["ls"])
    assert (stdout, rc) == ("", 255)
    assert "unsupported os_family" in stderr
    assert called["hit"] is False


@pytest.mark.parametrize(
    "raw_os_family",
    [42, {"x": 1}, ["darwin"], True],
)
def test_non_string_os_family_falls_back_to_linux(
    monkeypatch, patched_env, raw_os_family
):
    """A tampered hosts.json record with a non-string `os_family` must
    not raise AttributeError on `.lower()` — Python normalizes to the
    default ("linux") and the playbook resolves cleanly (iter-1 S1).

    `True` is a sentinel: bool is a subclass of int, exercising the
    isinstance-string guard explicitly."""
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {**HOST_FIXTURE, "os_family": raw_os_family},
    )

    captured = {}

    def fake_run(**kw):
        captured["playbook"] = kw["playbook"]
        return _make_result(_ok_events_for(stdout=b"ok"))

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    stdout, stderr, rc = agent_shell.run_agent_shell("wolf-i", "wolf-i", ["ls"])
    assert (stdout, stderr, rc) == ("ok", "", 0)
    assert captured["playbook"].endswith("/shell.yaml")


# ----- #808: OS-aware rc-file prepend -------------------------------


def test_darwin_rc_prepend_sources_login_files_then_bashrc(
    monkeypatch, patched_env
):
    """The macOS prepend must follow bash login-shell precedence
    (`.bash_profile` → `.bash_login` → `.profile`) followed by an
    always-on `.bashrc` source. Operators with a `.profile`-only
    POSIX-compat dotfile setup must still get PATH shims (iter-1 W2)."""
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {**HOST_FIXTURE, "os_family": "darwin"},
    )

    captured = {}

    def fake_run(**kw):
        captured["vars"] = kw["inventory"]["all"]["vars"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["echo", "hi"])

    decoded = base64.b64decode(captured["vars"]["cmd_b64"]).decode("utf-8")
    # All three login-file legs and the always-on bashrc must appear,
    # in precedence order, followed by exactly the user command.
    expected_prefix = (
        'if [ -f "$HOME/.bash_profile" ]; then . "$HOME/.bash_profile";'
        ' elif [ -f "$HOME/.bash_login" ]; then . "$HOME/.bash_login";'
        ' elif [ -f "$HOME/.profile" ]; then . "$HOME/.profile"; fi;'
        ' [ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"; '
    )
    assert decoded.startswith(expected_prefix), decoded
    assert decoded[len(expected_prefix) :] == "echo hi"


def test_linux_rc_prepend_unchanged(monkeypatch, patched_env):
    """Belt-and-suspenders: the Linux prepend remains bashrc-only."""
    captured = {}

    def fake_run(**kw):
        captured["vars"] = kw["inventory"]["all"]["vars"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["echo", "hi"])

    decoded = base64.b64decode(captured["vars"]["cmd_b64"]).decode("utf-8")
    assert decoded.startswith(_BASHRC_PREFIX), decoded
    # Must NOT contain the darwin-specific .bash_profile leg.
    assert ".bash_profile" not in decoded


# ----- W1: Ansible Jinja sub-injection blocked by base64 hop --------


def test_W1_jinja_in_cmd_not_re_templated(monkeypatch, patched_env):
    """A command containing `{{ ... }}` must reach the remote verbatim.

    Defense: the Python side base64-encodes `cmd_str` and the playbook
    decodes it inline (`{{ cmd_b64 | b64decode }}`). The decoded value
    is a leaf string Jinja does not re-template, so an injected
    expression like `{{ lookup('env','SECRET') }}` arrives at the
    remote `bash -lc` verbatim instead of expanding on the controller.
    """
    captured = {}

    def fake_run(**kw):
        captured["vars"] = kw["inventory"]["all"]["vars"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["echo", "{{1+1}}"]
    )
    # The wire value is the base64 of the bashrc-prefixed joined cmd.
    assert captured["vars"]["cmd_b64"] == base64.b64encode(
        (_BASHRC_PREFIX + "echo {{1+1}}").encode("utf-8")
    ).decode("ascii")
    # And no plain `cmd_str` var is shipped — only the encoded form.
    assert "cmd_str" not in captured["vars"]


# ----- W6: _extract_failure_message branches + malformed SHELL_RC ---


def test_W6_runner_on_failed_msg(monkeypatch, patched_env):
    failed = {
        "event": "runner_on_failed",
        "event_data": {"res": {"msg": "binary not found"}},
    }
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result([failed], status="failed"),
    )
    _stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert "binary not found" in stderr


def test_W6_runner_on_failed_stderr_only(monkeypatch, patched_env):
    failed = {
        "event": "runner_on_failed",
        "event_data": {"res": {"stderr": "permission denied"}},
    }
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result([failed], status="failed"),
    )
    _stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert "permission denied" in stderr


def test_W6_runner_failed_default_message(monkeypatch, patched_env):
    """No on_unreachable/on_failed event → falls back to default."""
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result([], status="failed"),
    )
    _stdout, stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert "failed" in stderr.lower()


def test_W6_malformed_shell_rc_int(monkeypatch, patched_env):
    """`SHELL_RC=garbage` → int() raises → rc=None → caller surfaces 255."""
    monkeypatch.setattr(
        agent_shell.ansible_runner,
        "run",
        lambda **kw: _make_result(
            [
                _ok_event("SHELL_STDOUT=" + base64.b64encode(b"x").decode()),
                _ok_event("SHELL_STDERR=" + base64.b64encode(b"").decode()),
                _ok_event("SHELL_RC=not-an-int"),
            ]
        ),
    )
    stdout, _stderr, rc = agent_shell.run_agent_shell(
        "wolf-i", "wolf-i", ["x"]
    )
    assert rc == 255
    assert stdout == "x"


# ----- W7: _LOG_DIR_SAFE_RE traversal defense -----------------------


@pytest.mark.parametrize(
    "tampered_alias",
    ["../etc", "a/b", "name with spaces", ""],
)
def test_W7_log_dir_sanitized_for_tampered_alias(
    monkeypatch, patched_env, tampered_alias
):
    """Aliases containing path separators or whitespace must never
    reach the on-disk directory name. The defense lets any single
    component matching `_LOG_DIR_SAFE_RE` through; everything else
    falls back to `host`. The leaf is always a single directory
    name under `logs/`, so a `..` substring inside the leaf is
    inert (path resolution only treats `..` as parent when it is the
    entire path component)."""
    from clawrium.core import hosts as hosts_module

    monkeypatch.setattr(
        hosts_module,
        "get_host",
        lambda h: {**HOST_FIXTURE, "alias": tampered_alias},
    )

    captured = {}

    def fake_run(**kw):
        captured["pd"] = kw["private_data_dir"]
        return _make_result(_ok_events_for())

    monkeypatch.setattr(agent_shell.ansible_runner, "run", fake_run)
    agent_shell.run_agent_shell("wolf-i", "wolf-i", ["x"])
    pd = Path(captured["pd"])
    leaf = pd.name
    # The leaf must always start with `shell-` and never contain a
    # path separator or whitespace in the leaf component itself.
    assert leaf.startswith("shell-")
    assert "/" not in leaf
    assert " " not in leaf
    # The full path must stay under the logs root — the alias cannot
    # escape via a `..` sub-component.
    logs_root = pd.parent.resolve()
    assert pd.resolve().is_relative_to(logs_root)
    # When alias fails the safe regex, fallback is "host". Empty
    # alias falls through to key_id ("wolf-i") via the or-chain.
    safe_prefixes = ("shell-host-", "shell-wolf-i-")
    assert any(leaf.startswith(p) for p in safe_prefixes), leaf

"""Tests for the OS-family playbook resolver (issue #469 step 1)."""

from __future__ import annotations

import pytest

from clawrium.core.playbook_resolver import (
    resolve_agent_playbook,
    resolve_base_playbook,
    resolve_shell_playbook,
    shell_rc_prepend,
)


class TestResolveBasePlaybook:
    def test_linux_returns_existing_base(self):
        path = resolve_base_playbook("linux")
        assert path.name == "base.yaml"
        assert path.exists()

    def test_darwin_returns_existing_base_macos(self):
        """Step 4 of #469 landed base_macos.yaml; resolver returns it."""
        path = resolve_base_playbook("darwin")
        assert path.name == "base_macos.yaml"
        assert path.exists()

    def test_unknown_os_family_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported os_family"):
            resolve_base_playbook("windows")


class TestResolveAgentPlaybook:
    def test_linux_hermes_install_returns_existing(self):
        path = resolve_agent_playbook("hermes", "install", "linux")
        assert path.name == "install.yaml"
        assert path.exists()

    def test_linux_zeroclaw_configure_returns_existing(self):
        path = resolve_agent_playbook("zeroclaw", "configure", "linux")
        assert path.name == "configure.yaml"
        assert path.exists()

    def test_darwin_hermes_install_returns_existing_after_step_5(self):
        """Step 5 of #469 landed install_macos.yaml; resolver returns it."""
        path = resolve_agent_playbook("hermes", "install", "darwin")
        assert path.name == "install_macos.yaml"
        assert path.exists()

    def test_unknown_agent_type_raises_file_not_found(self):
        # Same error class as Mac-missing — caller can distinguish via the
        # path embedded in the message.
        with pytest.raises(FileNotFoundError):
            resolve_agent_playbook("nonexistent-agent", "install", "linux")

    def test_unknown_os_family_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported os_family"):
            resolve_agent_playbook("hermes", "install", "windows")


class TestResolveShellPlaybook:
    def test_linux_returns_shell_yaml(self):
        path = resolve_shell_playbook("linux")
        assert path.name == "shell.yaml"
        assert path.exists()

    def test_darwin_returns_shell_macos_yaml(self):
        path = resolve_shell_playbook("darwin")
        assert path.name == "shell_macos.yaml"
        assert path.exists()

    def test_unknown_os_family_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported os_family"):
            resolve_shell_playbook("windows")

    def test_file_not_found_message_includes_resolved_path(
        self, monkeypatch, tmp_path
    ):
        """If the per-OS file is missing (build artifact missing or
        bad install), the resolver must raise FileNotFoundError with a
        message that includes the resolved path so the operator can
        diagnose where it looked (iter-1 lifecycle-core S5)."""
        from clawrium.core import playbook_resolver as resolver

        monkeypatch.setattr(resolver, "_PLATFORM_ROOT", tmp_path)
        with pytest.raises(FileNotFoundError) as excinfo:
            resolve_shell_playbook("linux")
        assert str(tmp_path) in str(excinfo.value)
        assert "shell.yaml" in str(excinfo.value)


class TestShellRcPrepend:
    """OS-aware rc-file prelude for `clawctl agent shell`. The OS
    literal lives here (dispatcher-only OS-fork invariant); agent_shell
    just concatenates the returned string."""

    def test_linux_sources_bashrc_only(self):
        prelude = shell_rc_prepend("linux")
        assert ".bashrc" in prelude
        # Linux must not source darwin-specific login files.
        assert ".bash_profile" not in prelude
        assert ".bash_login" not in prelude
        assert ".profile" not in prelude.replace(".bash_profile", "").replace(
            ".bashrc", ""
        )

    def test_darwin_sources_all_login_legs_then_bashrc(self):
        """bash login-shell precedence: `.bash_profile` → `.bash_login`
        → `.profile` (first found wins). Then `.bashrc` is sourced
        unconditionally so `.bashrc`-only setups still load PATH shims."""
        prelude = shell_rc_prepend("darwin")
        for leg in (".bash_profile", ".bash_login", ".profile", ".bashrc"):
            assert leg in prelude, f"darwin prelude missing {leg!r}: {prelude}"
        # Precedence: bash_profile comes before bash_login comes before
        # profile in the source.
        assert prelude.index(".bash_profile") < prelude.index(".bash_login")
        assert prelude.index(".bash_login") < prelude.index(".profile")

    def test_unknown_os_family_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported os_family"):
            shell_rc_prepend("windows")

    def test_both_preludes_end_with_semicolon_for_safe_concat(self):
        """The caller concatenates with ` <user_cmd>` — the prelude
        must end with `;` so a missing user_cmd doesn't accidentally
        glue the source statement to whatever follows."""
        for os_family in ("linux", "darwin"):
            assert shell_rc_prepend(os_family).rstrip().endswith(";"), os_family


# ---------------------------------------------------------------------------
# #811: unit_path_for — sync validate-phase + health probe seam
# ---------------------------------------------------------------------------


class TestUnitPathFor:
    def test_linux_returns_systemd_unit_path(self):
        from clawrium.core.playbook_resolver import unit_path_for

        assert (
            unit_path_for("linux", "zeroclaw", "alpha")
            == "/etc/systemd/system/zeroclaw-alpha.service"
        )

    def test_linux_hermes(self):
        from clawrium.core.playbook_resolver import unit_path_for

        assert (
            unit_path_for("linux", "hermes", "bob")
            == "/etc/systemd/system/hermes-bob.service"
        )

    def test_darwin_returns_plist_path(self):
        from clawrium.core.playbook_resolver import unit_path_for

        path = unit_path_for("darwin", "hermes", "alpha")
        assert path.startswith("/Library/LaunchDaemons/")
        assert path.endswith(".plist")
        # The label is whatever core.launchd computes; assert the
        # agent_name and agent_type both appear.
        assert "alpha" in path
        assert "hermes" in path

    def test_unknown_os_family_raises(self):
        import pytest as _pytest
        from clawrium.core.playbook_resolver import unit_path_for

        with _pytest.raises(ValueError, match="unsupported os_family"):
            unit_path_for("windows", "hermes", "alpha")

    def test_darwin_openclaw_uses_plist(self):
        """ATX iter-1 W7: openclaw-on-darwin coverage (was hermes-only)."""
        from clawrium.core.playbook_resolver import unit_path_for

        path = unit_path_for("darwin", "openclaw", "oc1")
        assert path.startswith("/Library/LaunchDaemons/")
        assert path.endswith(".plist")
        assert "oc1" in path
        assert "openclaw" in path

    def test_linux_unknown_agent_type_raises(self):
        """ATX iter-3 W7: linux branch was previously unvalidated and
        would happily materialize a service path for any string. The
        iter-2 W2 fix added a `_SUPPORTED_AGENT_TYPES` check on both
        branches; this regression guard pins the linux branch.
        Without it, a typo in hosts.json (`ethos` → systemd unit
        path) would slip past the probe and surface only at restart
        — defeating the whole point of #811."""
        import pytest as _pytest
        from clawrium.core.playbook_resolver import unit_path_for

        with _pytest.raises(ValueError, match="unsupported agent_type"):
            unit_path_for("linux", "nemoclaw", "alpha")

    def test_darwin_zeroclaw_raises_value_error(self):
        """ATX iter-1 B3: zeroclaw has no launchd label prefix
        registered in `core.launchd._LABEL_PREFIX_BY_TYPE` (zeroclaw
        is linux-only today). `unit_path_for("darwin", "zeroclaw",
        ...)` must raise `ValueError` so the probe call sites can
        wrap it in their typed errors. A regression in
        `_LABEL_PREFIX_BY_TYPE` (e.g. adding a zeroclaw entry
        without also adding the platform support) would otherwise
        silently materialize a bogus plist path."""
        import pytest as _pytest
        from clawrium.core.playbook_resolver import unit_path_for

        with _pytest.raises(ValueError):
            unit_path_for("darwin", "zeroclaw", "alpha")

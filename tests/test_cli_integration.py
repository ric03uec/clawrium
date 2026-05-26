"""Tests for integration CLI commands."""

import json
from unittest.mock import patch
from typer.testing import CliRunner

from clawrium.cli.main import app
from clawrium.core.integrations import INTEGRATIONS_FILE


runner = CliRunner()


class TestIntegrationTypes:
    """Tests for 'clm integration types' command."""

    def test_types_lists_all_integrations(self, isolated_config):
        """'clm integration types' lists all supported integration types."""
        result = runner.invoke(app, ["integration", "types"])

        assert result.exit_code == 0
        assert "github" in result.output
        assert "gitlab" in result.output
        assert "atlassian" in result.output
        assert "linear" in result.output
        assert "notion" in result.output
        assert "git" in result.output


class TestIntegrationList:
    """Tests for 'clm integration list' command."""

    def test_list_empty(self, isolated_config):
        """'clm integration list' shows message when no integrations."""
        result = runner.invoke(app, ["integration", "list"])

        assert result.exit_code == 0
        assert "no integrations configured" in result.output.lower()

    def test_list_with_integrations(self, isolated_config):
        """'clm integration list' shows configured integrations."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        integrations = [
            {
                "name": "work-github",
                "type": "github",
                "created_at": "2026-04-15T10:00:00Z",
            },
            {
                "name": "company-atlassian",
                "type": "atlassian",
                "created_at": "2026-04-15T11:00:00Z",
            },
        ]
        (isolated_config / INTEGRATIONS_FILE).write_text(json.dumps(integrations))

        result = runner.invoke(app, ["integration", "list"])

        assert result.exit_code == 0
        assert "work-github" in result.output
        assert "company-atlassian" in result.output
        assert "github" in result.output
        assert "atlassian" in result.output


class TestIntegrationAdd:
    """Tests for 'clm integration add' command."""

    def test_add_requires_type(self, isolated_config):
        """'clm integration add' requires --type option."""
        result = runner.invoke(app, ["integration", "add", "my-github"])

        assert result.exit_code != 0
        assert (
            "type" in result.output.lower() or "missing option" in result.output.lower()
        )

    def test_add_rejects_invalid_type(self, isolated_config):
        """'clm integration add' rejects invalid integration type."""
        result = runner.invoke(
            app,
            ["integration", "add", "my-int", "--type", "invalid-type"],
            input="\n",  # Cancel prompt
        )

        assert result.exit_code == 1
        assert "invalid integration type" in result.output.lower()

    def test_add_rejects_invalid_name(self, isolated_config):
        """'clm integration add' rejects invalid integration name."""
        result = runner.invoke(
            app, ["integration", "add", "123invalid", "--type", "github"], input="\n"
        )

        assert result.exit_code == 1
        assert "invalid" in result.output.lower() and "name" in result.output.lower()

    def test_add_prompts_for_credentials(self, isolated_config):
        """'clm integration add' prompts for credentials."""
        isolated_config.mkdir(parents=True, exist_ok=True)

        # Provide token value when prompted
        result = runner.invoke(
            app,
            ["integration", "add", "my-github", "--type", "github"],
            input="ghp_test123\n",
        )

        assert result.exit_code == 0
        assert "added successfully" in result.output.lower()

        # Verify integration was saved
        integrations_file = isolated_config / INTEGRATIONS_FILE
        assert integrations_file.exists()
        integrations = json.loads(integrations_file.read_text())
        assert len(integrations) == 1
        assert integrations[0]["name"] == "my-github"
        assert integrations[0]["type"] == "github"

    def test_add_rejects_duplicate(self, isolated_config):
        """'clm integration add' rejects duplicate name."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        result = runner.invoke(
            app,
            ["integration", "add", "my-github", "--type", "github"],
            input="ghp_test\n",
        )

        assert result.exit_code == 1
        assert "already exists" in result.output.lower()


class TestIntegrationAddGit:
    """Tests for `clm integration add --type git` (#531)."""

    def _run_git_add(self, name: str, input_text: str):
        return runner.invoke(
            app, ["integration", "add", name, "--type", "git"], input=input_text
        )

    def test_git_add_prefills_identity_from_local_git_config(self, isolated_config):
        """Identity defaults shell out to `git config --global` and accept on Enter."""
        isolated_config.mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, *args, **kwargs):
            assert cmd[:3] == ["git", "config", "--global"]
            stdout_map = {"user.name": "Alice Local\n", "user.email": "alice@local\n"}
            class R:
                returncode = 0
                stdout = stdout_map.get(cmd[3], "")
            return R()

        with patch("clawrium.cli.integration.subprocess.run", side_effect=fake_run):
            # Press Enter for all five prompts → accept defaults.
            result = self._run_git_add("my-git", "\n\n\n\n\n")

        assert result.exit_code == 0, result.output
        from clawrium.core.integrations import get_integration_credentials
        creds = get_integration_credentials("my-git")
        assert creds["GIT_USER_NAME"] == "Alice Local"
        assert creds["GIT_USER_EMAIL"] == "alice@local"
        assert creds["GIT_INIT_DEFAULT_BRANCH"] == "main"
        assert creds["GIT_PULL_REBASE"] == "false"
        assert creds["GIT_CORE_EDITOR"] == "vim"

    def test_git_add_handles_missing_local_git_config(self, isolated_config):
        """Missing/erroring `git config` falls back to empty identity prompts.

        The user types identity values; static defaults still apply when Enter
        is pressed for optional fields.
        """
        isolated_config.mkdir(parents=True, exist_ok=True)

        class FailR:
            returncode = 1
            stdout = ""

        with patch(
            "clawrium.cli.integration.subprocess.run",
            side_effect=FileNotFoundError("git not installed"),
        ):
            # Provide identity then accept defaults for the three optionals.
            result = self._run_git_add(
                "my-git", "Bob\nbob@example.com\n\n\n\n"
            )

        assert result.exit_code == 0, result.output
        from clawrium.core.integrations import get_integration_credentials
        creds = get_integration_credentials("my-git")
        assert creds["GIT_USER_NAME"] == "Bob"
        assert creds["GIT_USER_EMAIL"] == "bob@example.com"
        assert creds["GIT_INIT_DEFAULT_BRANCH"] == "main"
        assert creds["GIT_PULL_REBASE"] == "false"
        assert creds["GIT_CORE_EDITOR"] == "vim"
        # Suppress unused-class warnings from linters.
        _ = FailR

    def test_git_add_operator_override_persists(self, isolated_config):
        """Operator-supplied non-default values are stored verbatim."""
        isolated_config.mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, *args, **kwargs):
            class R:
                returncode = 0
                stdout = ""
            return R()

        with patch("clawrium.cli.integration.subprocess.run", side_effect=fake_run):
            result = self._run_git_add(
                "my-git", "Carol\ncarol@example.com\ntrunk\ntrue\nnano\n"
            )

        assert result.exit_code == 0, result.output
        from clawrium.core.integrations import get_integration_credentials
        creds = get_integration_credentials("my-git")
        assert creds["GIT_USER_NAME"] == "Carol"
        assert creds["GIT_USER_EMAIL"] == "carol@example.com"
        assert creds["GIT_INIT_DEFAULT_BRANCH"] == "trunk"
        assert creds["GIT_PULL_REBASE"] == "true"
        assert creds["GIT_CORE_EDITOR"] == "nano"

    def test_git_add_static_defaults_shown_in_prompt(self, isolated_config):
        """Static defaults (`main`, `false`, `vim`) are surfaced in the prompt text."""
        isolated_config.mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, *args, **kwargs):
            class R:
                returncode = 0
                stdout = "Dora\n" if cmd[3] == "user.name" else "dora@example.com\n"
            return R()

        with patch("clawrium.cli.integration.subprocess.run", side_effect=fake_run):
            result = self._run_git_add("my-git", "\n\n\n\n\n")

        assert result.exit_code == 0, result.output
        # typer renders defaults as `[default]` in the prompt.
        assert "main" in result.output
        assert "false" in result.output
        assert "vim" in result.output


class TestIntegrationAddGitSanitization:
    """Newlines in git fields must never reach storage (#534 ATX iter-1 B1)."""

    def test_newline_in_user_name_is_flattened_at_storage(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, *args, **kwargs):
            class R:
                returncode = 0
                stdout = ""
            return R()

        # typer.prompt reads a line via input(); the test runner supplies
        # one credential per newline. We cannot inject a literal \n into a
        # prompt response, but the sanitizer also strips \r — and bash-style
        # paste exploits commonly use \r. Mock the prompt return directly.
        with patch("clawrium.cli.integration.subprocess.run", side_effect=fake_run), \
             patch(
                 "clawrium.cli.integration.typer.prompt",
                 side_effect=[
                     "Alice\r[credential]\thelper=/evil",
                     "alice@example.com",
                     "main",
                     "false",
                     "vim",
                 ],
             ):
            result = runner.invoke(
                app, ["integration", "add", "g1", "--type", "git"], input=""
            )

        assert result.exit_code == 0, result.output
        from clawrium.core.integrations import get_integration_credentials
        stored = get_integration_credentials("g1")["GIT_USER_NAME"]
        assert "\r" not in stored
        assert "\n" not in stored
        # The injection token is no longer a section header in the rendered
        # template (because the literal newline is gone) — kept literal here.
        assert stored.startswith("Alice")


class TestIntegrationCredentialsUpdateGitSanitization:
    """The `credentials --update` path must also sanitize git fields (T1)."""

    def test_update_strips_carriage_returns(self, isolated_config):
        isolated_config.mkdir(parents=True, exist_ok=True)
        # Seed an existing git integration with clean values.
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "g", "type": "git"}])
        )
        from clawrium.core.integrations import (
            set_integration_credential,
            get_integration_credentials,
        )

        set_integration_credential("g", "GIT_USER_NAME", "Alice")
        set_integration_credential("g", "GIT_USER_EMAIL", "alice@example.com")

        with patch(
            "clawrium.cli.integration.typer.prompt",
            side_effect=[
                "Mallory\r[credential]\thelper=/evil",  # GIT_USER_NAME override
                "",  # GIT_USER_EMAIL — keep existing
                "",  # GIT_INIT_DEFAULT_BRANCH
                "",  # GIT_PULL_REBASE
                "",  # GIT_CORE_EDITOR
            ],
        ):
            result = runner.invoke(
                app, ["integration", "credentials", "g", "--update"]
            )

        assert result.exit_code == 0, result.output
        stored = get_integration_credentials("g")["GIT_USER_NAME"]
        assert "\r" not in stored
        assert "\n" not in stored

    def test_update_lf_newline_in_user_name(self, isolated_config):
        """A literal \\n payload via mocked prompt is flattened (W4)."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "g", "type": "git"}])
        )
        from clawrium.core.integrations import (
            set_integration_credential,
            get_integration_credentials,
        )

        set_integration_credential("g", "GIT_USER_NAME", "Alice")
        set_integration_credential("g", "GIT_USER_EMAIL", "alice@example.com")

        with patch(
            "clawrium.cli.integration.typer.prompt",
            side_effect=[
                "Mallory\n[credential]\nhelper=/evil",
                "",
                "",
                "",
                "",
            ],
        ):
            result = runner.invoke(
                app, ["integration", "credentials", "g", "--update"]
            )
        assert result.exit_code == 0, result.output
        stored = get_integration_credentials("g")["GIT_USER_NAME"]
        assert "\n" not in stored


def test_sanitize_git_field_strips_null_byte():
    """Direct unit test for the NUL clause (T3)."""
    from clawrium.cli.integration import _sanitize_git_field

    assert _sanitize_git_field("Alice\x00[core]") == "Alice[core]"
    assert _sanitize_git_field("\x00\x00\x00") == ""
    # \r → "" (dropped), \n → " " (flattened), \x00 → "" (dropped)
    assert _sanitize_git_field("Alice\rBob\nCarol\x00Dave") == "AliceBob CarolDave"


def test_sanitize_git_field_strips_all_three():
    """Comprehensive: CR removed, LF → space, NUL removed."""
    from clawrium.cli.integration import _sanitize_git_field

    out = _sanitize_git_field("a\rb\nc\x00d")
    assert "\r" not in out
    assert "\n" not in out
    assert "\x00" not in out
    assert "a" in out and "d" in out


class TestIntegrationShow:
    """Tests for 'clm integration show' command."""

    def test_show_not_found(self, isolated_config):
        """'clm integration show' errors when integration not found."""
        result = runner.invoke(app, ["integration", "show", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_show_existing_integration(self, isolated_config):
        """'clm integration show' displays integration details."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps(
                [
                    {
                        "name": "work-github",
                        "type": "github",
                        "created_at": "2026-04-15T10:00:00Z",
                        "updated_at": "2026-04-15T10:00:00Z",
                    }
                ]
            )
        )

        result = runner.invoke(app, ["integration", "show", "work-github"])

        assert result.exit_code == 0
        assert "work-github" in result.output
        assert "github" in result.output


class TestIntegrationRemove:
    """Tests for 'clm integration remove' command."""

    def test_remove_not_found(self, isolated_config):
        """'clm integration remove' errors when integration not found."""
        result = runner.invoke(app, ["integration", "remove", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_remove_prompts_for_confirmation(self, isolated_config):
        """'clm integration remove' prompts for confirmation."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        # Decline confirmation
        result = runner.invoke(app, ["integration", "remove", "my-github"], input="n\n")

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()

        # Verify not removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 1

    def test_remove_with_force(self, isolated_config):
        """'clm integration remove --force' skips confirmation."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with (
            patch(
                "clawrium.core.integrations.remove_integration_credentials",
                return_value=True,
            ),
            patch(
                "clawrium.core.integrations.find_agents_using_integration",
                return_value=[],
            ),
        ):
            result = runner.invoke(
                app, ["integration", "remove", "my-github", "--force"]
            )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

        # Verify removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 0

    def test_remove_with_confirmation(self, isolated_config):
        """'clm integration remove' removes when confirmed."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with (
            patch(
                "clawrium.core.integrations.remove_integration_credentials",
                return_value=True,
            ),
            patch(
                "clawrium.core.integrations.find_agents_using_integration",
                return_value=[],
            ),
        ):
            result = runner.invoke(
                app, ["integration", "remove", "my-github"], input="y\n"
            )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

    def test_remove_blocked_when_in_use(self, isolated_config):
        """'clm integration remove' fails when integration in use by agents."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.find_agents_using_integration",
            return_value=[("host1", "agent1")],
        ):
            result = runner.invoke(
                app, ["integration", "remove", "my-github"], input="y\n"
            )

        assert result.exit_code == 1
        assert "assigned to agents" in result.output.lower()
        assert "host1:agent1" in result.output

        # Verify NOT removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 1

    def test_remove_force_overrides_in_use_check(self, isolated_config):
        """'clm integration remove --force' removes even when in use."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "my-github", "type": "github"}])
        )

        with (
            patch(
                "clawrium.core.integrations.remove_integration_credentials",
                return_value=True,
            ),
            patch(
                "clawrium.core.integrations.find_agents_using_integration",
                return_value=[("host1", "agent1")],
            ),
        ):
            result = runner.invoke(
                app, ["integration", "remove", "my-github", "--force"]
            )

        assert result.exit_code == 0
        assert "removed successfully" in result.output.lower()

        # Verify removed
        integrations = json.loads((isolated_config / INTEGRATIONS_FILE).read_text())
        assert len(integrations) == 0


class TestIntegrationCredentials:
    """Tests for 'clm integration credentials' command."""

    def test_credentials_not_found(self, isolated_config):
        """'clm integration credentials' errors when integration not found."""
        result = runner.invoke(app, ["integration", "credentials", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_credentials_shows_status(self, isolated_config):
        """'clm integration credentials' shows credential status."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "work-github", "type": "github"}])
        )

        with patch(
            "clawrium.core.integrations.get_integration_credentials",
            return_value={"GITHUB_TOKEN": "ghp_test123"},
        ):
            result = runner.invoke(app, ["integration", "credentials", "work-github"])

        assert result.exit_code == 0
        assert "GITHUB_TOKEN" in result.output
        # Token should be masked
        assert "ghp_test123" not in result.output


class TestIntegrationStaleType:
    """Tests for CLI behavior on integration records with an unknown type.

    A stale `jira`/`confluence` record (or any manual edit pointing at a type
    not in INTEGRATION_TYPES) must NOT raise an unhandled exception, must
    surface a remediation message, and — for non-display commands — must exit
    non-zero so script chains don't silently proceed.
    """

    def _seed_stale_jira(self, isolated_config):
        # Deliberately pick a name that does NOT contain 'jira' so that an
        # assertion like `'jira' in result.output` proves the *type* was
        # rendered, not just the name.
        isolated_config.mkdir(parents=True, exist_ok=True)
        (isolated_config / INTEGRATIONS_FILE).write_text(
            json.dumps([{"name": "stale-ticket", "type": "jira"}])
        )

    def test_show_with_unknown_type_exits_nonzero_with_remediation(
        self, isolated_config
    ):
        self._seed_stale_jira(isolated_config)
        result = runner.invoke(app, ["integration", "show", "stale-ticket"])

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"Unexpected exception: {result.exception!r}"
        )
        assert "not a known type" in result.output.lower()
        assert "Error:" in result.output
        # Remediation must interpolate the actual integration name, not <name>.
        assert "stale-ticket" in result.output
        assert "<name>" not in result.output

    def test_credentials_read_with_unknown_type_exits_nonzero(self, isolated_config):
        self._seed_stale_jira(isolated_config)
        result = runner.invoke(app, ["integration", "credentials", "stale-ticket"])

        assert result.exit_code == 1
        assert "not a known type" in result.output.lower()
        assert "Error:" in result.output
        assert "stale-ticket" in result.output
        assert "<name>" not in result.output

    def test_credentials_update_with_unknown_type_exits_nonzero(self, isolated_config):
        self._seed_stale_jira(isolated_config)
        result = runner.invoke(
            app, ["integration", "credentials", "stale-ticket", "--update"]
        )

        assert result.exit_code == 1
        assert "not a known type" in result.output.lower()
        assert "Error:" in result.output
        assert "stale-ticket" in result.output
        assert "<name>" not in result.output

    def test_list_marks_unknown_type_with_indicator(self, isolated_config):
        self._seed_stale_jira(isolated_config)
        result = runner.invoke(app, ["integration", "list"])

        assert result.exit_code == 0
        # Both halves of the rendered cell must survive: the stale type name
        # and the "(unknown)" suffix.
        assert "(unknown)" in result.output
        assert "jira" in result.output
        assert "stale-ticket" in result.output

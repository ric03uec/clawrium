"""Pi chat playbooks keep native output encrypted in runner events (#1038)."""

from pathlib import Path
import os
import re
import subprocess

import pytest
import jinja2
import yaml


PLAYBOOKS = (
    Path("src/clawrium/platform/registry/pi/playbooks/chat.yaml"),
    Path("src/clawrium/platform/registry/pi/playbooks/chat_macos.yaml"),
)


def test_macos_chat_guard_accepts_real_dscl_output_and_rejects_mismatch():
    play = yaml.safe_load(PLAYBOOKS[1].read_text())[0]
    rules = next(
        task
        for task in play["tasks"]
        if task["name"] == "Verify Pi chat ownership binding"
    )["ansible.builtin.assert"]["that"]
    facts = {
        "agent_name": "pi-demo",
        "pi_home": "/Users/pi-demo",
        "pi_marker_data": {
            "schema": 2,
            "agent_name": "pi-demo",
            "home": "/Users/pi-demo",
            "uid": 501,
            "transaction_id": "12345678-1234-1234-1234-123456789abc",
        },
        "pi_account_uid": {"stdout": "UniqueID: 501\n"},
        "pi_account_home": {"stdout": "NFSHomeDirectory: /Users/pi-demo\n"},
        "pi_account_comment": {
            "stdout": "Comment: clawrium-pi-12345678-1234-1234-1234-123456789abc\n"
        },
    }
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
        pattern, replacement, value
    )

    def evaluate(values):
        return all(
            env.from_string("{{ " + rule + " }}").render(values) == "True"
            for rule in rules
        )

    assert evaluate(facts)
    facts["pi_account_uid"]["stdout"] = "UniqueID: 502\n"
    assert not evaluate(facts)
    facts["pi_account_uid"]["stdout"] = "UniqueID: 501\n"
    facts["pi_account_home"]["stdout"] = "NFSHomeDirectory: /Users/other\n"
    assert not evaluate(facts)
    facts["pi_account_home"]["stdout"] = "NFSHomeDirectory: /Users/pi-demo\n"
    facts["pi_account_comment"]["stdout"] = "Comment: clawrium-pi-wrong\n"
    assert not evaluate(facts)


@pytest.mark.parametrize("path", PLAYBOOKS)
@pytest.mark.parametrize(
    "provider_env,symlink",
    [
        ("AWS_PROFILE=p\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/../../escape\n", False),
        ("OPENROUTER_API_KEY=x\nAWS_PROFILE=p\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n", False),
        ("AWS_PROFILE=p\nAWS_PROFILE=q\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n", False),
        ("AWS_PROFILE=p\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n", True),
    ],
)
def test_pi_chat_bootstrap_rejects_untrusted_provider_environment(
    path: Path, provider_env: str, symlink: bool, tmp_path: Path
):
    """Execute the production chat bootstrap, not a parser reimplementation."""
    play = yaml.safe_load(path.read_text())[0]
    home = tmp_path / "pi-home"
    env_file = home / ".pi" / "agent" / "clawrium-provider.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(provider_env)
    if symlink:
        target = tmp_path / "provider-config"
        target.write_text("[profile p]\n")
        (env_file.parent / "clawrium-aws-config").symlink_to(target)
    result = subprocess.run(
        ["/bin/bash", "-c", play["vars"]["pi_chat_capture_bootstrap"], "test", "ignored", "ignored", "/bin/true"],
        text=True, capture_output=True, env={**os.environ, "HOME": str(home)}, check=False,
    )
    assert result.returncode == 126


def test_pi_chat_playbooks_use_cms_result_transport_without_raw_output_events():
    for path in PLAYBOOKS:
        play = yaml.safe_load(path.read_text())[0]
        rendered = path.read_text()
        assert "pi_chat_recipient_certificate" in rendered
        assert "openssl cms -encrypt" in rendered
        assert "PI_CHAT_RESULT=" in rendered
        assert "PI_CHAT_STDOUT=" not in rendered
        assert "PI_CHAT_STDERR=" not in rendered
        assert '. "$HOME/.pi/agent/clawrium-provider.env"' not in rendered
        assert "OPENROUTER_API_KEY=${line#OPENROUTER_API_KEY=}" in rendered
        assert "AWS_PROFILE=${line#AWS_PROFILE=}" in rendered
        assert "AWS_REGION=${line#AWS_REGION=}" in rendered
        assert "AWS_CONFIG_FILE" in rendered
        # Pi 0.73.1's documented Bedrock provider consumes AWS_PROFILE and
        # AWS_REGION through the AWS SDK; it does not need to discover or run
        # an aws binary during a chat/exec. Keep the trusted PATH and do not
        # introduce AWS_CLI_PATH or a user-controlled command lookup here.
        assert "command -v aws" not in rendered
        assert "AWS_CLI_PATH" not in rendered
        assert "PATH=/usr/bin:/bin; export PATH;" in rendered
        assert "export AWS_PROFILE AWS_REGION AWS_CONFIG_FILE" in rendered
        assert "set -o pipefail" in rendered
        task = next(
            task
            for task in play["tasks"]
            if task["name"] == "Run finite Pi chat command as dedicated agent user"
        )
        assert task["no_log"] is True
        switch_at = next(
            i
            for i, task in enumerate(play["tasks"])
            if task["name"] == "Run finite Pi chat command as dedicated agent user"
        )
        binding_at = next(
            i
            for i, task in enumerate(play["tasks"])
            if task["name"] == "Verify Pi chat ownership binding"
        )
        assert binding_at < switch_at
        binding = play["tasks"][binding_at]["ansible.builtin.assert"]
        assert any("agent_name" in rule for rule in binding["that"])
        assert any("uid" in rule for rule in binding["that"])
        assert any("home" in rule for rule in binding["that"])

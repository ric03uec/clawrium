"""Pi chat playbooks keep native output encrypted in runner events (#1038)."""

from pathlib import Path
import re

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


def test_pi_chat_playbooks_use_cms_result_transport_without_raw_output_events():
    for path in PLAYBOOKS:
        play = yaml.safe_load(path.read_text())[0]
        rendered = path.read_text()
        assert "pi_chat_recipient_certificate" in rendered
        assert "openssl cms -encrypt" in rendered
        assert "PI_CHAT_RESULT=" in rendered
        assert "PI_CHAT_STDOUT=" not in rendered
        assert "PI_CHAT_STDERR=" not in rendered
        assert '. "$HOME/.pi/agent/clawrium-openrouter.env"' not in rendered
        assert "OPENROUTER_API_KEY=${line#OPENROUTER_API_KEY=}" in rendered
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

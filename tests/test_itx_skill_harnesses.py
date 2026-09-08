"""Contracts for sharing canonical ITX skills across assistant harnesses."""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parent.parent
CANONICAL_SKILLS = ROOT / ".claude" / "skills"
PI_EXTENSION = ROOT / ".pi" / "extensions" / "itx-command-aliases.js"
EXPECTED_ITX_SKILLS = {
    "itx-bug-new",
    "itx-bug-update",
    "itx-execute",
    "itx-issue-new",
    "itx-issue-update",
    "itx-note",
    "itx-plan-create",
    "itx-plan-scaffold",
    "itx-pr-status",
    "itx-release",
    "itx-review-pr",
    "itx-triage",
    "itx-verify",
}


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text()
    assert text.startswith("---\n"), f"Missing frontmatter: {path}"
    return yaml.safe_load(text.split("---", 2)[1])


def test_canonical_itx_skill_set_and_names() -> None:
    skill_files = sorted(CANONICAL_SKILLS.glob("itx-*/SKILL.md"))
    names = []

    for skill_file in skill_files:
        name = _frontmatter(skill_file)["name"]
        assert isinstance(name, str)
        assert re.fullmatch(r"[a-z0-9-]{1,64}", name)
        assert name == skill_file.parent.name
        names.append(name)

    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_ITX_SKILLS


def test_opencode_has_no_itx_shadows_or_legacy_names() -> None:
    command_shadows = []
    for command_dir in ("command", "commands"):
        root = ROOT / ".opencode" / command_dir
        for command_file in root.rglob("*.md"):
            name = command_file.stem
            source = command_file.read_text()
            if source.startswith("---\n"):
                configured_name = _frontmatter(command_file).get("name")
                if isinstance(configured_name, str):
                    name = configured_name
            if name.startswith(("itx-", "itx:")):
                command_shadows.append(command_file)
    assert not command_shadows

    skill_shadows = []
    for skill_dir in ("skill", "skills"):
        root = ROOT / ".opencode" / skill_dir
        for skill_file in root.rglob("SKILL.md"):
            name = str(_frontmatter(skill_file).get("name", ""))
            if name.startswith(("itx-", "itx:")):
                skill_shadows.append(skill_file)
    assert not skill_shadows


def test_pi_loads_canonical_skills() -> None:
    settings = json.loads((ROOT / ".pi" / "settings.json").read_text())

    assert settings["skills"] == ["../.claude/skills"]
    assert settings["enableSkillCommands"] is True


def test_pi_registers_exact_aliases_and_preserves_arguments() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Pi requires Node.js, which is not installed")

    script = r"""
const extension = await import(process.argv[1]);
const expected = JSON.parse(process.argv[2]);
const commands = new Map();
const sent = [];

extension.default({
  registerCommand(name, definition) {
    if (commands.has(name)) throw new Error(`duplicate command: ${name}`);
    commands.set(name, definition);
  },
  sendUserMessage(message, options) {
    sent.push({ message, options });
  },
});

const names = [...commands.keys()].sort();
if (JSON.stringify(names) !== JSON.stringify(expected)) {
  throw new Error(`unexpected aliases: ${JSON.stringify(names)}`);
}

await commands.get("itx-release").handler("26.9.0 --dry-run");
await commands.get("itx-bug-update").handler("");
console.log(JSON.stringify({ names, sent }));
"""
    result = subprocess.run(
        [
            node,
            "--input-type=module",
            "--eval",
            script,
            PI_EXTENSION.as_uri(),
            json.dumps(sorted(EXPECTED_ITX_SKILLS)),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert set(payload["names"]) == EXPECTED_ITX_SKILLS
    assert payload["sent"] == [
        {
            "message": "/skill:itx-release 26.9.0 --dry-run",
            "options": {
                "deliverAs": "followUp",
                "expandPromptTemplates": True,
            },
        },
        {
            "message": "/skill:itx-bug-update",
            "options": {
                "deliverAs": "followUp",
                "expandPromptTemplates": True,
            },
        },
    ]


def test_review_transport_is_not_pinned_to_one_harness() -> None:
    config = json.loads((ROOT / ".claude" / "itx-config.json").read_text())
    review_skill = (
        CANONICAL_SKILLS / "itx-review-pr" / "SKILL.md"
    ).read_text()
    execute_skill = (CANONICAL_SKILLS / "itx-execute" / "SKILL.md").read_text()

    assert config["mcp"]["review_enabled"] is True
    assert "review_tool" not in config["mcp"]
    assert "mcp__atx__request_review" not in review_skill
    assert "ATX via MCP" in review_skill
    assert "atx review request" in review_skill
    assert "manual review" in review_skill.lower()

    for workflow, terminal_step in (
        (review_skill, "Manual review"),
        (execute_skill, "Skip ATX"),
    ):
        normalized = " ".join(workflow.split())
        mcp_fallback = normalized.index("MCP is unavailable, fails, or times out")
        cli_step = normalized.index("ATX via CLI")
        cli_binary = normalized.index("command -v atx", cli_step)
        cli_status = normalized.index("atx server status", cli_binary)
        running = normalized.index("Running: true", cli_status)
        cli_fallback = normalized.index(
            "CLI is unavailable, stopped, fails, or times out"
        )
        terminal = normalized.index(terminal_step, cli_fallback)
        assert (
            mcp_fallback
            < cli_step
            < cli_binary
            < cli_status
            < running
            < cli_fallback
            < terminal
        )

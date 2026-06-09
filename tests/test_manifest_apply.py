"""Tests for the manifest apply/diff/delete pipeline.

Covers: parse_file (multi-doc), validate_refs, compute (apply + idempotent +
attach/detach diffs), and the CLI surface for apply/diff/delete.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from clawrium.core.manifest.parser import parse_file, parse_directory
from clawrium.core.manifest.schema import ManifestDocument
from clawrium.core.manifest.validator import validate_refs, collect_secret_refs
from clawrium.core.manifest.differ import compute
from clawrium.core.manifest.state import ActualState, ActualAgent


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_yaml(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


def _make_empty_actual() -> ActualState:
    return ActualState(
        hosts={},
        providers={},
        channels={},
        integrations={},
        agents={},
    )


# ── fleet fixture ─────────────────────────────────────────────────────────────

FLEET_YAML = """\
apiVersion: clawrium.io/v1
kind: Host
metadata:
  name: mybox
spec:
  hostname: 192.168.1.100
  user: xclm
---
apiVersion: clawrium.io/v1
kind: Provider
metadata:
  name: anthropic-main
spec:
  type: anthropic
  config:
    defaultModel: claude-sonnet-4-5
  credentials:
    apiKey:
      secretRef: providers/anthropic-main/apiKey
---
apiVersion: clawrium.io/v1
kind: Channel
metadata:
  name: discord-main
spec:
  type: discord
  config:
    allowedUsers: ["alice", "bob"]
---
apiVersion: clawrium.io/v1
kind: Integration
metadata:
  name: gh-main
spec:
  type: github
---
apiVersion: clawrium.io/v1
kind: Agent
metadata:
  name: my-agent
spec:
  type: openclaw
  host: mybox
  provider: anthropic-main
  channels:
    - discord-main
  integrations:
    - gh-main
  lifecycle:
    autoStart: true
    autoRestart: false
"""


# ── test 1: parse_file — multi-doc YAML with all 5 kinds ─────────────────────

def test_parse_file_all_five_kinds(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)

    assert isinstance(doc, ManifestDocument)
    assert len(doc.resources) == 5
    assert len(doc.hosts()) == 1
    assert len(doc.providers()) == 1
    assert len(doc.channels()) == 1
    assert len(doc.integrations()) == 1
    assert len(doc.agents()) == 1

    host = doc.hosts()[0]
    assert host.metadata.name == "mybox"
    assert host.spec.hostname == "192.168.1.100"

    provider = doc.providers()[0]
    assert provider.metadata.name == "anthropic-main"
    assert provider.spec.type == "anthropic"
    assert provider.spec.config.defaultModel == "claude-sonnet-4-5"
    assert provider.spec.credentials.apiKey.secretRef == "providers/anthropic-main/apiKey"

    channel = doc.channels()[0]
    assert channel.metadata.name == "discord-main"
    assert channel.spec.type == "discord"
    assert "alice" in channel.spec.config.allowedUsers

    integration = doc.integrations()[0]
    assert integration.metadata.name == "gh-main"
    assert integration.spec.type == "github"

    agent = doc.agents()[0]
    assert agent.metadata.name == "my-agent"
    assert agent.spec.type == "openclaw"
    assert agent.spec.host == "mybox"
    assert agent.spec.provider == "anthropic-main"
    assert "discord-main" in agent.spec.channels
    assert "gh-main" in agent.spec.integrations
    assert agent.spec.lifecycle.autoStart is True


def test_parse_file_unknown_kind_raises(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "bad.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Banana
        metadata:
          name: oops
        spec:
          foo: bar
    """)
    with pytest.raises(ValueError, match="Unknown kind"):
        parse_file(f)


def test_parse_directory(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "01-host.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Host
        metadata:
          name: box1
        spec:
          hostname: 10.0.0.1
    """)
    _write_yaml(tmp_path, "02-provider.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Provider
        metadata:
          name: prov1
        spec:
          type: openai
    """)
    doc = parse_directory(tmp_path)
    assert len(doc.resources) == 2
    assert doc.hosts()[0].metadata.name == "box1"
    assert doc.providers()[0].metadata.name == "prov1"


# ── test 2: validate_refs ─────────────────────────────────────────────────────

def test_validate_refs_missing_host(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Agent
        metadata:
          name: orphan-agent
        spec:
          type: openclaw
          host: nonexistent-host
    """)
    doc = parse_file(f)
    errors = validate_refs(doc)
    assert len(errors) == 1
    assert "nonexistent-host" in errors[0]
    assert "orphan-agent" in errors[0]


def test_validate_refs_missing_provider(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Host
        metadata:
          name: mybox
        spec:
          hostname: 192.168.1.1
        ---
        apiVersion: clawrium.io/v1
        kind: Agent
        metadata:
          name: my-agent
        spec:
          type: openclaw
          host: mybox
          provider: missing-provider
    """)
    doc = parse_file(f)
    errors = validate_refs(doc)
    assert any("missing-provider" in e for e in errors)


def test_validate_refs_ok(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)
    errors = validate_refs(doc)
    assert errors == []


# ── test 3: compute — fresh fleet ─────────────────────────────────────────────

def test_compute_creates_for_fresh_fleet(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)
    actual = _make_empty_actual()
    cs = compute(doc, actual)

    create_kinds = {op.kind for op in cs.creates}
    assert "host" in create_kinds
    assert "provider" in create_kinds
    assert "channel" in create_kinds
    assert "integration" in create_kinds
    assert "agent" in create_kinds

    attach_kinds = {aop.resource_kind for aop in cs.attaches}
    assert "provider" in attach_kinds
    assert "channel" in attach_kinds
    assert "integration" in attach_kinds

    assert "my-agent" in cs.starts


def test_compute_no_deletes_on_apply(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)
    actual = _make_empty_actual()
    cs = compute(doc, actual)
    assert cs.deletes == []


# ── test 4: idempotent ────────────────────────────────────────────────────────

def test_compute_idempotent_noop(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)

    actual = ActualState(
        hosts={
            "mybox": {"hostname": "192.168.1.100", "alias": "mybox"},
            "192.168.1.100": {"hostname": "192.168.1.100", "alias": "mybox"},
        },
        providers={"anthropic-main": {"name": "anthropic-main", "type": "anthropic", "model": "claude-sonnet-4-5"}},
        channels={"discord-main": {"name": "discord-main", "type": "discord"}},
        integrations={"gh-main": {"name": "gh-main", "type": "github"}},
        agents={
            "my-agent": ActualAgent(
                name="my-agent",
                type="openclaw",
                host="192.168.1.100",
                status="running",
                providers=["anthropic-main"],
                channels=["discord-main"],
                integrations=["gh-main"],
                skills=[],
            )
        },
    )

    cs = compute(doc, actual)

    assert cs.is_empty(), (
        f"Expected empty changeset but got:\n"
        f"  creates={cs.creates}\n"
        f"  updates={cs.updates}\n"
        f"  attaches={cs.attaches}\n"
        f"  detaches={cs.detaches}\n"
        f"  starts={cs.starts}\n"
        f"  restarts={cs.restarts}"
    )


# ── test 5: attach / detach ───────────────────────────────────────────────────

def test_compute_attach_new_channel(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)

    actual = ActualState(
        hosts={
            "mybox": {"hostname": "192.168.1.100"},
            "192.168.1.100": {"hostname": "192.168.1.100"},
        },
        providers={"anthropic-main": {"name": "anthropic-main", "type": "anthropic"}},
        channels={"discord-main": {"name": "discord-main", "type": "discord"}},
        integrations={"gh-main": {"name": "gh-main", "type": "github"}},
        agents={
            "my-agent": ActualAgent(
                name="my-agent",
                type="openclaw",
                host="192.168.1.100",
                status="stopped",
                providers=["anthropic-main"],
                channels=[],
                integrations=["gh-main"],
                skills=[],
            )
        },
    )

    cs = compute(doc, actual)

    attach_channels = [
        aop for aop in cs.attaches
        if aop.resource_kind == "channel" and aop.resource_name == "discord-main"
    ]
    assert len(attach_channels) == 1, f"Expected channel attach, got {cs.attaches}"


def test_compute_detach_removed_integration(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Host
        metadata:
          name: mybox
        spec:
          hostname: 192.168.1.100
        ---
        apiVersion: clawrium.io/v1
        kind: Agent
        metadata:
          name: my-agent
        spec:
          type: openclaw
          host: mybox
          lifecycle:
            autoStart: false
    """)
    doc = parse_file(f)

    actual = ActualState(
        hosts={
            "mybox": {"hostname": "192.168.1.100"},
            "192.168.1.100": {"hostname": "192.168.1.100"},
        },
        providers={},
        channels={},
        integrations={},
        agents={
            "my-agent": ActualAgent(
                name="my-agent",
                type="openclaw",
                host="192.168.1.100",
                status="running",
                providers=[],
                channels=[],
                integrations=["gh-main"],
                skills=[],
            )
        },
    )

    cs = compute(doc, actual)

    detach_intgs = [
        aop for aop in cs.detaches
        if aop.resource_kind == "integration" and aop.resource_name == "gh-main"
    ]
    assert len(detach_intgs) == 1, f"Expected integration detach, got {cs.detaches}"


# ── test 6: delete mode ───────────────────────────────────────────────────────

def test_compute_delete_for_delete_flag(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Host
        metadata:
          name: mybox
        spec:
          hostname: 192.168.1.100
        ---
        apiVersion: clawrium.io/v1
        kind: Agent
        metadata:
          name: my-agent
        spec:
          type: openclaw
          host: mybox
    """)
    doc = parse_file(f)

    actual = ActualState(
        hosts={"mybox": {"hostname": "192.168.1.100"}},
        providers={},
        channels={},
        integrations={},
        agents={
            "my-agent": ActualAgent(
                name="my-agent",
                type="openclaw",
                host="192.168.1.100",
                status="running",
            )
        },
    )

    cs = compute(doc, actual, for_delete=True)
    assert len(cs.deletes) == 1
    assert cs.deletes[0].name == "my-agent"
    assert cs.deletes[0].action == "delete"
    assert cs.creates == []
    assert cs.attaches == []


def test_compute_delete_noop_for_absent_agent(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Agent
        metadata:
          name: ghost-agent
        spec:
          type: openclaw
          host: nowhere
    """)
    doc = parse_file(f)
    actual = _make_empty_actual()
    cs = compute(doc, actual, for_delete=True)
    assert cs.deletes == []
    assert any(op.name == "ghost-agent" for op in cs.noops)


# ── test 7: collect_secret_refs ───────────────────────────────────────────────

def test_collect_secret_refs(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", FLEET_YAML)
    doc = parse_file(f)
    refs = collect_secret_refs(doc)
    assert "providers/anthropic-main/apiKey" in refs


def test_collect_secret_refs_empty_when_no_credentials(tmp_path: Path) -> None:
    f = _write_yaml(tmp_path, "fleet.yaml", """\
        apiVersion: clawrium.io/v1
        kind: Host
        metadata:
          name: mybox
        spec:
          hostname: 192.168.1.100
    """)
    doc = parse_file(f)
    refs = collect_secret_refs(doc)
    assert refs == []

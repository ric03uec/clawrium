"""Tests for the ethos agent type registration in the bundled registry."""

from clawrium.core.registry import load_manifest, list_claws


def test_ethos_in_registry():
    claws = list_claws()
    assert "ethos" in claws


def test_ethos_manifest_loads():
    manifest = load_manifest("ethos")
    assert manifest["agent"]["type"] == "ethos"


def test_ethos_manifest_has_required_fields():
    manifest = load_manifest("ethos")
    assert "features" in manifest
    assert manifest["features"]["chat"]["type"] == "openai"
    assert manifest["features"]["web_ui"]["enabled"] is True
    assert manifest["features"]["web_ui"]["port_field"] == "gateway.port"
    assert "platforms" in manifest
    assert len(manifest["platforms"]) >= 1
    assert "onboarding" in manifest


def test_ethos_manifest_platforms():
    manifest = load_manifest("ethos")
    for platform in manifest["platforms"]:
        assert "version" in platform
        assert "os" in platform
        assert "os_version" in platform
        assert "arch" in platform
        deps = platform.get("requirements", {}).get("dependencies", {})
        assert "nodejs" in deps


def test_ethos_manifest_memory():
    manifest = load_manifest("ethos")
    assert manifest.get("features", {}).get("memory") is True
    assert "memory_path" in manifest.get("workspace", {})


def test_ethos_manifest_onboarding_identity_required():
    manifest = load_manifest("ethos")
    identity = manifest["onboarding"]["stages"]["identity"]
    assert identity.get("required") is True
    assert identity.get("auto_skip") is not True


def test_ethos_manifest_onboarding_stages_present():
    manifest = load_manifest("ethos")
    stages = manifest["onboarding"]["stages"]
    assert "providers" in stages
    assert "identity" in stages
    assert "channels" in stages
    assert "validate" in stages


def test_ethos_manifest_secrets_optional_keys():
    manifest = load_manifest("ethos")
    secrets = manifest.get("secrets", {})
    optional_keys = [s["key"] for s in secrets.get("optional", [])]
    assert "ANTHROPIC_API_KEY" in optional_keys
    assert "OPENAI_API_KEY" in optional_keys
    assert "TELEGRAM_BOT_TOKEN" in optional_keys
    assert "DISCORD_BOT_TOKEN" in optional_keys
    assert "SLACK_BOT_TOKEN" in optional_keys
    # Required must be empty (no mandatory secrets)
    assert secrets.get("required", []) == []


def test_ethos_manifest_web_ui_bind_loopback():
    manifest = load_manifest("ethos")
    web_ui = manifest["features"]["web_ui"]
    assert web_ui["bind"] == "loopback"


def test_ethos_playbooks_exist():
    """All required playbooks must ship in the ethos registry."""
    from importlib.resources import files

    ethos_pkg = files("clawrium.platform.registry.ethos")
    for name in (
        "install",
        "configure",
        "start",
        "stop",
        "remove",
        "exec",
        "skills_apply",
        "memory_read",
        "memory_write",
        "memory_info",
        "memory_delete",
    ):
        assert (ethos_pkg / "playbooks" / f"{name}.yaml").is_file(), (
            f"Missing ethos playbook: {name}.yaml"
        )


def test_ethos_templates_exist():
    """All required templates must ship in the ethos registry."""
    from importlib.resources import files

    ethos_pkg = files("clawrium.platform.registry.ethos")
    for name in (
        "ethos.env.j2",
        "ethos-config.yaml.j2",
        "ethos-soul.md.j2",
        "ethos-toolset.yaml.j2",
        "ethos-personality-config.yaml.j2",
        "verify_ethos.js",
    ):
        assert (ethos_pkg / "templates" / name).is_file(), (
            f"Missing ethos template: {name}"
        )


def test_ethos_install_playbook_shape():
    """The ethos install playbook must encode the install-disabled invariants."""
    from importlib.resources import files
    import yaml

    ethos_pkg = files("clawrium.platform.registry.ethos")
    playbook_path = ethos_pkg / "playbooks" / "install.yaml"
    content = playbook_path.read_text()

    assert "- hosts:" in content
    assert "agent_name" in content
    # Agent user is a service account: nologin shell reduces lateral-movement surface.
    assert "shell: /usr/sbin/nologin" in content
    # ethos binary at global path
    assert "/usr/local/bin/ethos" in content
    # Service must NOT be enabled or started in install.yaml
    data = yaml.safe_load(content)
    tasks = data[0]["tasks"]
    enable_tasks = [
        t
        for t in tasks
        if t.get("ansible.builtin.systemd", {}).get("enabled") is True
        or t.get("ansible.builtin.systemd", {}).get("state") == "started"
    ]
    assert enable_tasks == [], (
        "install.yaml must not enable or start the ethos service; "
        "configure.yaml owns the start half of the lifecycle"
    )


def test_ethos_memory_delete_no_log():
    """memory_delete.yaml must mark the file-removal task no_log: true."""
    from importlib.resources import files
    import yaml

    ethos_pkg = files("clawrium.platform.registry.ethos")
    data = yaml.safe_load((ethos_pkg / "playbooks" / "memory_delete.yaml").read_text())
    tasks = data[0]["tasks"]
    delete_tasks = [
        t
        for t in tasks
        if isinstance(t.get("ansible.builtin.file"), dict)
        and t["ansible.builtin.file"].get("state") == "absent"
    ]
    assert delete_tasks, "memory_delete.yaml: no delete task found"
    for task in delete_tasks:
        assert task.get("no_log") is True, (
            f"ethos/memory_delete.yaml task '{task.get('name')}' "
            f"must have no_log: true"
        )


def test_ethos_memory_playbooks_target_default_personality():
    """Each memory_*.yaml must point at ~/.ethos/personalities/default/."""
    from importlib.resources import files

    ethos_pkg = files("clawrium.platform.registry.ethos")
    for name in ("memory_read", "memory_write", "memory_delete", "memory_info"):
        content = (ethos_pkg / "playbooks" / f"{name}.yaml").read_text()
        assert "/.ethos/personalities/default" in content, (
            f"{name}.yaml must use ~/.ethos/personalities/default/"
        )


def test_ethos_env_template_has_gateway_key():
    """ethos.env.j2 must render ETHOS_GATEWAY_API_KEY."""
    from importlib.resources import files

    ethos_pkg = files("clawrium.platform.registry.ethos")
    content = (ethos_pkg / "templates" / "ethos.env.j2").read_text()
    assert "ETHOS_GATEWAY_API_KEY" in content
    assert "ETHOS_GATEWAY_PORT" in content


def test_ethos_env_template_has_telegram():
    """ethos.env.j2 must render TELEGRAM_BOT_TOKEN block."""
    from importlib.resources import files

    ethos_pkg = files("clawrium.platform.registry.ethos")
    content = (ethos_pkg / "templates" / "ethos.env.j2").read_text()
    assert "TELEGRAM_BOT_TOKEN" in content


# ---------------------------------------------------------------------------
# #924 (ATX B1): the five ethos config files are deployed as pre-rendered
# bytes from core/render.py:render_ethos via `ansible.builtin.copy:
# content:` tasks. If the extravar names drift between Python
# (lifecycle.configure_agent) and Ansible, the playbook silently deploys
# an empty file. These tests pin the var name for every dest and forbid a
# partial revert to server-side `template:` tasks.
# ---------------------------------------------------------------------------

def _ethos_configure_tasks():
    from importlib.resources import files

    import yaml

    ethos_pkg = files("clawrium.platform.registry.ethos")
    content = (ethos_pkg / "playbooks" / "configure.yaml").read_text()
    data = yaml.safe_load(content)
    return data[0]["tasks"]


def test_ethos_configure_copies_prerendered_bytes():
    """Every canonical config file lands via `copy: content:` reading the
    matching `prerendered_ethos_*` extravar, mode 0600."""
    copies = {}
    for task in _ethos_configure_tasks():
        block = task.get("ansible.builtin.copy") or task.get("copy")
        if isinstance(block, dict) and "content" in block:
            copies[block.get("dest", "")] = block

    for dest_suffix, var in [
        ("/.env", "prerendered_ethos_env"),
        ("}}/config.yaml", "prerendered_ethos_config_yaml"),
        ("personalities/default/SOUL.md", "prerendered_ethos_soul_md"),
        ("personalities/default/toolset.yaml", "prerendered_ethos_toolset_yaml"),
        (
            "personalities/default/config.yaml",
            "prerendered_ethos_personality_config_yaml",
        ),
    ]:
        matches = [
            block
            for dest, block in copies.items()
            if dest.endswith(dest_suffix)
        ]
        assert matches, f"no copy task lands a dest ending in {dest_suffix!r}"
        block = matches[0]
        assert block["content"].strip() == "{{ " + var + " }}", (
            f"copy task content var drifted for {dest_suffix!r}: "
            f"{block['content']!r}"
        )
        assert str(block.get("mode")) == "0600"


def test_ethos_configure_has_no_template_tasks_for_canonical_files():
    """Defense-in-depth against a partial revert (#924 B1): no `template:`
    task may render the five canonical .j2 files server-side — that is the
    dual-render-path bug class #622 closed for hermes."""
    forbidden = {
        "ethos.env.j2",
        "ethos-config.yaml.j2",
        "ethos-soul.md.j2",
        "ethos-toolset.yaml.j2",
        "ethos-personality-config.yaml.j2",
    }
    for task in _ethos_configure_tasks():
        tpl_block = task.get("ansible.builtin.template") or task.get("template")
        if not isinstance(tpl_block, dict):
            continue
        src = tpl_block.get("src", "") or ""
        assert not any(name in src for name in forbidden), (
            f"template task still renders {src!r} server-side; the five "
            f"canonical ethos files must deploy via copy: content: "
            f"(prerendered by render_ethos)"
        )


def test_ethos_registered_in_canonical_sync_renderers():
    """#924 B1: `clawctl agent sync` must render ethos through the same
    render_ethos the doctor command and configure_agent use."""
    from clawrium.core.lifecycle_canonical import _RENDERERS
    from clawrium.core.render import render_ethos

    assert _RENDERERS.get("ethos") is render_ethos


def test_ethos_registered_in_sync_cli_diff_renderers():
    """#924 B1: the `sync --dry-run --diff` renderer-name table must also
    know ethos, or the diff path reports 'no renderer for agent type'."""
    from clawrium.cli.clawctl.agent.sync import _RENDERERS as _CLI_RENDERERS

    assert _CLI_RENDERERS.get("ethos") == "render_ethos"

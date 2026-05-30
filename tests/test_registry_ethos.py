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

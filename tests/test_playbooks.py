"""Tests for Ansible playbooks structure and content."""

from pathlib import Path


def test_base_playbook_exists():
    """Test that base playbook exists."""

    # Base playbook is at src/clawrium/platform/playbooks/base.yaml
    project_root = Path(__file__).parent.parent
    base_playbook = (
        project_root / "src" / "clawrium" / "platform" / "playbooks" / "base.yaml"
    )

    assert base_playbook.exists(), "base.yaml playbook should exist"


def test_base_playbook_structure():
    """Test that base playbook has required structure."""
    import yaml

    project_root = Path(__file__).parent.parent
    base_playbook = (
        project_root / "src" / "clawrium" / "platform" / "playbooks" / "base.yaml"
    )

    content = base_playbook.read_text()

    # Check for required elements in raw content
    assert "- hosts:" in content, "Should have hosts directive"
    assert "become: yes" in content or "become: true" in content, "Should require sudo"

    # Parse YAML to validate structure and package lists
    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"

    # Extract all tasks from the first play
    tasks = data[0].get("tasks", [])

    # Find and validate Node.js installation
    # Look for the specific task "Install Node.js"
    nodejs_tasks = [t for t in tasks if t.get("name") == "Install Node.js"]
    assert len(nodejs_tasks) > 0, "Should have task to install Node.js"
    nodejs_task = nodejs_tasks[0]
    apt_module = nodejs_task.get("ansible.builtin.apt", {})
    assert apt_module.get("name") == "nodejs", (
        "Node.js task should install nodejs package"
    )

    # Find and validate build-essential installation
    build_essential_tasks = [
        t for t in tasks if "build-essential" in str(t.get("name", "")).lower()
    ]
    assert len(build_essential_tasks) > 0, "Should have task to install build-essential"
    build_essential_task = build_essential_tasks[0]
    apt_module = build_essential_task.get("ansible.builtin.apt", {})
    assert apt_module.get("name") == "build-essential", (
        "build-essential task should install build-essential package"
    )

    # Find and validate git/gh installation
    git_gh_tasks = [
        t
        for t in tasks
        if "git" in str(t.get("name", "")).lower()
        and "github" in str(t.get("name", "")).lower()
    ]
    assert len(git_gh_tasks) > 0, "Should have task to install git and GitHub CLI"
    git_gh_task = git_gh_tasks[0]
    apt_module = git_gh_task.get("ansible.builtin.apt", {})
    packages = apt_module.get("name", [])
    assert isinstance(packages, list), "git/gh task should install list of packages"
    assert "git" in packages, "Should install git package"
    assert "gh" in packages, "Should install gh (GitHub CLI) package"


def test_openclaw_install_playbook_exists():
    """Test that openclaw install playbook exists."""
    from importlib.resources import files

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_dir = openclaw_package / "playbooks"
    install_playbook = playbook_dir / "install.yaml"

    # Since we're using importlib.resources, check if it's readable
    assert install_playbook.is_file(), "install.yaml playbook should exist"


def test_openclaw_install_playbook_structure():
    """Test that openclaw install playbook has required structure."""
    from importlib.resources import files
    import yaml

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_path = openclaw_package / "playbooks" / "install.yaml"

    content = playbook_path.read_text()

    # Check for required elements
    assert "- hosts:" in content, "Should have hosts directive"
    assert "agent_name" in content, "Should use agent_name variable"
    assert "install-cli.sh" in content, "Should use official install-cli.sh installer"
    # Service can use either hardcoded path or variable for runtime binary
    assert "gateway run" in content, "Should start gateway with 'gateway run' command"
    assert "--allow-unconfigured" in content, (
        "Should allow startup before interactive setup is completed"
    )
    assert "EnvironmentFile=" in content, "Should load environment file in service"
    assert "exec-approvals.json" in content, (
        "Should write host exec approvals policy file"
    )

    # Parse YAML to ensure it's valid
    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"
    tasks = data[0].get("tasks", [])
    exec_approvals_task = next(
        t for t in tasks if t.get("name") == "Write exec approvals policy from template"
    )
    template_cfg = exec_approvals_task["ansible.builtin.template"]
    assert template_cfg["src"] == "{{ template_path }}/exec-approvals.json.j2"
    assert (
        template_cfg["dest"] == "/home/{{ agent_name }}/.openclaw/exec-approvals.json"
    )
    # W6 (ATX iter-2): `backup: yes` was removed because it accumulates
    # `exec-approvals.json.NNNN~` siblings on every reconfigure with no
    # rotation; the previous value is recoverable from the template.
    # Pin its absence so a re-add is caught.
    assert "backup" not in template_cfg
    assert exec_approvals_task["no_log"] is True
    assert any(t.get("name") == "Verify exec approvals JSON is valid" for t in tasks), (
        "Should validate exec-approvals JSON after rendering"
    )


def test_openclaw_configure_playbook_exists():
    """Test that openclaw configure playbook exists."""
    from importlib.resources import files

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_dir = openclaw_package / "playbooks"
    configure_playbook = playbook_dir / "configure.yaml"

    assert configure_playbook.is_file(), "configure.yaml playbook should exist"


def test_openclaw_configure_playbook_structure():
    """Test that openclaw configure playbook is valid and has key tasks."""
    from importlib.resources import files
    import yaml

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_path = openclaw_package / "playbooks" / "configure.yaml"

    content = playbook_path.read_text()

    assert "- hosts:" in content, "Should have hosts directive"
    assert "Verify openclaw.json configuration" in content, (
        "Should include configuration validation task"
    )
    # B2 fix: Now uses external script instead of embedded Python
    assert "verify_config.py" in content, "Should use external verify_config.py script"
    assert "Write exec approvals policy from template" in content, (
        "Should include task to manage host exec approvals policy"
    )

    data = yaml.safe_load(content)
    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"
    tasks = data[0].get("tasks", [])
    exec_approvals_task = next(
        t for t in tasks if t.get("name") == "Write exec approvals policy from template"
    )
    template_cfg = exec_approvals_task["ansible.builtin.template"]
    assert template_cfg["src"] == "{{ template_path }}/exec-approvals.json.j2"
    assert (
        template_cfg["dest"] == "/home/{{ agent_name }}/.openclaw/exec-approvals.json"
    )
    # W6 (ATX iter-2): `backup: yes` was removed because it accumulates
    # `exec-approvals.json.NNNN~` siblings on every reconfigure with no
    # rotation; the previous value is recoverable from the template.
    # Pin its absence so a re-add is caught.
    assert "backup" not in template_cfg
    assert exec_approvals_task["no_log"] is True
    assert any(t.get("name") == "Verify exec approvals JSON is valid" for t in tasks), (
        "Should validate exec-approvals JSON after rendering"
    )


def test_openclaw_start_playbook_uses_openclaw_process_check():
    """Start playbook should verify openclaw process, not node."""
    from importlib.resources import files
    import yaml

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_path = openclaw_package / "playbooks" / "start.yaml"

    content = playbook_path.read_text()
    data = yaml.safe_load(content)

    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"
    assert "pgrep -u {{ agent_name }} openclaw" in content
    assert "pgrep -u {{ agent_name }} node" not in content


def test_openclaw_stop_playbook_uses_openclaw_process_check():
    """Stop playbook should verify openclaw process, not node."""
    from importlib.resources import files
    import yaml

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_path = openclaw_package / "playbooks" / "stop.yaml"

    content = playbook_path.read_text()
    data = yaml.safe_load(content)

    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"
    assert "pgrep -u {{ agent_name }} openclaw" in content
    assert "pgrep -u {{ agent_name }} node" not in content


def test_openclaw_configure_playbook_has_workspace_tasks():
    """Configure playbook should have workspace sync tasks."""
    from importlib.resources import files
    import yaml

    openclaw_package = files("clawrium.platform.registry.openclaw")
    playbook_path = openclaw_package / "playbooks" / "configure.yaml"

    content = playbook_path.read_text()
    data = yaml.safe_load(content)

    assert isinstance(data, list), "Playbook should be a list of plays"
    assert len(data) > 0, "Playbook should have at least one play"

    # Get all task names
    tasks = data[0].get("tasks", [])
    task_names = [t.get("name", "") for t in tasks]

    # Verify workspace tasks exist
    assert any("workspace directory" in name.lower() for name in task_names), (
        "Should have workspace directory creation task"
    )
    assert any("soul.md" in name.lower() for name in task_names), (
        "Should have SOUL.md copy task"
    )
    assert any("agents.md" in name.lower() for name in task_names), (
        "Should have AGENTS.md render task"
    )
    assert any("tools.md" in name.lower() for name in task_names), (
        "Should have TOOLS.md render task"
    )
    assert any("identity.md" in name.lower() for name in task_names), (
        "Should have IDENTITY.md render task"
    )


def test_identity_templates_exist():
    """Identity templates should exist for workspace sync."""
    from importlib.resources import files

    openclaw_package = files("clawrium.platform.registry.openclaw")
    template_dir = openclaw_package / "templates"

    # Verify templates exist
    assert (template_dir / "AGENTS.md.j2").is_file(), (
        "AGENTS.md.j2 template should exist"
    )
    assert (template_dir / "TOOLS.md.j2").is_file(), "TOOLS.md.j2 template should exist"
    assert (template_dir / "IDENTITY.md.j2").is_file(), (
        "IDENTITY.md.j2 template should exist"
    )
    assert (template_dir / "exec-approvals.json.j2").is_file(), (
        "exec-approvals.json.j2 template should exist"
    )


def test_verify_config_script_exists():
    """B2 fix: verify_config.py script should exist for config validation."""
    from importlib.resources import files

    openclaw_package = files("clawrium.platform.registry.openclaw")
    template_dir = openclaw_package / "templates"

    verify_script = template_dir / "verify_config.py"
    assert verify_script.is_file(), "verify_config.py should exist"

    # Verify it's a valid Python script
    content = verify_script.read_text()
    assert "#!/usr/bin/env python3" in content, "Should have Python shebang"
    assert "def main():" in content, "Should have main function"
    assert "sys.exit" in content, "Should use sys.exit for return codes"

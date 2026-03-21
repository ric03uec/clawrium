# Phase 2: Host Management - Research

**Researched:** 2026-03-20
**Domain:** SSH connection management, hardware detection via Ansible, host configuration storage
**Confidence:** HIGH

## Summary

Host management requires three key capabilities: (1) SSH connection testing and configuration, (2) hardware detection via ansible-runner, and (3) JSON-based host storage with schema validation. The Python ecosystem provides mature, well-tested libraries for all three domains.

**Primary recommendations:**
- Use **Paramiko 4.0.0** for SSH connection testing with native SSH config support
- Use **ansible-runner 2.4.3** with the setup module for comprehensive hardware detection
- Store hosts in JSON with optional **jsonschema 4.26.0** validation
- Follow Typer's hybrid pattern: flags for common cases, prompts for missing values

**Critical insight:** Ansible facts do NOT include GPU information natively. GPU detection requires custom command execution via `lspci` or similar tools, not the standard fact gathering flow.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Host Storage Format:**
- **D-01:** JSON format for hosts file (native Python support, no dependencies)
- **D-02:** Single `hosts.json` file in `~/.config/clawrium/` (not directory-per-host)
- **D-03:** Hostname/IP as primary identifier, with optional friendly alias
- **D-04:** Schema includes: hostname, port, user, auth_method, alias, hardware capabilities, metadata (added_at, last_seen, tags)
- **D-05:** Simple string tags supported for host organization
- **D-06:** Hardware detected on add, refreshed only via explicit `clm host status --refresh`

**SSH Connection Flow:**
- **D-07:** Hybrid input: flags for common cases, prompts fill missing values
- **D-08:** SSH key only authentication (no password support) via SSH agent or explicit key path
- **D-09:** Honor ~/.ssh/config — auto-detect matching entries, allow explicit --ssh-config flag
- **D-10:** Test connection on add — reject and don't save if connection fails
- **D-11:** Default port 22, default user `xclm` (system admin user for installations)
- **D-12:** Two-user model: `xclm` for system ops (stored now), claw users (`<prefix>-<hostname>`) for claw ops (Phase 5)

**Hardware Detection:**
- **D-13:** Full capability set: architecture, CPU cores, memory, disk space, GPU (presence + vendor)
- **D-14:** Use Ansible facts via ansible-runner for hardware detection
- **D-15:** Hardware stored for compatibility checking (Phase 3), not displayed to users by default

**CLI Command Design:**
- **D-16:** Subcommand structure: `clm host add`, `clm host list`, `clm host remove`, `clm host status`
- **D-17:** Rich table output for `clm host list` (consistent with Phase 1 dependency display)
- **D-18:** Interactive confirmation for `clm host remove`
- **D-19:** `clm host status` shows: connection status, hostname verified, last seen, service health (prep for claw status in Phase 5)

### Claude's Discretion
- Exact schema field names and types
- Error message wording
- Table column layout and formatting
- Ansible playbook structure for hardware detection

### Deferred Ideas (OUT OF SCOPE)
- Claw user management — handled in Phase 5 with claw installation
- Password-based SSH authentication — security concern, key-only for v1
- GPU driver version detection — presence + vendor sufficient for compatibility
- Display hardware to users — not needed for v1, compatibility checking is internal

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HOST-01 | User can add a host with SSH details (`clm host add`) | Paramiko SSHClient for connection testing, SSH config parsing; Typer prompt patterns for hybrid input |
| HOST-02 | User can list all hosts with hardware info (`clm host list`) | Rich Table formatting patterns from Phase 1; JSON file reading |
| HOST-03 | User can remove a host (`clm host remove`) | Typer confirmation prompts; JSON file updates |
| HOST-04 | User can check host status (`clm host status`) | Paramiko connection test; ansible-runner fact gathering for refresh |
| HOST-05 | System detects hardware capabilities (arch, GPU, memory, disk) | ansible-runner with setup module for standard facts; custom lspci command for GPU detection |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ansible-runner | 2.4.3 | Hardware fact gathering, remote execution | Already in dependencies; standard Ansible integration for Python apps |
| paramiko | 4.0.0 | SSH connection testing, SSH config parsing | De facto Python SSH library; mature API; native OpenSSH config support |
| rich | 14.0.0+ | Table formatting for CLI output | Already in dependencies; used in Phase 1 |
| typer | 0.24.0+ | CLI framework with prompt support | Already in dependencies; project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| jsonschema | 4.26.0 | Host configuration schema validation | Optional: validate host.json on load for robustness |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| paramiko | fabric | Fabric adds higher-level abstractions but heavier dependency; paramiko sufficient for connection tests |
| JSON | YAML/TOML | JSON has zero dependencies, native Python support; YAML/TOML require external libs |
| ansible-runner | subprocess + ansible CLI | ansible-runner provides structured API and fact caching; CLI parsing fragile |

**Installation:**

All core libraries already in project dependencies (pyproject.toml). Optional schema validation:
```bash
uv add jsonschema  # if schema validation needed
```

**Version verification:**
- ansible-runner: 2.4.3 (latest, released 2024)
- paramiko: 4.0.0 (latest, released January 2025)
- rich: 14.1.0 (latest stable)
- typer: 0.12.1 (latest stable as of 2026)
- jsonschema: 4.26.0 (latest, released January 2026)

## Architecture Patterns

### Recommended Project Structure
```
src/clawrium/
├── core/
│   ├── config.py         # Existing: config dir management
│   ├── hosts.py          # NEW: Host storage (load, save, add, remove)
│   ├── hardware.py       # NEW: ansible-runner fact gathering
│   └── ssh_connection.py # NEW: Paramiko connection testing
├── cli/
│   ├── main.py           # Existing: register host subcommand
│   └── host.py           # NEW: host add/list/remove/status commands
```

### Pattern 1: Hybrid Flag + Prompt Input (Typer)
**What:** Accept values via flags for automation, prompt interactively when missing
**When to use:** CLI commands that need both scriptability and user-friendliness
**Example:**
```python
# Source: https://typer.tiangolo.com/tutorial/options/prompt/
import typer
from typing import Optional

def add(
    hostname: str = typer.Argument(..., help="Host IP or hostname"),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="SSH port"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="SSH user"),
):
    # Prompt for missing values
    if port is None:
        port = typer.prompt("SSH port", default=22, type=int)
    if user is None:
        user = typer.prompt("SSH user", default="xclm")
```

### Pattern 2: SSH Config Parsing with Paramiko
**What:** Read ~/.ssh/config and apply host-specific settings
**When to use:** Before connecting, to respect user's existing SSH configuration
**Example:**
```python
# Source: https://docs.paramiko.org/en/stable/api/config.html
import paramiko
import os
from pathlib import Path

def get_ssh_config(hostname: str) -> dict:
    """Parse SSH config and return settings for hostname."""
    ssh_config = paramiko.SSHConfig()
    config_file = Path.home() / ".ssh" / "config"

    if config_file.exists():
        with open(config_file) as f:
            ssh_config.parse(f)
        return ssh_config.lookup(hostname)
    return {}

# Use parsed config
config = get_ssh_config("myhost")
user = config.get('user', 'xclm')
port = config.as_int('port') if 'port' in config else 22
```

### Pattern 3: SSH Connection Testing
**What:** Validate SSH connection before saving host configuration
**When to use:** On `clm host add` to fail fast with clear error messages
**Example:**
```python
# Source: https://docs.paramiko.org/en/stable/api/client.html
import paramiko
import socket

def test_ssh_connection(hostname: str, port: int, user: str, key_filename: str = None) -> tuple[bool, str]:
    """Test SSH connection and return (success, message)."""
    client = paramiko.SSHClient()
    client.load_system_host_keys()

    try:
        client.connect(
            hostname=hostname,
            port=port,
            username=user,
            key_filename=key_filename,
            timeout=10
        )
        # Test command execution
        stdin, stdout, stderr = client.exec_command('echo "Connection OK"')
        result = stdout.read().decode().strip()
        client.close()
        return (True, result)
    except paramiko.BadHostKeyException:
        return (False, "Host key verification failed")
    except paramiko.AuthenticationException:
        return (False, "Authentication failed - check SSH keys")
    except socket.error as e:
        return (False, f"Network error: {e}")
    except paramiko.SSHException as e:
        return (False, f"SSH error: {e}")
    finally:
        client.close()
```

### Pattern 4: Ansible Fact Gathering
**What:** Use ansible-runner to collect hardware facts from remote host
**When to use:** After successful SSH connection, to populate hardware capabilities
**Example:**
```python
# Source: https://docs.ansible.com/projects/runner/en/1.4.7/python_interface.html
import ansible_runner
from pathlib import Path
import tempfile
import json

def gather_hardware_facts(hostname: str, user: str, ssh_key: str = None) -> dict:
    """Gather hardware facts using ansible-runner."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create inventory
        inventory = {
            'all': {
                'hosts': {
                    hostname: {
                        'ansible_user': user,
                        'ansible_port': 22,
                    }
                }
            }
        }

        if ssh_key:
            inventory['all']['hosts'][hostname]['ansible_ssh_private_key_file'] = ssh_key

        inv_path = Path(tmpdir) / 'inventory'
        inv_path.mkdir()
        (inv_path / 'hosts.json').write_text(json.dumps(inventory))

        # Run setup module to gather facts
        r = ansible_runner.run(
            private_data_dir=tmpdir,
            host_pattern=hostname,
            module='setup'
        )

        if r.status == 'successful':
            return r.get_fact_cache(hostname)
        else:
            raise RuntimeError(f"Fact gathering failed: {r.status}")
```

### Pattern 5: Rich Table Output
**What:** Display host list in formatted table (consistent with Phase 1 pattern)
**When to use:** `clm host list` command
**Example:**
```python
# Source: Existing pattern from src/clawrium/cli/init.py
from rich.console import Console
from rich.table import Table

def display_hosts(hosts: list[dict]):
    """Display hosts in a Rich table."""
    console = Console()
    table = Table(title="Registered Hosts")

    table.add_column("Alias", style="cyan")
    table.add_column("Host", style="white")
    table.add_column("Architecture", style="yellow")
    table.add_column("CPU Cores", justify="right")
    table.add_column("Memory (GB)", justify="right")
    table.add_column("Tags", style="dim")

    for host in hosts:
        hw = host.get('hardware', {})
        table.add_row(
            host.get('alias', '-'),
            host['hostname'],
            hw.get('architecture', '?'),
            str(hw.get('processor_cores', '?')),
            str(round(hw.get('memtotal_mb', 0) / 1024, 1)),
            ', '.join(host.get('tags', []))
        )

    console.print(table)
```

### Pattern 6: Host Storage (JSON)
**What:** Load and save hosts from ~/.config/clawrium/hosts.json
**When to use:** All host operations (add/remove/list)
**Example:**
```python
import json
from pathlib import Path
from typing import List, Dict
from clawrium.core.config import get_config_dir

HOSTS_FILE = "hosts.json"

def load_hosts() -> List[Dict]:
    """Load hosts from JSON file."""
    hosts_path = get_config_dir() / HOSTS_FILE
    if not hosts_path.exists():
        return []

    with open(hosts_path) as f:
        return json.load(f)

def save_hosts(hosts: List[Dict]) -> None:
    """Save hosts to JSON file."""
    hosts_path = get_config_dir() / HOSTS_FILE
    with open(hosts_path, 'w') as f:
        json.dump(hosts, f, indent=2)

def add_host(host: Dict) -> None:
    """Add a host to the registry."""
    hosts = load_hosts()
    hosts.append(host)
    save_hosts(hosts)

def remove_host(hostname: str) -> bool:
    """Remove a host by hostname. Returns True if found and removed."""
    hosts = load_hosts()
    filtered = [h for h in hosts if h['hostname'] != hostname]
    if len(filtered) == len(hosts):
        return False
    save_hosts(filtered)
    return True
```

### Anti-Patterns to Avoid

- **Don't store passwords in JSON** - SSH key-only authentication means no password storage needed; storing passwords would create security risk
- **Don't prompt without --no-input flag** - Always check if stdin is a TTY before prompting; provide --no-input flag for scripting
- **Don't silently continue on connection failure** - Connection test MUST succeed before saving host; fail fast with clear error
- **Don't rely on Ansible facts for GPU** - Standard Ansible facts don't include GPU info; must use custom commands

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSH connection management | Custom socket + authentication | Paramiko SSHClient | Host key verification, agent forwarding, known_hosts handling, config parsing all built-in |
| Hardware detection | Custom shell commands + parsing | ansible-runner with setup module | Handles cross-platform differences, caches facts, structured output |
| SSH config parsing | Regex on ~/.ssh/config | Paramiko SSHConfig | OpenSSH config format is complex (Include directives, Match blocks, token expansion) |
| CLI prompts | input() calls | Typer prompt options | Type validation, default values, confirmation, TTY detection built-in |
| Table formatting | String formatting | Rich Table | Unicode box drawing, column alignment, overflow handling, styling |

**Key insight:** SSH and Ansible both have edge cases that took years to solve (multiplexing, agent forwarding, privilege escalation, cross-platform paths). Reinventing these leads to subtle bugs that only appear in production.

## Common Pitfalls

### Pitfall 1: Ignoring SSH Config File
**What goes wrong:** Connection fails even though `ssh user@host` works manually
**Why it happens:** User has custom settings in ~/.ssh/config (port, user, ProxyJump, etc.) that CLI doesn't honor
**How to avoid:** Always parse ~/.ssh/config with Paramiko SSHConfig before connecting; merge CLI flags with config file values (CLI flags take precedence)
**Warning signs:** Works with ssh command, fails with Python; reports show "wrong user" or "wrong port"

### Pitfall 2: Assuming GPU Detection in Ansible Facts
**What goes wrong:** Hardware detection completes but GPU field is empty/missing
**Why it happens:** Ansible's setup module does NOT collect GPU information by default; it's not in the standard fact set
**How to avoid:** After fact gathering, run separate command (`lspci | grep -i vga`) to detect GPU presence and vendor
**Warning signs:** All other hardware fields populated (CPU, memory, disk) but GPU missing

### Pitfall 3: Not Testing Connection Before Saving
**What goes wrong:** Host saved to hosts.json but can't actually connect; subsequent operations fail
**Why it happens:** Skipping connection test to "speed up" the add process
**How to avoid:** ALWAYS test connection on add; only save if test succeeds; show clear error if test fails
**Warning signs:** `clm host add` succeeds quickly, `clm host status` fails; users confused why saved host doesn't work

### Pitfall 4: Prompting in Non-Interactive Contexts
**What goes wrong:** CLI hangs in scripts/CI because it's waiting for interactive input
**Why it happens:** Typer prompts work in TTY but block when stdin is not a terminal
**How to avoid:** Check if stdin is TTY before prompting; require --no-input flag for scripts; fail with clear error if required value missing in non-interactive mode
**Warning signs:** Works locally, hangs in CI; works in terminal, fails in cron

### Pitfall 5: Hardcoding SSH Key Paths
**What goes wrong:** Connection fails because SSH key not found at expected path
**Why it happens:** Assuming ~/.ssh/id_rsa when user has id_ed25519, or key stored elsewhere
**How to avoid:** Try SSH agent first (paramiko auto-detects), then check ~/.ssh/config, then prompt for key path; don't assume default key name
**Warning signs:** "Authentication failed" error even with valid key; works with `ssh` command but not CLI

### Pitfall 6: Not Handling SSH Host Key Changes
**What goes wrong:** Connection fails with BadHostKeyException after host reinstall
**Why it happens:** Host key changed but old key still in ~/.ssh/known_hosts
**How to avoid:** Catch BadHostKeyException and provide clear error message with instructions to update known_hosts; don't auto-accept unknown keys (security risk)
**Warning signs:** Worked before, fails after host reinstall; error message unclear

### Pitfall 7: Storing Large Fact Output
**What goes wrong:** hosts.json becomes huge, slow to load
**Why it happens:** Storing ALL Ansible facts (thousands of fields) instead of just needed hardware capabilities
**How to avoid:** Extract only required fields from fact cache (architecture, processor_cores, memtotal_mb, ansible_devices, ansible_mounts); don't store entire fact dictionary
**Warning signs:** hosts.json > 100KB for a few hosts; slow `clm host list` performance

## Code Examples

Verified patterns from official sources.

### SSH Connection Test with Config Parsing
```python
# Source: https://docs.paramiko.org/en/stable/api/client.html
# Source: https://docs.paramiko.org/en/stable/api/config.html
import paramiko
import socket
from pathlib import Path

def test_connection_with_config(hostname: str, port: int = None, user: str = None, key_file: str = None):
    """Test SSH connection, honoring ~/.ssh/config."""
    # Parse SSH config
    ssh_config = paramiko.SSHConfig()
    config_file = Path.home() / ".ssh" / "config"

    host_config = {}
    if config_file.exists():
        with open(config_file) as f:
            ssh_config.parse(f)
        host_config = ssh_config.lookup(hostname)

    # Merge: CLI flags override config file
    final_hostname = host_config.get('hostname', hostname)
    final_port = port or host_config.as_int('port') if 'port' in host_config else 22
    final_user = user or host_config.get('user', 'xclm')
    final_key = key_file or host_config.get('identityfile', [None])[0]

    client = paramiko.SSHClient()
    client.load_system_host_keys()

    try:
        client.connect(
            hostname=final_hostname,
            port=final_port,
            username=final_user,
            key_filename=final_key,
            timeout=10
        )
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)
    finally:
        client.close()
```

### Hardware Detection with GPU
```python
# Source: https://docs.ansible.com/projects/runner/en/1.4.7/python_interface.html
# Source: https://github.com/ansible/ansible/issues/72220 (GPU not in standard facts)
import ansible_runner
import tempfile
import json
from pathlib import Path

def detect_hardware(hostname: str, user: str, ssh_key: str = None) -> dict:
    """Detect hardware capabilities including GPU."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create inventory
        inventory = {
            'all': {
                'hosts': {
                    hostname: {
                        'ansible_user': user,
                        'ansible_port': 22,
                    }
                }
            }
        }

        if ssh_key:
            inventory['all']['hosts'][hostname]['ansible_ssh_private_key_file'] = ssh_key

        inv_path = Path(tmpdir) / 'inventory'
        inv_path.mkdir()
        (inv_path / 'hosts.json').write_text(json.dumps(inventory))

        # Gather standard facts
        r = ansible_runner.run(
            private_data_dir=tmpdir,
            host_pattern=hostname,
            module='setup'
        )

        if r.status != 'successful':
            raise RuntimeError(f"Fact gathering failed: {r.status}")

        facts = r.get_fact_cache(hostname)

        # Extract relevant hardware
        hardware = {
            'architecture': facts['ansible_architecture'],
            'processor_cores': facts['ansible_processor_cores'],
            'processor_count': facts['ansible_processor_count'],
            'memtotal_mb': facts['ansible_memtotal_mb'],
            'mounts': [
                {
                    'mount': m['mount'],
                    'size_total': m['size_total'],
                    'size_available': m['size_available'],
                }
                for m in facts['ansible_mounts']
            ]
        }

        # GPU detection: run lspci command
        gpu_result = ansible_runner.run(
            private_data_dir=tmpdir,
            host_pattern=hostname,
            module='command',
            module_args='lspci | grep -i vga'
        )

        if gpu_result.status == 'successful':
            for event in gpu_result.events:
                if event.get('event') == 'runner_on_ok':
                    stdout = event.get('event_data', {}).get('res', {}).get('stdout', '')
                    if stdout:
                        # Parse GPU vendor from lspci output
                        gpu_vendor = None
                        if 'nvidia' in stdout.lower():
                            gpu_vendor = 'nvidia'
                        elif 'amd' in stdout.lower() or 'ati' in stdout.lower():
                            gpu_vendor = 'amd'
                        elif 'intel' in stdout.lower():
                            gpu_vendor = 'intel'

                        hardware['gpu'] = {
                            'present': True,
                            'vendor': gpu_vendor,
                            'raw_info': stdout
                        }
                        break

        if 'gpu' not in hardware:
            hardware['gpu'] = {'present': False}

        return hardware
```

### Typer Interactive Confirmation
```python
# Source: https://typer.tiangolo.com/tutorial/prompt/
import typer

def remove(hostname: str, force: bool = typer.Option(False, "--force", "-f")):
    """Remove a host with confirmation."""
    if not force:
        confirmed = typer.confirm(f"Remove host '{hostname}'? This cannot be undone.")
        if not confirmed:
            raise typer.Abort()

    # Proceed with removal
    success = remove_host(hostname)
    if success:
        typer.echo(f"Host '{hostname}' removed successfully")
    else:
        typer.echo(f"Host '{hostname}' not found", err=True)
        raise typer.Exit(code=1)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| subprocess + ssh commands | Paramiko SSHClient | ~2015 | Structured error handling, programmatic control |
| subprocess + ansible CLI | ansible-runner Python API | 2018 (ansible-runner 1.0) | Structured fact access, no CLI parsing |
| Manual JSON parsing | jsonschema validation | Ongoing | Catch schema errors early, better error messages |
| Text-based output | Rich tables | 2020s (Rich adoption) | Better UX, clearer presentation |

**Deprecated/outdated:**
- **fabric2** for simple SSH tasks: Paramiko is sufficient for connection testing; Fabric adds overhead
- **ansible-playbook CLI + parsing**: ansible-runner provides native Python API
- **Hardcoded ~/.ssh/id_rsa**: Modern SSH uses ed25519 keys, various key names

## Open Questions

1. **GPU driver version detection**
   - What we know: lspci shows GPU presence and vendor
   - What's unclear: Whether driver version needed for Phase 3 compatibility checks
   - Recommendation: Start with presence + vendor only (per D-15); add driver version later if Phase 3 requires it

2. **SSH agent vs. explicit key file**
   - What we know: Paramiko can use SSH agent automatically if running
   - What's unclear: Best UX for users without agent (prompt for key path vs. error message?)
   - Recommendation: Try agent first, fall back to prompting for key path if agent not available

3. **Host key auto-acceptance**
   - What we know: Auto-accepting unknown host keys is security risk
   - What's unclear: Whether to provide --accept-new-host-key flag for convenience
   - Recommendation: Require manual known_hosts management for v1; consider --accept-new-host-key flag for v2 with strong warning

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0.0+ |
| Config file | pyproject.toml (existing) |
| Quick run command | `pytest tests/test_hosts.py -x` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HOST-01 | Add host with SSH test | integration | `pytest tests/test_host_add.py::test_add_with_valid_connection -x` | ❌ Wave 0 |
| HOST-01 | Parse SSH config | unit | `pytest tests/test_ssh_connection.py::test_ssh_config_parsing -x` | ❌ Wave 0 |
| HOST-02 | List hosts in table | unit | `pytest tests/test_cli_host.py::test_list_displays_table -x` | ❌ Wave 0 |
| HOST-03 | Remove host with confirmation | integration | `pytest tests/test_cli_host.py::test_remove_with_confirmation -x` | ❌ Wave 0 |
| HOST-04 | Check connection status | integration | `pytest tests/test_host_status.py::test_status_connection_check -x` | ❌ Wave 0 |
| HOST-05 | Detect architecture, CPU, memory | unit | `pytest tests/test_hardware.py::test_parse_ansible_facts -x` | ❌ Wave 0 |
| HOST-05 | Detect GPU via lspci | unit | `pytest tests/test_hardware.py::test_gpu_detection -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_hosts.py tests/test_hardware.py tests/test_ssh_connection.py -x` (< 30 sec)
- **Per wave merge:** `pytest tests/ -v` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_hosts.py` — covers HOST-02, HOST-03 (host storage operations)
- [ ] `tests/test_hardware.py` — covers HOST-05 (fact parsing, GPU detection)
- [ ] `tests/test_ssh_connection.py` — covers HOST-01 (SSH config parsing, connection test)
- [ ] `tests/test_cli_host.py` — covers HOST-01, HOST-02, HOST-03 (CLI commands)
- [ ] `tests/test_host_status.py` — covers HOST-04 (status checking)
- [ ] `tests/conftest.py` — add SSH mocking fixtures (existing file, extend)

## Sources

### Primary (HIGH confidence)
- [Ansible setup module docs](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/setup_module.html) - Hardware fact categories
- [ansible-runner Python interface docs](https://docs.ansible.com/projects/runner/en/1.4.7/python_interface.html) - Fact gathering API
- [Paramiko SSHClient API](https://docs.paramiko.org/en/stable/api/client.html) - Connection testing
- [Paramiko SSHConfig API](https://docs.paramiko.org/en/stable/api/config.html) - SSH config parsing
- [Typer prompt tutorial](https://typer.tiangolo.com/tutorial/prompt/) - Interactive prompts
- [Rich Table docs](https://rich.readthedocs.io/en/stable/introduction.html) - Table formatting

### Secondary (MEDIUM confidence)
- [How to Use Ansible Runner in Python Applications](https://oneuptime.com/blog/post/2026-02-21-ansible-runner-python-applications/view) - ansible-runner patterns
- [How to Use Ansible Facts](https://oneuptime.com/blog/post/2026-01-21-ansible-facts/view) - Fact variable names
- [Building CLI Tools with Typer and Rich](https://dasroot.net/posts/2026/01/building-cli-tools-with-typer-and-rich/) - Typer + Rich integration
- [Command Line Interface Guidelines](https://clig.dev/) - CLI best practices
- [How to Fix Ansible Failed to Connect to Host via SSH Errors](https://oneuptime.com/blog/post/2026-02-21-fix-ansible-ssh-connection-errors/view) - Common SSH pitfalls

### Tertiary (LOW confidence - verified with official docs)
- [Ansible GPU detection issue #72220](https://github.com/ansible/ansible/issues/72220) - Confirms GPU not in standard facts
- [Ansible disk facts guide](https://github.com/oneuptime/blog/tree/master/posts/2026-02-21-how-to-use-ansible-facts-to-get-disk-information) - ansible_mounts and ansible_devices usage

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified with PyPI, versions confirmed current
- Architecture patterns: HIGH - All patterns sourced from official docs or existing codebase
- Pitfalls: MEDIUM-HIGH - SSH/Ansible pitfalls verified via official docs and recent 2026 troubleshooting guides; GPU limitation confirmed via GitHub issue

**Research date:** 2026-03-20
**Valid until:** ~2026-04-30 (30 days; stable domain, libraries mature)

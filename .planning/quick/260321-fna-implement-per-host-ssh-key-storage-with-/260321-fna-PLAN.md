---
type: quick
plan_id: 260321-fna
description: Implement per-host SSH key storage with clm host init command
files_modified:
  - src/clawrium/core/keys.py
  - src/clawrium/cli/host.py
  - src/clawrium/core/hosts.py
  - tests/test_keys.py
  - tests/test_cli_host.py
  - docs/host-preparation.md
  - docs/index.md
autonomous: true
---

<objective>
Implement per-host SSH key storage and the `clm host init` command.

**Purpose:** Enable Clawrium to generate and manage SSH keypairs per-host, stored in `~/.config/clawrium/keys/<hostname>/`. The new `clm host init` command automates xclm user setup on hosts.

**Output:**
- New `clm host init <hostname>` command
- Per-host keypair storage in `keys/<hostname>/xclm_ed25519`
- Updated `clm host add` to use per-host keys
- Updated `clm host remove` to clean up per-host keys
- Updated documentation
</objective>

<context>
@/home/devashish/workspace/ric03uec/clawrium/src/clawrium/core/config.py
@/home/devashish/workspace/ric03uec/clawrium/src/clawrium/core/hosts.py
@/home/devashish/workspace/ric03uec/clawrium/src/clawrium/core/ssh_connection.py
@/home/devashish/workspace/ric03uec/clawrium/src/clawrium/cli/host.py
@/home/devashish/workspace/ric03uec/clawrium/tests/conftest.py

<interfaces>
<!-- Key types and contracts from existing codebase -->

From src/clawrium/core/config.py:
```python
def get_config_dir() -> Path:
    """Get the Clawrium configuration directory path."""

def init_config_dir() -> Path:
    """Create and return the configuration directory."""
```

From src/clawrium/core/hosts.py:
```python
def load_hosts() -> list[dict]: ...
def save_hosts(hosts: list[dict]) -> None: ...
def add_host(host: dict) -> None: ...
def remove_host(hostname: str) -> bool: ...
def get_host(identifier: str) -> dict | None: ...
```

From src/clawrium/core/ssh_connection.py:
```python
def get_ssh_config(hostname: str) -> dict: ...
def test_ssh_connection(hostname, port, user, key_filename) -> tuple[bool, str]: ...
class HostKeyVerificationRequired(Exception): ...
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create keys module with per-host key storage</name>
  <files>src/clawrium/core/keys.py, tests/test_keys.py</files>
  <behavior>
    - get_host_key_dir(hostname) returns Path to keys/<hostname>/
    - get_host_private_key(hostname) returns Path to xclm_ed25519 or None if missing
    - generate_host_keypair(hostname) creates ed25519 keypair with 0600 permissions
    - delete_host_keys(hostname) removes entire keys/<hostname>/ directory
    - Keypair naming: xclm_ed25519 and xclm_ed25519.pub
  </behavior>
  <action>
Create `src/clawrium/core/keys.py` with:

1. `get_host_key_dir(hostname: str) -> Path`:
   - Return `get_config_dir() / "keys" / hostname`

2. `get_host_private_key(hostname: str) -> Path | None`:
   - Return path to `xclm_ed25519` if exists, None otherwise

3. `get_host_public_key(hostname: str) -> Path | None`:
   - Return path to `xclm_ed25519.pub` if exists, None otherwise

4. `generate_host_keypair(hostname: str) -> tuple[Path, Path]`:
   - Create `keys/<hostname>/` directory with 0700
   - Generate ed25519 keypair using `cryptography` library (already available via paramiko)
   - Write private key with 0600 permissions
   - Write public key
   - Return (private_key_path, public_key_path)

5. `delete_host_keys(hostname: str) -> bool`:
   - Remove entire `keys/<hostname>/` directory
   - Return True if deleted, False if didn't exist

6. `read_public_key(hostname: str) -> str | None`:
   - Read and return public key content, or None if missing

Create `tests/test_keys.py` with tests for each function using `isolated_config` fixture.
  </action>
  <verify>
    <automated>make test -- -k test_keys -x</automated>
  </verify>
  <done>Keys module exists with all functions, tests pass</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement clm host init command</name>
  <files>src/clawrium/cli/host.py, tests/test_cli_host.py</files>
  <behavior>
    - `clm host init <hostname>` generates keypair for host
    - `--user` flag specifies SSH user for initial connection (default: current user)
    - On successful initial connection: create xclm user, configure sudo, copy pubkey, verify
    - On failed initial connection: output manual commands, display public key
    - Shows public key to user on success for verification
  </behavior>
  <action>
Add `init` command to `src/clawrium/cli/host.py`:

```python
@host_app.command()
def init(
    hostname: str = typer.Argument(..., help="Host IP or hostname to initialize"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="SSH user for initial connection (default: current user)"),
) -> None:
```

Implementation flow:

1. **Generate keypair** (if not exists):
   - Call `generate_host_keypair(hostname)` from keys module
   - Display public key path

2. **Try initial connection** using provided user (or current user):
   - Use `test_ssh_connection()` with user's existing credentials
   - Handle `HostKeyVerificationRequired` same as `host add`

3. **If connection succeeds** (automated setup):
   - Use ansible-runner or paramiko to execute:
     ```bash
     sudo useradd -m -s /bin/bash xclm 2>/dev/null || true
     echo "xclm ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/xclm
     sudo chmod 440 /etc/sudoers.d/xclm
     sudo mkdir -p /home/xclm/.ssh
     sudo chmod 700 /home/xclm/.ssh
     echo "<pubkey>" | sudo tee /home/xclm/.ssh/authorized_keys
     sudo chmod 600 /home/xclm/.ssh/authorized_keys
     sudo chown -R xclm:xclm /home/xclm/.ssh
     ```
   - Verify xclm connection works with new keypair
   - Output success message with next step: `clm host add <hostname>`

4. **If connection fails** (manual setup):
   - Output the commands user needs to run manually on the host
   - Display the public key content for user to copy
   - Instruct user to run `clm host init <hostname>` again to verify

Add tests to `tests/test_cli_host.py`:
- `test_host_init_generates_keypair`
- `test_host_init_auto_setup_success`
- `test_host_init_manual_fallback`
  </action>
  <verify>
    <automated>make test -- -k "test_host_init" -x</automated>
  </verify>
  <done>clm host init command works for both auto and manual setup paths</done>
</task>

<task type="auto">
  <name>Task 3: Update host add/remove and docs for per-host keys</name>
  <files>src/clawrium/cli/host.py, src/clawrium/core/hosts.py, docs/host-preparation.md, docs/index.md</files>
  <action>
**Update `clm host add` in src/clawrium/cli/host.py:**

1. Before testing connection, get per-host key:
   ```python
   from clawrium.core.keys import get_host_private_key
   host_key = get_host_private_key(hostname)
   if not host_key:
       console.print(f"[red]Error:[/red] No keypair found for '{hostname}'")
       console.print("Run 'clm host init {hostname}' first to generate keys")
       raise typer.Exit(code=1)
   ```

2. Use `host_key` for connection test instead of SSH config lookup:
   - Remove `final_key` from SSH config merge
   - Use `key_filename=str(host_key)` in `test_ssh_connection()`

3. Update status command similarly to use per-host key

**Update `clm host remove` in src/clawrium/cli/host.py:**

1. After successful removal from hosts.json, delete per-host keys:
   ```python
   from clawrium.core.keys import delete_host_keys
   delete_host_keys(host['hostname'])
   ```

**Update docs/host-preparation.md:**

Rewrite to reflect new workflow:
- P0: `clm host init <hostname>` (attempts auto-setup, falls back to manual)
- P1: Manual setup commands (only if P0 auto-setup failed)
- P2: `clm host add <hostname>` (after xclm user is configured)

Remove references to `clm keys show` (no longer needed - per-host keys).

**Update docs/index.md:**

Update User Data table:
```markdown
| `keys/<hostname>/xclm_ed25519` | Private key for SSH to <hostname>. 0600 permissions. |
| `keys/<hostname>/xclm_ed25519.pub` | Public key added to host's authorized_keys. |
```

Remove the single keypair entries.

Add note about `clm host init` in Quick Reference.
  </action>
  <verify>
    <automated>make test -- -k "test_host" -x && cat docs/host-preparation.md | grep -q "clm host init"</automated>
  </verify>
  <done>host add requires per-host key, host remove cleans up keys, docs updated</done>
</task>

</tasks>

<verification>
```bash
# All tests pass
make test

# Lint passes
make lint

# Manual verification flow
clm host init 192.168.1.100 --user myuser  # Should generate keys, try auto-setup
clm host add 192.168.1.100                  # Should use per-host key
clm host remove 192.168.1.100 --force       # Should delete keys/<hostname>/
ls ~/.config/clawrium/keys/                 # Should be empty
```
</verification>

<success_criteria>
1. `clm host init <hostname>` generates per-host keypair in `keys/<hostname>/`
2. Auto-setup creates xclm user and configures SSH when initial connection succeeds
3. Manual fallback displays commands and public key when initial connection fails
4. `clm host add` requires keypair to exist (enforces init-first workflow)
5. `clm host remove` deletes the per-host key directory
6. Documentation reflects new workflow (P0 init, P1 manual if needed, P2 add)
7. All existing tests pass, new tests cover key module and init command
</success_criteria>

<output>
After completion, create `.planning/quick/260321-fna-implement-per-host-ssh-key-storage-with-/260321-fna-SUMMARY.md`
</output>

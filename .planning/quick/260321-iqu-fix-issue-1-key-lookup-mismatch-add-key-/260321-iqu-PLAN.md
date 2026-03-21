---
id: 260321-iqu
type: quick
description: "Fix issue #1: Key lookup mismatch. Add key_id field to host records"
files_modified:
  - src/clawrium/core/names.py
  - src/clawrium/cli/host.py
  - src/clawrium/core/hosts.py
  - tests/test_names.py
  - tests/test_cli_host.py
autonomous: true
---

<objective>
Fix the key lookup mismatch bug (issue #1) where keys are stored under the CLI argument (alias/hostname) but looked up by resolved IP address.

**Root cause:** `clm host init kevin` stores keys at `~/.config/clawrium/keys/kevin/`, but `clm host status kevin` resolves to IP and looks up keys at `~/.config/clawrium/keys/192.168.1.x/`.

**Solution:** Add `key_id` field to host records that stores the original CLI argument used during init. All key operations use `key_id` instead of resolved hostname.

**Additional requirement:** When user provides only an IP (no alias), generate a Docker-style random name (adjective-scientist) for the `key_id`.
</objective>

<context>
@src/clawrium/cli/host.py (host commands - init, add, status, remove)
@src/clawrium/core/keys.py (key storage - uses hostname to find keys)
@src/clawrium/core/hosts.py (host storage - JSON records)
@tests/test_cli_host.py (existing CLI tests)
</context>

<interfaces>
<!-- Key functions that need modification -->

From src/clawrium/core/keys.py:
```python
def get_host_private_key(hostname: str) -> Path | None:
    """Get the path to a host's private key."""
    key_path = get_host_key_dir(hostname) / KEY_FILENAME
    return key_path if key_path.exists() else None

def delete_host_keys(hostname: str) -> bool:
    """Delete all SSH keys for a host."""
    # Uses hostname to find key directory
```

From src/clawrium/core/hosts.py:
```python
def add_host(host: dict) -> None:
    """Add a host to the registry."""
    # Host dict needs new key_id field
```

Current host record structure (from cli/host.py line 290-306):
```python
host = {
    "hostname": final_hostname,  # Resolved hostname
    "port": final_port,
    "user": final_user,
    "auth_method": "key",
    "hardware": hardware,
    "metadata": {...}
}
# Missing: key_id field
```
</interfaces>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create names.py with Docker-style random name generator</name>
  <files>src/clawrium/core/names.py, tests/test_names.py</files>
  <behavior>
    - generate_random_name() returns "adjective-scientist" format
    - Uses ~50 hardcoded scientist lastnames (einstein, curie, newton, etc.)
    - Uses ~30 adjectives (clever, swift, bright, etc.)
    - Names are lowercase, hyphen-separated
    - Random selection from both lists
    - is_ip_address(value) returns True for valid IPv4 addresses, False otherwise
  </behavior>
  <action>
    1. Create src/clawrium/core/names.py with:
       - ADJECTIVES list (~30 words): clever, swift, bright, calm, bold, eager, gentle, kind, quick, sharp, steady, vivid, warm, wise, agile, brave, clear, deft, fair, keen, lively, neat, prime, rapid, smart, sound, strong, true, able
       - SCIENTISTS list (50 names): einstein, curie, newton, darwin, tesla, lovelace, turing, hawking, feynman, bohr, planck, fermi, dirac, heisenberg, schrodinger, maxwell, faraday, galileo, kepler, copernicus, euclid, archimedes, pythagoras, aristotle, hypatia, noether, meitner, franklin, hopper, goodall, carson, sagan, tyson, lamarr, wu, rubin, leavitt, cannon, payne, burnell, ride, jemison, elion, yalow, mcclintock, blackwell, hodgkin, joliot, germain, chatelet
       - generate_random_name() -> str: returns f"{random.choice(ADJECTIVES)}-{random.choice(SCIENTISTS)}"
       - is_ip_address(value: str) -> bool: regex match for valid IPv4 (digits.digits.digits.digits pattern)
    2. Create tests/test_names.py with tests for:
       - generate_random_name returns "adjective-scientist" format
       - is_ip_address returns True for "192.168.1.1", "10.0.0.1", "255.255.255.255"
       - is_ip_address returns False for "hostname", "kevin", "my-server", "192.168.1" (incomplete)
  </action>
  <verify>
    <automated>make test -- tests/test_names.py -v</automated>
  </verify>
  <done>names.py module exists with working random name generator and IP detection, all tests pass</done>
</task>

<task type="auto">
  <name>Task 2: Add key_id to host records and fix key lookup</name>
  <files>src/clawrium/cli/host.py</files>
  <action>
    **Changes to `host add` command (line 178-309):**

    1. After line 192 (keypair check), capture the original hostname argument BEFORE resolution:
       ```python
       # Original argument becomes key_id (used for key lookup)
       original_hostname = hostname
       ```

    2. After line 221 (final_key assignment), determine key_id:
       ```python
       from clawrium.core.names import is_ip_address, generate_random_name

       # Determine key_id: use alias if provided, else original hostname
       # If original is an IP and no alias, generate a random name
       if alias:
           key_id = alias
       elif is_ip_address(original_hostname):
           key_id = generate_random_name()
       else:
           key_id = original_hostname
       ```

    3. In host record (line 290-306), add key_id field:
       ```python
       host = {
           "hostname": final_hostname,
           "key_id": key_id,  # <-- ADD THIS
           "port": final_port,
           ...
       }
       ```

    **Changes to `host status` command (line 396-510):**

    4. Replace line 421-422:
       ```python
       # OLD:
       actual_hostname = host['hostname']
       host_key = get_host_private_key(actual_hostname)

       # NEW:
       key_id = host.get('key_id') or host['hostname']  # Fallback for old records
       host_key = get_host_private_key(key_id)
       ```

    5. Update error message on line 424-425:
       ```python
       console.print(f"[red]Error:[/red] No keypair found for '{key_id}'")
       console.print(f"Run 'clm host init {key_id}' to regenerate keys")
       ```

    **Changes to `host remove` command (line 353-393):**

    6. Replace line 386-387:
       ```python
       # OLD:
       actual_hostname = host['hostname']
       keys_deleted = delete_host_keys(actual_hostname)

       # NEW:
       key_id = host.get('key_id') or host['hostname']  # Fallback for old records
       keys_deleted = delete_host_keys(key_id)
       ```

    7. Update message on line 390:
       ```python
       console.print(f"[dim]Keypair for '{key_id}' deleted.[/dim]")
       ```

    **Changes to `host init` command (line 38-175):**

    8. After successful setup (line 124), update the message to show the key_id used:
       No change needed - init uses the original hostname argument directly for keypair storage, which is correct.

    **Import at top of file:**

    9. Add import after line 25:
       ```python
       from clawrium.core.names import is_ip_address, generate_random_name
       ```
  </action>
  <verify>
    <automated>make test -- tests/test_cli_host.py -v</automated>
  </verify>
  <done>
    - host add stores key_id field in host record
    - host add generates random name when user provides IP without alias
    - host status uses key_id for key lookup
    - host remove uses key_id for key deletion
    - Existing tests still pass
  </done>
</task>

<task type="auto">
  <name>Task 3: Add tests for key_id behavior</name>
  <files>tests/test_cli_host.py</files>
  <action>
    Add new tests to tests/test_cli_host.py:

    1. Test key_id is stored when alias provided:
       ```python
       def test_host_add_stores_key_id_from_alias(isolated_config: Path, mock_ssh_client, mock_ansible_runner):
           """clm host add with alias stores key_id = alias."""
           create_test_keypair(isolated_config, "myserver")

           with patch('clawrium.core.ssh_connection.paramiko.SSHClient', return_value=mock_ssh_client):
               with patch('clawrium.core.hardware.ansible_runner.run', return_value=mock_ansible_runner):
                   result = runner.invoke(
                       app,
                       ["host", "add", "192.168.1.100", "--alias", "myserver"],
                       env=os.environ
                   )

                   assert result.exit_code == 0

                   # Verify key_id is stored
                   import json
                   hosts = json.loads((isolated_config / "hosts.json").read_text())
                   assert hosts[0].get("key_id") == "myserver"
       ```

    2. Test key_id auto-generated for IP-only input:
       ```python
       def test_host_add_generates_key_id_for_ip(isolated_config: Path, mock_ssh_client, mock_ansible_runner):
           """clm host add with IP only generates random key_id."""
           # First generate a random name to create keypair
           from clawrium.core.names import generate_random_name

           # We need to mock generate_random_name to get a predictable key_id
           with patch('clawrium.cli.host.generate_random_name', return_value='clever-einstein'):
               create_test_keypair(isolated_config, "clever-einstein")

               with patch('clawrium.core.ssh_connection.paramiko.SSHClient', return_value=mock_ssh_client):
                   with patch('clawrium.core.hardware.ansible_runner.run', return_value=mock_ansible_runner):
                       result = runner.invoke(
                           app,
                           ["host", "add", "192.168.1.100"],
                           env=os.environ
                       )

                       assert result.exit_code == 0

                       import json
                       hosts = json.loads((isolated_config / "hosts.json").read_text())
                       # key_id should be the generated name
                       assert hosts[0].get("key_id") == "clever-einstein"
       ```

    3. Test status uses key_id for lookup:
       ```python
       def test_host_status_uses_key_id(isolated_config: Path, mock_ssh_client):
           """clm host status looks up keys by key_id, not hostname."""
           # Create keypair under alias name, not IP
           create_test_keypair(isolated_config, "myserver")

           # Create host record with key_id
           import json
           host_data = {
               'hostname': '192.168.1.100',
               'key_id': 'myserver',
               'port': 22,
               'user': 'xclm',
               'auth_method': 'key',
               'hardware': {},
               'metadata': {'added_at': '2026-03-21', 'last_seen': '2026-03-21', 'tags': []}
           }
           hosts_file = isolated_config / "hosts.json"
           isolated_config.mkdir(parents=True, exist_ok=True)
           hosts_file.write_text(json.dumps([host_data]))

           with patch('clawrium.core.ssh_connection.paramiko.SSHClient', return_value=mock_ssh_client):
               result = runner.invoke(app, ["host", "status", "myserver"], env=os.environ)

               # Should succeed because key lookup uses key_id "myserver", not hostname "192.168.1.100"
               assert result.exit_code == 0
               assert "connected" in result.output.lower()
       ```
  </action>
  <verify>
    <automated>make test -- tests/test_cli_host.py -v -k "key_id"</automated>
  </verify>
  <done>All key_id-related tests pass, confirming the fix works end-to-end</done>
</task>

</tasks>

<verification>
```bash
# Run all tests
make test

# Verify the fix manually (integration test):
# 1. clm host init myserver (creates keys at ~/.config/clawrium/keys/myserver/)
# 2. clm host add 192.168.1.100 --alias myserver
# 3. clm host status myserver (should find keys, not error)
```
</verification>

<success_criteria>
- names.py module created with generate_random_name() and is_ip_address()
- host add command stores key_id field in host records
- host add generates Docker-style random name for IP-only inputs
- host status uses key_id (not hostname) for key lookup
- host remove uses key_id for key deletion
- All existing tests pass
- New tests for key_id behavior pass
- Issue #1 is resolved: `clm host init X && clm host add Y --alias X && clm host status X` works
</success_criteria>

<output>
After completion, create `.planning/quick/260321-iqu-fix-issue-1-key-lookup-mismatch-add-key-/260321-iqu-SUMMARY.md`
</output>

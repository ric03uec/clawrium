---
phase: quick
plan: 260321-jld
type: execute
wave: 1
depends_on: []
files_modified:
  - src/clawrium/core/hardware.py
  - tests/test_hardware.py
autonomous: true
requirements: []
issue: "https://github.com/ric03uec/clawrium/issues/3"

must_haves:
  truths:
    - "gather_hardware() successfully retrieves facts from remote host"
    - "GPU detection runs against the same host"
    - "No more 'No facts returned from host' error"
  artifacts:
    - path: "src/clawrium/core/hardware.py"
      provides: "Fixed ansible_runner.run calls with inventory parameter"
      contains: "inventory=inventory"
  key_links:
    - from: "src/clawrium/core/hardware.py"
      to: "ansible_runner.run"
      via: "inventory parameter"
      pattern: "ansible_runner\\.run\\([^)]*inventory=inventory"
---

<objective>
Fix hardware detection failure in `gather_hardware()` where ansible-runner's `host_pattern` cannot match hosts because the inventory is not passed to the runner.

Purpose: Resolve GitHub issue #3 - hardware detection fails silently with "No facts returned from host" because ansible-runner needs the inventory dict passed directly, not just written to a file.

Output: Working hardware detection that correctly gathers CPU, memory, disk, and GPU information from remote hosts.
</objective>

<context>
@.planning/STATE.md
@src/clawrium/core/hardware.py
@tests/test_hardware.py
</context>

<root_cause>
The `gather_hardware()` function creates an inventory dict and writes it to `{tmpdir}/inventory/hosts.json`, but does NOT pass `inventory=inventory` to `ansible_runner.run()`.

While ansible-runner can auto-discover inventory files in `{private_data_dir}/inventory/`, the `host_pattern` parameter requires the inventory to be explicitly passed for reliable host matching.

Current code (broken):
```python
ansible_runner.run(
    private_data_dir=tmpdir,
    host_pattern=hostname,  # Matches nothing without inventory param
    module="setup",
    ...
)
```

Fixed code:
```python
ansible_runner.run(
    private_data_dir=tmpdir,
    inventory=inventory,    # Pass inventory dict directly
    host_pattern=hostname,
    module="setup",
    ...
)
```
</root_cause>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add test for inventory parameter usage</name>
  <files>tests/test_hardware.py</files>
  <behavior>
    - Test confirms ansible_runner.run receives inventory parameter
    - Test verifies inventory dict structure matches expected format
  </behavior>
  <action>
Add a test that verifies `ansible_runner.run()` is called with the `inventory` parameter. Use `monkeypatch` to capture the kwargs passed to the function.

```python
def test_gather_hardware_passes_inventory_to_runner(monkeypatch):
    """Test that gather_hardware passes inventory dict to ansible_runner.run."""
    captured_calls = []

    class MockResult:
        status = "successful"
        events = []
        def get_fact_cache(self, hostname):
            return {"ansible_architecture": "x86_64", "ansible_processor_cores": 4,
                    "ansible_processor_count": 1, "ansible_memtotal_mb": 16384,
                    "ansible_mounts": []}

    def capture_run(*args, **kwargs):
        captured_calls.append(kwargs)
        return MockResult()

    import ansible_runner
    monkeypatch.setattr(ansible_runner, "run", capture_run)

    from clawrium.core.hardware import gather_hardware
    gather_hardware("192.168.1.100", user="testuser", port=2222, ssh_key="/path/to/key")

    # Should be called twice (setup module + lspci)
    assert len(captured_calls) == 2

    # Both calls should have inventory parameter
    for call in captured_calls:
        assert "inventory" in call, "inventory parameter must be passed to ansible_runner.run"
        inv = call["inventory"]
        assert "all" in inv
        assert "hosts" in inv["all"]
        assert "192.168.1.100" in inv["all"]["hosts"]
        host_vars = inv["all"]["hosts"]["192.168.1.100"]
        assert host_vars["ansible_user"] == "testuser"
        assert host_vars["ansible_port"] == 2222
        assert host_vars["ansible_ssh_private_key_file"] == "/path/to/key"
```
  </action>
  <verify>
    <automated>cd /home/devashish/workspace/ric03uec/clawrium && make test 2>&1 | grep -E "(PASSED|FAILED|ERROR|test_gather_hardware_passes_inventory)"</automated>
  </verify>
  <done>Test exists and FAILS (RED phase) because inventory parameter is not yet passed</done>
</task>

<task type="auto">
  <name>Task 2: Fix ansible_runner.run calls to pass inventory</name>
  <files>src/clawrium/core/hardware.py</files>
  <action>
Modify `gather_hardware()` in `src/clawrium/core/hardware.py`:

1. Add `inventory=inventory` parameter to the first `ansible_runner.run()` call (line ~112):
```python
result = ansible_runner.run(
    private_data_dir=tmpdir,
    inventory=inventory,    # ADD THIS LINE
    host_pattern=hostname,
    module="setup",
    quiet=True,
    timeout=30,
)
```

2. Add `inventory=inventory` parameter to the second `ansible_runner.run()` call for GPU detection (line ~133):
```python
gpu_result = ansible_runner.run(
    private_data_dir=tmpdir,
    inventory=inventory,    # ADD THIS LINE
    host_pattern=hostname,
    module="shell",
    module_args="lspci | grep -i vga || true",
    quiet=True,
    timeout=15,
)
```

Note: Keep the inventory file writing (lines 107-109) as it may be useful for debugging, but the key fix is passing the dict directly to `run()`.
  </action>
  <verify>
    <automated>cd /home/devashish/workspace/ric03uec/clawrium && make test</automated>
  </verify>
  <done>All tests pass including the new test_gather_hardware_passes_inventory_to_runner</done>
</task>

<task type="auto">
  <name>Task 3: Clean up unnecessary inventory file write</name>
  <files>src/clawrium/core/hardware.py</files>
  <action>
Since the inventory is now passed directly to `ansible_runner.run()`, the file-based inventory is no longer needed. Remove the redundant code:

Remove lines 107-109:
```python
inv_path = Path(tmpdir) / "inventory"
inv_path.mkdir()
(inv_path / "hosts.json").write_text(json.dumps(inventory))
```

Also remove the `json` import from line 9 if no longer used elsewhere in the file:
```python
import json  # REMOVE if not used elsewhere
```

Check if `json` is used elsewhere in the file before removing.
  </action>
  <verify>
    <automated>cd /home/devashish/workspace/ric03uec/clawrium && make test && make lint</automated>
  </verify>
  <done>Code is cleaner with no unused file operations, all tests pass, linting passes</done>
</task>

</tasks>

<verification>
1. All existing tests pass: `make test`
2. New test specifically validates inventory passing
3. Linting passes: `make lint`
4. Manual verification (if real host available): `clm host add <hostname>` should detect hardware
</verification>

<success_criteria>
- `gather_hardware()` passes inventory dict directly to `ansible_runner.run()`
- Both ansible_runner calls (setup module and lspci) include the inventory parameter
- All existing tests continue to pass
- New test validates the fix
- GitHub issue #3 root cause is resolved
</success_criteria>

<output>
After completion, create `.planning/quick/260321-jld-fix-hardware-detection-ansible-runner-ne/260321-jld-SUMMARY.md`
</output>

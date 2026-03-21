---
phase: 2
slug: host-management
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-21
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.0.0+ |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `pytest tests/test_hosts.py tests/test_hardware.py tests/test_ssh_connection.py -x` |
| **Full suite command** | `pytest tests/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_hosts.py tests/test_hardware.py tests/test_ssh_connection.py -x`
- **After every plan wave:** Run `pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 0 | HOST-01 | unit | `pytest tests/test_hosts.py -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 0 | HOST-05 | unit | `pytest tests/test_hardware.py -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 0 | HOST-01 | unit | `pytest tests/test_ssh_connection.py -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | HOST-01 | unit | `pytest tests/test_hosts.py::test_add_host -x` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | HOST-01 | unit | `pytest tests/test_ssh_connection.py::test_connection -x` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 1 | HOST-05 | unit | `pytest tests/test_hardware.py::test_parse_ansible_facts -x` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 1 | HOST-05 | unit | `pytest tests/test_hardware.py::test_gpu_detection -x` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 2 | HOST-01 | integration | `pytest tests/test_cli_host.py::test_add -x` | ❌ W0 | ⬜ pending |
| 02-04-02 | 04 | 2 | HOST-02 | integration | `pytest tests/test_cli_host.py::test_list -x` | ❌ W0 | ⬜ pending |
| 02-04-03 | 04 | 2 | HOST-03 | integration | `pytest tests/test_cli_host.py::test_remove -x` | ❌ W0 | ⬜ pending |
| 02-04-04 | 04 | 2 | HOST-04 | integration | `pytest tests/test_cli_host.py::test_status -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_hosts.py` — stubs for host storage (load/save/add/remove)
- [ ] `tests/test_hardware.py` — stubs for fact parsing, GPU detection
- [ ] `tests/test_ssh_connection.py` — stubs for SSH config parsing, connection testing
- [ ] `tests/test_cli_host.py` — stubs for CLI commands (add/list/remove/status)
- [ ] `tests/conftest.py` — SSH mocking fixtures, ansible-runner mocks

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SSH key prompting UX | HOST-01 | Requires TTY interaction | 1. Run `clm host add myhost` without --user flag 2. Verify prompt appears 3. Enter user and verify connection proceeds |
| Real hardware detection | HOST-05 | Requires actual remote host | 1. Run `clm host add <real-host>` 2. Verify architecture, CPU, memory, disk populated 3. Verify GPU detection (if host has GPU) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

VERDICT: REVISE

Round-1 items 1, 2, 5, 6 fixed. Two blockers remain from round 1 and
the commit message does not acknowledge them.

1. **Round-1 item 3 not addressed — silent snapshot fallback still
   re-opens the wolf-i trap (`upgrade.py:197-220`).** When
   `_get_live_openclaw_version` returns `None`, control drops through
   the `if live_version_str is not None:` guard at line 199 and hits
   the pre-#754 snapshot comparator at lines 222-240. On wolf-i that
   would compare snapshot `2026.6.8` against manifest max `2026.6.8`
   and emit `no-op` — the exact false-no-op #754 is meant to close.
   You even codified this behavior as a passing test at line 778
   (`test_upgrade_live_probe_fallback_to_snapshot_on_ssh_failure`).
   That test asserts the bug.

   Pick one:
   (a) fail loudly: replace the silent fall-through with
       `emit_error("live openclaw version probe failed", hint="check
       SSH connectivity to <host> then re-run; pass --skip-live-probe
       to trust snapshot")` — new hidden flag mirrors
       `--skip-drift-check`.
   (b) upgrade unconditionally: on `None`, log
       `stream_action(resource=..., message="live version probe
       failed; proceeding with force reinstall")` and skip the
       snapshot equality check entirely (`run_installation(force=True)`
       is idempotent).

   Then update the codified test:
   - Delete `test_upgrade_live_probe_fallback_to_snapshot_on_ssh_failure`
     (line 778) — it enshrines the wrong behavior.
   - Add `test_upgrade_live_probe_failure_fails_loudly` (option a) or
     `test_upgrade_live_probe_failure_proceeds_with_reinstall`
     (option b) covering the new path.

2. **Round-1 item 4 not addressed — T6 still doesn't prove preflight
   and upgrade share the resolver
   (`tests/cli/clawctl/agent/test_upgrade.py:758-775`).** The
   extraction from item 1 is done, so the shared symbol
   `clawrium.core.openclaw_version.get_host_openclaw_version` now
   exists — but T6 still only patches the local wrapper
   `clawrium.cli.clawctl.agent.upgrade._get_live_openclaw_version`
   and only exercises the upgrade code path.

   Rewrite as either:
   - one test that patches
     `clawrium.core.openclaw_version.get_host_openclaw_version` with
     a spy, invokes both the upgrade path AND
     `lifecycle_canonical.sync_agent_canonical` (or the direct
     brave-preflight helper at `lifecycle_canonical.py:2383`),
     asserting the spy was called from each; OR
   - two tests sharing the same patch target, one per code path,
     each asserting `mock.call_count == 1`.

Everything else — extraction (item 1), lifecycle/lifecycle_canonical
imports (item 2), `os_family` kwarg passthrough at `lifecycle.py:2983`,
BC alias at `lifecycle_canonical.py:88`, updated patch targets in
`tests/core/test_lifecycle_canonical.py` and
`tests/test_lifecycle.py`, new `tests/core/test_openclaw_version.py`
(7 tests: dispatcher Linux/Darwin routing, nonzero-exit, unparseable
output, stderr capture, parametrized semver parse) — is correct.

`make lint` clean, `uv run pytest` 4789 passed / 8 skipped. Rebase on
`origin/main` (still one commit ahead: `40b4b2a`) is deferred until
after these two items land.

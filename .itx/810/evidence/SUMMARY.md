# UAT Summary — Issue #810

## Targets used

- `wolf-i` (Linux, openclaw record in `status=failed, installed_at=null` — the
  natural #790 repro state, perfect for baseline + post-fix.)
- `esper-macmini` (darwin, healthy openclaw — regression check.)

## Evidence ledger

| File | Phase | Verdict |
|---|---|---|
| `wolf-i/00a-baseline-describe.txt` | Pre-fix, capture record shape | `status=failed`, `installed_at=-` confirmed |
| `wolf-i/00b-attach-brave.txt` | Pre-fix, recreate the bug surface | wolf-brave integration attached on failed agent |
| `wolf-i/00-baseline-repro.txt` | Pre-fix `clawctl agent sync wolf-i` | Bug reproduced: error tells operator to `clawctl agent upgrade` (the misleading `clawctl_upgrade_strips_attachments` path) |
| `wolf-i/01-postfix-sync-refused.txt` | Post-fix `clawctl agent sync wolf-i` | New clear error: refuses with `clawctl agent create wolf-i --type openclaw --host wolf.tailf7742d.ts.net --cleanup-failed` hint, mentions attachments preserved |
| `wolf-i/02-postfix-attachments-still-present.txt` | After refused sync | wolf-brave still attached — no silent mutation |
| `wolf-i/02b-describe-after-refused-sync.txt` | After refused sync, full record | All record state intact |
| `wolf-i/05-postfix-degenerate-detach-still-refused.txt` | D2: operator detaches mid-recovery | Even with the integration detached, sync still refuses on a `status=failed` record — fix is correct (root cause is the failed install, not the integration) |
| `esper-macmini/06-postfix-healthy-agent-still-works.txt` | D3: regression on a healthy openclaw | `synced (drift=0)` — guard does not fire on `status=installed`+`installed_at=…` records |

## Deliberately skipped

- **Happy path step 3 (`clawctl agent create wolf-i --cleanup-failed`)** —
  running a full openclaw reinstall on the operator's live `wolf-i` would
  delete the existing failed record, push a fresh playbook against the
  remote host, and overwrite operator state (port allocations, gateway
  token, on-host `~/.openclaw/`). That's high blast radius for a UAT
  step. The fix routes the operator to the correct existing command;
  `clawctl agent create --cleanup-failed` already has its own coverage
  (`tests/test_install.py`, `core/install.py:449`). The control-plane
  guard's contract is "stop and point at the repair command", which is
  fully verified above.

## Conclusion

Bug behavior reproduced (`00-baseline-repro.txt`).
Fix observed live (`01-postfix-sync-refused.txt`): correct error string,
correct exit code, attachments preserved, regression-safe on healthy
agents, degenerate-case-safe on detach-mid-recovery.

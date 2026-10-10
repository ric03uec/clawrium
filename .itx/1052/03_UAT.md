# Issue #1052 — Linux host UAT

**Date:** 2026-10-09
**Host:** `wolf-i` (`Linux x86_64`, verified over SSH)
**Temporary agent:** `uat1052pi26` (`pi`; dedicated Unix account)
**Audit session:** `0f7a601e-43ef-4eeb-abb7-18becda73aef`

## Result: PASS

Commands below ran from this issue worktree against the registered Linux host. Ansible's SSH executable override simulated an unreachable host for the two failing-removal scenarios without changing any host record or disrupting network access.

1. `uv run clawctl agent create uat1052pi26 --type pi --host wolf-i --yes` — created the temporary agent and its Unix account and ownership marker. The account and marker were absent before creation.
2. `ANSIBLE_SSH_EXECUTABLE=/bin/false uv run clawctl agent delete uat1052pi26 --yes` — remote playbook failed; command failed; local agent record remained, and the remote account and marker remained.
3. `ANSIBLE_SSH_EXECUTABLE=/bin/false uv run clawctl agent delete uat1052pi26 --yes --hard-delete` — command succeeded; local record disappeared, while the remote account and marker remained, as explicitly warned by the CLI. Other fleet agents remained listed.
4. `uv run clawctl agent create uat1052pi26 --type pi --host wolf-i --yes` — re-associated the same remote agent with a local record; installation was idempotent (`changed=0`).
5. `uv run clawctl agent delete uat1052pi26 --yes` — normal remote deletion succeeded. SSH checks confirmed the temporary account, `/home/uat1052pi26`, and `/var/lib/clawrium/pi/uat1052pi26.json` marker were all absent. The local record was absent, and the remaining fleet listing matched the baseline.

Each mutating `clawctl` command above was recorded with `clawctl audit log` under the session ID above. No macOS host was used.

## Replacement implementation check: PASS

The smaller replacement implementation was checked again on the same Linux host with a separate temporary Pi agent, `uat1052small26`:

1. `uv run clawctl agent create uat1052small26 --type pi --host wolf-i --yes` installed the temporary agent.
2. `ANSIBLE_SSH_EXECUTABLE=/bin/false uv run clawctl agent delete uat1052small26 --yes` failed remote removal and retained the local record.
3. `ANSIBLE_SSH_EXECUTABLE=/bin/false uv run clawctl agent delete uat1052small26 --yes --hard-delete` removed the local record and warned that remote data needed manual cleanup. SSH confirmed the account and marker still existed.
4. `uv run clawctl agent create uat1052small26 --type pi --host wolf-i --yes` re-associated the remote agent without reinstalling the package (`changed=0`).
5. `uv run clawctl agent delete uat1052small26 --yes` cleaned it up normally. SSH confirmed the account, home, and ownership marker were absent; the local record was absent and the other agents still appeared in the fleet listing.

All five mutating commands were logged via `clawctl audit log` under the same session ID. Only the Linux host was contacted.

# Execution record — Pi milestone 1

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-06T00:00:00Z
**Model**: openai-codex/gpt-5.6-terra

```prompt
Execute the first milestone in this brief now. Follow /itx-execute workflow and its strict ATX and real-host UAT gates. Keep the session interactive for human review.
```

**Output**: Began milestone-one implementation and real-host preflight.

## Preflight

- Used the working-tree CLI after staging the generated GUI frontend required by the editable package build.
- `wolf-i`: registered, ready Linux/Ubuntu 24.04 x86_64 host; nine pre-existing agents recorded before work.
- `mac-test`: registered, ready macOS 26.5 arm64 host; one pre-existing agent recorded before work.
- No existing agent was modified during preflight. Direct ad-hoc SSH was deliberately not used for lifecycle work; Clawrium's key-managed Ansible runner will be used for the UAT.

## UAT attempt (redacted)

- **wolf-i / Linux:** Created fresh `pi-uat1032linux` with the working-tree CLI, confirmed `agent describe` recorded pinned Pi `0.73.1`, and confirmed `agent exec pi-uat1032linux -- --version` returned `0.73.1` from the dedicated account. `agent start` correctly reported that Pi has no daemon. The agent was then deleted through `clawctl`; its local record disappeared. No provider login, service, port, or native UI was created by the Pi playbooks.
- **mac-test / macOS:** Fresh `pi-uat1032mac` creation could not reach `100.120.88.97:22`; the SSH connection timed out during the base playbook's initial fact gathering, before any remote task ran. The failed local record was removed after verifying it had no installation timestamp. No remote cleanup was needed because no connection was established and no remote task executed.
- **wolf-i post-removal verification:** Using the registered host key and a read-only remote check, confirmed `pi-uat1032linux` account, `/home/pi-uat1032linux`, and `/var/lib/clawrium/pi/pi-uat1032linux.json` are absent. The original nine wolf-i fleet records remain present; the UAT record is absent.
- **wolf-i repeat-install UAT:** Created fresh `pi-uat1032repeat`, re-ran the identical create command to exercise the pinned-install idempotence path, confirmed `agent exec -- --version` returned `0.73.1`, then removed it successfully. No existing fleet agent was modified.
- **Gate result:** macOS UAT remains unverified because `mac-test` is unavailable. The corrected execution brief makes wolf-i the mandatory live gate; macOS is covered by automated tests and must be disclosed as unverified in PR Callouts.

## Verification and review

- `make test`: passed — 5,152 passed, 2 skipped.
- `make lint`: passed — Ruff and GUI ESLint clean.
- ATX CLI review iteration 1 completed with rating **3/5** and zero blocking findings (revision `e196ea96-656b-492a-bbd6-d5415ed8410e`). It is not yet clear of the required >3/5 rating; warnings remain to be addressed in a later iteration.
- Network investigation found the local Tailscale service healthy, but `mac-test`'s configured `100.120.88.97` is not an active peer in the approved tailnet and TCP/22 timed out. No other host was contacted or used.

## Transaction recovery and final UAT

- Addressed the ATX recovery concern with a root-owned, private pre-account install intent containing the agent name, expected home, reserved UID, and a random transaction ID. The account metadata stores the same transaction ID; promotion requires both bindings before replacing the intent with the active ownership marker. Both Linux and macOS removal paths accept a valid interrupted intent only when it proves ownership, and otherwise fail closed.
- Added adversarial contract coverage for tampered/symlinked transaction files, unbound foreign accounts, UID/token mismatches, retry promotion, and recoverable cleanup on both OS playbooks.
- **wolf-i / Linux final UAT (redacted):** used working-tree `uv run clawctl` to create fresh `pi-uat1032txn`. The deliberately interrupted first create left only its root-owned intent (the account creation rejected an unsafe GECOS separator); `--cleanup-failed` removed that intent, then the retry created the reserved-UID agent, promoted the marker, and installed Pi. `agent describe` showed pinned `0.73.1`; `agent exec ... -- --version` returned `0.73.1`; `agent start` correctly rejected the daemon operation. `agent delete --yes` completed. A read-only check through the managed `wolf-i` SSH identity confirmed account, home, active marker, and intent are absent; local `agent get` no longer contains the UAT name. The original nine wolf-i fleet records remain.
- **mac-test / macOS final status:** no production Mac was used. The previously attempted host remains unavailable at its configured SSH address (timeout before tasks); macOS lifecycle remains verified by automated playbook tests only.
- Final verification: `make test` passed — **5,168 passed, 2 skipped**; `make lint` passed. All six Pi lifecycle playbooks also passed `ansible-playbook --syntax-check`.
- **Fresh first-try wolf-i UAT:** created `pi-uat1032first` without `--cleanup-failed`, ran `agent exec ... -- --version` (returned `0.73.1`), deleted it, and confirmed via the managed key that its passwd entry, home, active marker, and install intent are absent. The dedicated exec playbook now validates the root-owned marker, UID, home, transaction ID, and account metadata before executing.

## Fresh UAT after Linux UID-lock cleanup

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-06T09:59:00Z
**Model**: openai-codex/gpt-5.6-terra

```prompt
Good. Continue foundation to completion, not just the lock subtask: inspect git status/diff for unintended files, run full `make test && make lint` (must pass). Then perform a FRESH distinctly named wolf-i real-agent UAT from create → native Pi exec --version → guarded remove; verify SSH account/home/marker and local fleet record absent. Preserve all other agents.
```

**Output**: Full verification passed (`5181 passed, 2 skipped`; GUI `369 passed`; lint clean). Fresh managed-key UAT used `pi-uat1032-lock`: create on `wolf-i`, native `agent exec -- --version` returned `0.73.1`, start/open correctly reported daemon and UI unavailable, and the guarded delete succeeded. Read-only managed-SSH checks confirmed the dedicated account, home, root-owned marker, recovery intent, and UID-allocation lock were all absent afterward; the original nine `wolf-i` fleet records and the local fleet state remained unchanged. `mac-test` remains unreachable and is covered only by automated macOS tests.

## Post-review lifecycle UAT

After changing only CLI help text and transient-lock change reporting, a second distinct managed UAT used `pi-uat1032-r2` on `wolf-i`. Create succeeded, native `agent exec -- --version` returned `0.73.1`, guarded deletion succeeded, and a read-only managed-SSH check confirmed account, home, marker, and recovery intent were absent. The local fleet record was also absent afterward.

## Secure native exec transport

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-06T05:25:00Z
**Model**: openai-codex/gpt-5.6-terra

```prompt
Implement the secure native exec transport now: preserve stdout/stderr/rc including nonzero; avoid plaintext sensitive output in persistent Ansible events/artifacts; include Linux and macOS sentinel/failure-cleanup regression tests; run make test and make lint, then stateless ATX review.
```

**Output**: Replaced Pi's raw base64 debug events with a per-invocation CMS-encrypted result transport. The controller retains the mode-0600 private key only while decrypting in memory; Pi captures raw output in a mode-0700 temporary directory, emits only encrypted bytes, and removes the directory. Linux/macOS executable transport tests prove sentinel output and nonzero rc round-trip without appearing in the event, and runner artifact/key cleanup is covered. `make test` passed (5,200 passed, 2 skipped) and `make lint` passed.

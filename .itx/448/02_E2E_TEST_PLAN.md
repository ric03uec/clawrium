# Issue #448 — End-to-end manual test plan (wolf-i)

> **Execution record (2026-05-29, against wolf-i).** Scenarios 2, 3, 6
> executed against a throwaway hermes agent `test448` on wolf-i.
> Scenario 3 failed on first run and surfaced a real defect: the
> paramiko env-probe ran `grep` as `xclm` without `sudo`, so the
> 0700-mode agent home made the file unreadable — the helper saw
> empty stdout and returned the non-fatal "API_SERVER_KEY not present"
> path, the reconcile never fired, the daemon kept enforcing the
> corrupt bearer. Fix: `sudo -n grep ...` in the probe. After fix,
> Scenarios 2 and 3 PASS end-to-end (bearer survives across stop/start,
> drift is detected and reconciled, HTTP 200 with canonical bearer).
> Scenario 1 (host re-record) and the IP→DNS migration in Scenario 2
> were skipped to avoid mutating the live wolf-i record that 7 other
> agents depend on — covered by unit tests
> (`tests/cli/clawctl/host/test_create_preserves_key_id.py`,
> `tests/core/test_secrets_keying.py`). Throwaway agent `test448`
> removed cleanly; secret cleanup on remove went through the new
> `key_id`-keyed slot and emitted "Cleaned up instance secrets".


Branch under test: `issue-448-stable-secrets-keying` (PR #551, HEAD `643e884`).

Goal: validate that the maurice/wolf-i breakage that motivated #448
cannot reproduce on the patched code, and that no nearby behavior
regressed. Pure unit/mock coverage is in place — this plan covers the
parts that can only be exercised against a real host.

## Pre-conditions

1. wolf-i is reachable on **both** its old IP (`192.168.1.36`) and the
   Tailscale DNS name (`wolf.tailf7742d.ts.net`). If it isn't, swap in
   any two coordinates that both resolve to the same machine.
2. You have an existing `hermes` agent named `maurice` installed on
   wolf-i with a working provider key. (If you don't, the very first
   scenario installs one.)
3. **Back up local state first** — every scenario below mutates
   `~/.config/clawrium/`:
   ```bash
   cp -r ~/.config/clawrium ~/.config/clawrium.backup-$(date +%s)
   ```
4. Install the branch:
   ```bash
   cd ~/workspace/ric03uec/clawrium-issue-448
   uv tool install --editable . --force
   clm --version   # confirm
   ```
5. Tail logs in another pane so you can correlate:
   ```bash
   ssh xclm@192.168.1.36 'journalctl -u hermes-maurice.service -f'
   ```

A failure in **any** scenario below means **do not merge**.

---

## Scenario 1 — `get_host` resolves by `key_id` after hostname mutation

This is the smallest possible repro of the keying contract.

```bash
# 1a. Register wolf-i by IP (skip if already registered).
clm host create 192.168.1.36 --user xclm --alias wolf-i
jq '.[] | select(.alias=="wolf-i") | {hostname, key_id, alias}' \
  ~/.config/clawrium/hosts.json
```
**Expect:** `hostname == "192.168.1.36"`, `key_id == "192.168.1.36"`.

```bash
# 1b. Re-record with the Tailscale DNS name.
clm host create wolf.tailf7742d.ts.net --user xclm --alias wolf-i
```
**Expect:** Exit code 0. Output contains
`hostname 192.168.1.36 → wolf.tailf7742d.ts.net (key_id preserved: 192.168.1.36)`.

```bash
# 1c. Inspect the record.
jq '.[] | select(.alias=="wolf-i") | {hostname, key_id, addresses}' \
  ~/.config/clawrium/hosts.json
```
**Expect:**
- `hostname == "wolf.tailf7742d.ts.net"`
- `key_id == "192.168.1.36"` ← unchanged, this is the whole point
- exactly **one** entry in `addresses` has `is_primary: true`, and its
  `address` is `wolf.tailf7742d.ts.net`
- the old `192.168.1.36` entry is still in `addresses` but not primary

**Fail conditions:** `key_id` changed; `addresses` list grew unbounded
or lost a primary; exit code non-zero.

---

## Scenario 2 — secrets survive the hostname mutation (the #448 core fix)

This is the canonical repro from the issue.

```bash
# 2a. Reset wolf-i to the IP coordinates and confirm an agent is
# installed with a secret. Pick any agent type with secrets — the
# original repro used hermes/maurice with HERMES_API_SERVER_KEY.
clm host create 192.168.1.36 --user xclm --alias wolf-i
clm agent get   # confirm maurice is installed

# 2b. Note the bearer secrets.json holds for maurice.
jq '."192.168.1.36:hermes:maurice".HERMES_API_SERVER_KEY.value' \
  ~/.config/clawrium/secrets.json
```
**Expect:** a 64-char lowercase hex string. **Copy it** — call this
`$BEFORE`.

```bash
# 2c. Chat works on the IP-form host.
clm agent chat maurice -m "ping"
```
**Expect:** a response, exit code 0. No 401.

```bash
# 2d. Migrate hostname to DNS (the operation that historically broke).
clm host create wolf.tailf7742d.ts.net --user xclm --alias wolf-i

# 2e. Re-inspect secrets.json — the bearer must still be under the
# OLD key (192.168.1.36:hermes:maurice), unchanged.
jq '."192.168.1.36:hermes:maurice".HERMES_API_SERVER_KEY.value' \
  ~/.config/clawrium/secrets.json
```
**Expect:** equal to `$BEFORE`. No new `wolf.tailf7742d.ts.net:hermes:maurice` entry.

```bash
# 2f. Chat after the migration — the actual proof.
clm agent chat maurice -m "still here?"
```
**Expect:** a response, exit code 0. **A 401 here means the fix
failed and the PR must not merge.**

```bash
# 2g. Sync and configure paths exercise the same lookup.
clm agent sync maurice
clm agent configure maurice --stage providers   # no-op if already complete
```
**Expect:** both succeed without any "missing or invalid" secret error.

**Fail conditions:** any of 2c, 2f, 2g returns 401 or "DISCORD_BOT_TOKEN/
HERMES_API_SERVER_KEY missing or invalid"; a duplicate secrets entry
appears under the new hostname.

---

## Scenario 3 — env-file reconcile (Phase 3 invariant)

This proves the new pre-start probe in `lifecycle.start_agent`
actually reconciles `.env` drift instead of just looking like it does
in unit tests.

```bash
# 3a. Force a deliberate drift: scribble a bogus bearer into the
# on-host .env without going through configure.
ssh xclm@wolf.tailf7742d.ts.net \
  "sudo -u maurice sed -i 's|^API_SERVER_KEY=.*|API_SERVER_KEY='\\''deadbeef'\\''|' \
   /home/maurice/.hermes/.env"
ssh xclm@wolf.tailf7742d.ts.net \
  "grep '^API_SERVER_KEY' /home/maurice/.hermes/.env"
```
**Expect:** `API_SERVER_KEY='deadbeef'`.

```bash
# 3b. Stop, then start. The pre-start probe must notice the drift,
# trigger configure to re-render .env, and only then run start.
clm agent stop maurice
clm agent start maurice
```
**Expect:** the start output emits the line
`API_SERVER_KEY drift detected between .env and secrets.json; reconfiguring before start`
before the start playbook runs. Exit code 0.

```bash
# 3c. Confirm .env was re-rendered from secrets.json.
ssh xclm@wolf.tailf7742d.ts.net \
  "grep '^API_SERVER_KEY' /home/maurice/.hermes/.env"
```
**Expect:** equals `$BEFORE` from Scenario 2 (the secrets.json value),
no longer `deadbeef`.

```bash
# 3d. Chat works.
clm agent chat maurice -m "after reconcile"
```
**Expect:** response, exit code 0.

**Fail conditions:** no drift-detection line; `.env` still says
`deadbeef`; chat 401s.

---

## Scenario 4 — non-fatal probe on transient SSH failure

Proves the probe doesn't synthesize a configure storm when the host
is unreachable. (Pulls the cable, metaphorically.)

```bash
# 4a. Make the configured hostname unresolvable. Easiest: re-record
# the alias to a bogus DNS name with no A record, then try to start.
clm host create wolf-bogus-does-not-resolve.invalid \
  --user xclm --alias wolf-i
# This will fail at the SSH verify step inside host create — that's
# fine; the test is whether start_agent's *probe* failure is silent.
```

If 4a errored out cleanly at host-create's SSH verify, you've already
got the answer for that surface. The probe surface itself is harder
to exercise without a privileged ssh-firewall setup. If you don't
have one handy, the unit test
(`test_probe_is_non_fatal_on_ssh_failure`) already covers this; mark
Scenario 4 as "covered by unit test" in your run notes.

---

## Scenario 5 — recycled-IP smoke check (ATX iter-1 W2 — known follow-up)

This scenario is **expected to fail** today and is documented as a
follow-up in the PR. Run it so you know exactly what regression a
later fix will address.

```bash
# 5a. After Scenarios 1-3, delete the wolf-i record entirely.
clm host delete wolf-i --force

# 5b. Register a *different* machine at the same old IP. (Use any
# spare host whose IP you can temporarily assign to 192.168.1.36 —
# or skip this scenario and mark "deferred per PR Callouts".)
clm host create 192.168.1.36 --user xclm --alias different-host

# 5c. Inspect secrets.json — the orphaned 192.168.1.36:hermes:maurice
# entry from before will still be present and reachable by anything
# that constructs that instance_key.
jq 'keys[]' ~/.config/clawrium/secrets.json
```
**Expect (known gap):** the old `192.168.1.36:hermes:maurice` key is
still there. The PR does **not** scan-and-warn on this; that's W2
deferred. Document it in your run notes; do not block merge on it.

---

## Scenario 6 — regression sweep on adjacent surfaces

These are the surfaces I touched but couldn't validate against a real
host. Smoke them.

```bash
# 6a. clm secret list — routes through the modified get_installed_claw.
clm agent secret list maurice
```
**Expect:** lists HERMES_API_SERVER_KEY (and any provider keys),
shows the host identifier next to the agent name. (It now shows
`key_id` instead of `hostname` for display — that's intentional.)

```bash
# 6b. clm agent get — host record rendering.
clm agent get
```
**Expect:** maurice listed under wolf-i, no traceback.

```bash
# 6c. clm host get -o json — confirm shape is intact.
clm host get -o json | jq '.[] | {name, hostname, key_id}'
```
**Expect:** every record has both `hostname` and `key_id` populated;
no nulls.

```bash
# 6d. GUI smoke (if you run it).
clm gui open
# Click into maurice → confirm dashboard loads, no 500s in the GUI log.
```

**Fail conditions:** any traceback; missing fields; GUI 500.

---

## Post-test cleanup

```bash
# Restore your real config if any scenario corrupted it.
mv ~/.config/clawrium ~/.config/clawrium.test-run
mv ~/.config/clawrium.backup-* ~/.config/clawrium
```

If everything passed, throw away the backup; otherwise keep it.

## Reporting

After the run, append a comment to PR #551 with:
- Pass / fail for each scenario.
- For failures: the exact command, output, and `journalctl` excerpt.
- Confirm `make test` and `make lint` still pass after any local edits
  you made during testing.

If Scenarios 1, 2, and 3 all pass, the #448 fix is validated against
the original maurice/wolf-i breakage and the PR is ready to merge
(modulo the iter-1 W2-W6 follow-ups documented in the PR Callouts).

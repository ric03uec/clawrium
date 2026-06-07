# Issue #608 — `pair_device.mjs` Protocol Mismatch

**Issue:** https://github.com/ric03uec/clawrium/issues/608
**Discovered via:** #604 (openclaw on macOS — PR #607 `[UNRESOLVED]` Callout)

## Customer Outcome
A fresh `clawctl agent create --type openclaw --host <host>` against the currently-pinned openclaw v2026.5.28 completes end-to-end on both Linux and macOS, with `hosts.json.agents.<name>.config.gateway.device_*` populated and the agent reaching `READY`.

## Scope Decision
**Proper fix only.** No manifest revert / version pin / workaround. The pair client must speak the protocol the current pinned daemon expects, and survive the next upstream bump without re-breaking.

## What the Code Actually Says

`src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs`:

- **Line 94–95:** `minProtocol: 3, maxProtocol: 3` — both pinned to 3, no negotiation window. This is the immediate failure.
- **Line 43:** signature payload schema is the string literal `"v2|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce"`. **`v2` here is the payload format, not the connect protocol.** They are independent versioned axes. The v3→v4 connect-protocol bump may or may not also bump the payload schema.
- **Line 75:** waits for `event: connect.challenge` from server, then sends `connect` request. The daemon-side response shape (`auth.deviceToken`) is what we currently consume.

Manifest `src/clawrium/platform/registry/openclaw/manifest.yaml` pins openclaw to **v2026.5.28** for Linux (22.04 + 24.04) and macOS (arm64, >=14). v2026.4.2 and v0.1.0 entries also exist (older). The manifest is NOT changing in this issue — the script must speak v2026.5.28's protocol.

Existing pair tests (`tests/test_configure_claw.py:2515-2547`): three static regex-grep checks (parse-error logging, nonce validation, timeout). **No behavioral test.** None would have caught this.

## Test Host

**`wolf-i`** — Linux x86_64, ubuntu 24.04, already in `hosts.json`. Currently runs:
- Openclaw `wolf-i` agent at v2026.4.2 (paired pre-protocol-bump, working).
- Hermes agents `espresso`, `maurice`, `clawctl-demo`.
- Zeroclaw agents `clawrium-d01`, `nemotron-beta`, `nemotron-alpha`.

**Verification install on wolf-i will use a new agent name** (e.g. `openclaw-608`) so the existing `wolf-i` openclaw agent (and its discord channel + onboarding state) is not disturbed. Port allocator pool `40000..41999` has plenty of headroom (current uses: 40198, 40919, 40971, 41429).

**Pre-step before verification (separate, already-requested by user):** wolf-i's primary address in `hosts.json` flips from `192.168.1.36` to the tailscale hostname `wolf.tailf7742d.ts.net`. Pair verification runs after that flip so the test traverses the address path that will be production going forward.

## Phased Plan

### Phase 1 — Read the v2026.5.28 daemon's `connect` handler (no code)
**Exit:** know exactly what changed from protocol v3 → v4 so we can implement it, not guess.

1. SSH to wolf-i. Read the v2026.5.28 daemon source — installed under `/home/<agent>/.openclaw/...` via npm. Find the gateway's pair handler. Look for:
   - The `expectedProtocol` field's source (literal constant? config flag?).
   - The connect-request schema for protocol v4: required fields, removed fields, renamed fields vs. v3.
   - Whether `v4` accepts `minProtocol: 3, maxProtocol: 4` and negotiates down to v3, or whether `min=3` is rejected outright.
   - Whether the signature payload schema bumped (`"v2|..."` → `"v3|..."` or some other shape).
   - The response shape — confirm `result.auth.deviceToken` is still the field we read.
2. Record findings as an issue comment on #608 before starting Phase 2. This is the spec for the implementation.

**Why this step exists:** the bug report assumes v4 differs only in the protocol version field. The code may say otherwise. Building Phase 2 on assumption is how we end up shipping a "fix" that breaks differently. Read first.

### Phase 2 — Update `pair_device.mjs` to speak the negotiated protocol
**Exit:** script speaks v2026.5.28's protocol; degrades gracefully against older daemons; surfaces a clear error against unknown future protocols.

Concrete changes to `src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs`:

1. **Negotiation range, not pin.** `minProtocol: 3, maxProtocol: 4` (or whatever the upper bound Phase 1 confirms). The daemon picks the version both sides support.
2. **Payload format branching IF Phase 1 finds the schema bumped.** Build the signature payload from a `payloadVersion`-keyed function table, not a string literal. Today's v2 stays; if v4 connect requires a v3 payload (or v4 payload), add the new schema as a sibling and select based on the negotiated protocol from the daemon's challenge or connect-ack.
3. **Other v4-specific fields IF Phase 1 finds new required fields.** Add them; default sensibly for v3 callers.
4. **Clear failure mode for unknown protocol.** If the daemon advertises a protocol outside `[minProtocol, maxProtocol]`, the existing `error: 'protocol mismatch'` already fires — keep it, but make sure the error message names the version we saw vs. the range we support, so the NEXT operator hitting this knows what to bump.
5. **No version-bump-as-side-effect.** Don't touch the manifest in this phase. Don't add a workaround for any one specific daemon version. The script must be a function of the negotiated protocol, full stop.

### Phase 3 — Behavioral regression test
**Exit:** a test in the suite would fail today (against the unfixed script) and pass after Phase 2 — and would catch the next protocol bump.

New file: `tests/platform/test_pair_device_protocol.py` (or extension of `tests/test_configure_claw.py` — pick whichever matches project convention; check neighbors first).

Test harness: in-process Node WebSocket server (the `ws` library is already a dev dep via hermes' ui-tui builds) that mimics the openclaw `connect.challenge` → `connect` → `auth.deviceToken` flow. The mock daemon is parameterized by `expectedProtocol`.

Cases:

1. **Daemon `expectedProtocol=4`:** pair script connects, server picks v4 from advertised range, signature payload uses whichever schema Phase 1 said v4 wants, response carries `auth.deviceToken`, test reads `stdout` JSON and asserts `deviceId / deviceToken / privateKeyPem` present.
2. **Daemon `expectedProtocol=3`:** backward compatibility — same flow, server picks v3, signature payload uses v2 schema (today's behavior), `auth.deviceToken` returned. Asserts no regression for hosts still on the older daemon.
3. **Daemon advertises `expectedProtocol=5`:** pair script exits non-zero with a clear error naming "supports 3-4, daemon expected 5". This is the **future-proofing assertion** — the NEXT time openclaw bumps, the failure is loud and self-describing.
4. **Daemon `expectedProtocol=2`:** pair script exits non-zero (we dropped v2 support — if it never existed, this case stays). Same loud-failure shape as case 3.

Test runs `node pair_device.mjs ws://127.0.0.1:<test-port> <token>` as a subprocess. If `node` is missing in the test environment, `pytest.skip("node required for behavioral pair test")` — but verify `make test` already exercises node (hermes ui-tui build does) so CI runs it.

### Phase 4 — Real-host verification on `wolf-i` (merge gate)
**Exit:** fresh openclaw install at v2026.5.28 completes end-to-end on wolf-i; existing `wolf-i` agent at v2026.4.2 unaffected.

**Pre-condition:** wolf-i primary address already flipped to `wolf.tailf7742d.ts.net` in `hosts.json` (separate operation, done before this phase).

Sequence (run from main checkout with Phase 2 code merged or staged locally):

1. **Confirm existing `wolf-i` openclaw agent is healthy.** `clawctl agent get` shows `runtime.status: running` for `wolf-i/openclaw`. Baseline — anything that breaks this is a regression.
2. **Fresh install with a new name:** `clawctl agent create openclaw-608 --type openclaw --host wolf-i`. Must reach `READY`.
3. **Inspect `hosts.json.agents.openclaw-608.config.gateway`:**
   - `port` in `40000..41999`, not colliding with `40198 / 40919 / 40971 / 41429`.
   - `auth` populated (≥32 chars).
   - `device.id`, `device.token`, `device.privateKey` populated.
4. **Lifecycle round-trip:** `clawctl agent stop openclaw-608` → `start` → `restart`. Each command exits 0. Daemon listens after start, doesn't after stop.
5. **Re-install idempotency:** re-run `clawctl agent create openclaw-608 --type openclaw --host wolf-i`. Pair must skip; `device.id` and `device.token` from step 3 must be identical after the re-run. Data-corruption guard.
6. **Old agent untouched:** `hosts.json.agents.wolf-i.config.gateway.device.id` unchanged from before Phase 4. The existing agent's bearer token, ports, onboarding state, discord channel binding all preserved.
7. **Clean teardown:** `clawctl agent remove openclaw-608 --yes`. `hosts.json.agents.openclaw-608` gone; remote `/home/openclaw-608/` removed; systemd unit `openclaw-openclaw-608.service` absent; no orphan state.
8. Paste the full output log into the PR body under `## Real-host verification`.

If any step fails, **the PR does not merge.** No `[ITX-STUCK]` shortcut — this is the bug we're fixing.

### Phase 5 — CHANGELOG + close
**Exit:** PR mergeable.

- `CHANGELOG.md` `[Unreleased] ### Fixed`: "Openclaw pairing now negotiates protocol v3 and v4, unblocking fresh installs against openclaw v2026.5.28+ on both Linux and macOS (#608)."
- `make test` + `make lint` green.
- PR title: `fix(openclaw): pair_device.mjs negotiates protocol v3/v4 (#608)`.
- PR body includes Phase 1 findings, Phase 4 verification log, and a `## Callouts` section.

## Files Affected

| Phase | File | Change |
|---|---|---|
| 2 | `src/clawrium/platform/registry/openclaw/scripts/pair_device.mjs` | Negotiate v3/v4; payload schema dispatch if Phase 1 finds it bumped; clearer unknown-protocol error |
| 3 | `tests/platform/test_pair_device_protocol.py` (new) | Behavioral test with mock ws daemon, four protocol cases |
| 5 | `CHANGELOG.md` | `### Fixed` entry |

Three files. No manifest changes. No version pins moved.

## Out of Scope

- Manifest version pin changes (v2026.5.28 stays).
- Refactoring the install playbooks' pair invocation (already correct shape).
- Supporting arbitrary future protocols by reading `expectedProtocol` and adapting — that's protocol-divination, not engineering. Bumping the supported range when upstream bumps is the right cadence.
- macOS-specific verification — the same fix unblocks both platforms; Linux verification on `wolf-i` is sufficient because the bug is OS-agnostic (daemon-side protocol drift).

## Risks

- **Phase 1 may discover the v4 changes are bigger than just the protocol number field** — new required fields, renamed scopes, payload schema bump. Phase 2 scope absorbs this (payload format is already planned to branch), but it could turn a small patch into a medium one. Time risk only; correctness path unchanged.
- **The `ws` mock daemon in the test harness must faithfully mimic the real handshake** — if the mock is wrong, the test passes against the mock but the real daemon still rejects us. Mitigation: Phase 1 reads the real daemon's handler before writing the mock; mock asserts byte-shape match for at least one captured real challenge frame.
- **`node` availability in CI** — gate the new behavioral test on `node` presence with `pytest.skip` so the test suite doesn't false-fail on environments without it. Verify `make test` runs node today (hermes ui-tui build path).
- **Existing openclaw `wolf-i` agent regression** — Phase 4 step 1 captures the baseline; step 6 re-checks. The install playbook gates pair on `not openclaw_already_installed` so a re-run on the existing agent name won't re-pair, but a code path change in `pair_device.mjs` could affect both. Test the negotiation against the live v2026.4.2 daemon (case 2 in Phase 3) before Phase 4.

---

<details>
<summary>Prompt Log</summary>

**Stage**: plan
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-04T00:00:00Z
**Model**: claude-opus-4-7

```prompt
608 (no files, just execution plan)
```

Follow-up: `update plan with track b. no workaround or hacks. need a proper fix. use wolf-i host to test. switch the wolf-i ip to the alternate ip as primary. update plan first`

**Output**: Single-track plan (Track A workaround dropped). Five phases: read v2026.5.28 daemon's pair handler → update pair_device.mjs to negotiate v3/v4 with payload-schema branching → behavioral regression test with mock ws daemon → real-host verification on wolf-i with a fresh agent name (`openclaw-608`) so existing `wolf-i` agent stays intact → CHANGELOG + PR. No manifest changes, no version pin shifts, no shortcuts. Test pre-condition: wolf-i primary address flipped to tailscale hostname (separate operation, requested by user).

</details>

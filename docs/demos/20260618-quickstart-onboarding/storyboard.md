# Clawrium Quickstart Onboarding — Storyboard

**Output**: `docs/demos/recordings/quickstart-onboarding.mp4` (gitignored; uploaded to YouTube)
**Style**: Long-form storyboarded demo
**Execution**: All-LIVE end-to-end on host `wolf-i`
**Reference page**: https://ric03uec.github.io/clawrium/docs/guides/quickstart

## Pre-flight checklist

- [ ] Every command below has been run manually at least once on wolf-i.
- [ ] Captured outputs committed under `docs/demos/quickstart-onboarding/outputs/NN-<scene-slug>.txt`.
- [ ] Stitched transcript produced at `docs/demos/quickstart-onboarding/stitched.txt` with runtime estimate.
- [ ] User has reviewed and truncated long outputs before recording.
- [ ] Non-deterministic values masked (timestamps, UUIDs, IPs, secret values).
- [ ] `_SCENES=(...)` in `_quickstart-onboarding_helpers.sh` matches the scene table below (titles + order).
- [ ] User has approved this storyboard before recording.

## Fleet target

| Field | Value |
|---|---|
| Host | `wolf-i` (already registered) |
| Agent name | `quickstart-demo` |
| Agent type | `hermes` |
| Provider attached | `clawrium-gtm-litellm` (model: `writer`) |

## Scenes

> Scene 1 is fixed by convention: every clawrium demo opens with `clawctl --version` so viewers can anchor the recording to a known release. Do not remove it.

| # | Title                       | Command                                                                                  | Mode | Capture file               | Notes                                                |
|---|-----------------------------|------------------------------------------------------------------------------------------|------|----------------------------|------------------------------------------------------|
| 1 | clawctl version             | `clawctl --version`                                                                      | LIVE | `01-version.txt`           | Fixed opener — do not remove                         |
| 2 | Initialize clawrium service | `clawctl service init`                                                                   | LIVE | `02-service-init.txt`      | Idempotent on a host that's already initialized      |
| 3 | Register a host             | `clawctl host create wolf.tailf7742d.ts.net --user xclm --alias wolf-i`                  | LIVE | `03-host-create.txt`       | wolf-i already registered → alias collision; capture the real error/no-op output. Tailscale name to be masked before recording. |
| 4 | Install the hermes agent    | `clawctl agent create quickstart-demo --type hermes --host wolf-i`                       | LIVE | `04-agent-create.txt`      | Real Ansible install. Long output expected.          |
| 5 | Configure the agent         | `clawctl agent configure quickstart-demo --stage providers --provider clawrium-gtm-litellm` | LIVE | `05-agent-configure.txt`   | Non-interactive (verified — `--stage providers --provider` accepted) |
| 6 | Check fleet status          | `clawctl agent get`                                                                      | LIVE | `06-agent-get.txt`         | Confirms `quickstart-demo` row is `ready`           |
| 7 | Chat with the agent         | `clawctl agent chat quickstart-demo` + single prompt "hello, what model are you?" + `Ctrl+D` | LIVE | `07-agent-chat.txt`        | Interactive TUI. Real API call to clawrium-gtm-litellm. |

**Mode legend**

- `replay` — tape executes `cat docs/demos/quickstart-onboarding/outputs/NN-<slug>.txt`. Deterministic; no infra needed at record time.
- `LIVE`   — tape runs the real command. **This entire demo is LIVE.** Captured outputs in `outputs/` are reference material for stitching/truncation, not replay sources.

## Narration (optional, for YouTube voiceover)

Per-scene script. Keep each beat to one or two sentences so timing matches the on-screen `Sleep`.

- Scene 1: "Running clawctl version X.Y.Z — everything you see in the rest of this demo was recorded against this release."
- Scene 2: "First, initialize the clawrium service. This sets up the config directory and validates ansible and ssh are available."
- Scene 3: "Next, register the host you want to deploy agents to. We're using wolf-i, a machine already on my home network."
- Scene 4: "Now install a hermes agent on wolf-i. Clawrium uses ansible under the hood, so this runs a real install playbook end-to-end."
- Scene 5: "Configure the agent — attach a model provider so it can actually answer prompts. We're using a litellm-backed provider already in the secret store."
- Scene 6: "Check fleet status. The new quickstart-demo agent should appear as ready."
- Scene 7: "Finally, chat with it. One prompt in, one response out — clawrium just routed the request through the configured provider."

## Re-capture cadence

Captured outputs drift from the real CLI when output format or columns change. Re-run capture:

- Before each release tag.
- After any change touching CLI output formatting (Rich tables, column order, status strings).
- When the demo is reshot for a major version.

## Open risks (acknowledged 2026-06-18)

1. ~~`agent configure` non-interactive flag may not exist~~ → **resolved**: `--stage providers --provider <name>` is supported.
2. wolf-i already runs 5 hermes agents (espresso, clawrium-triage, clawrium-gtm, clawrium-exec, clawrium-maurice) + 1 openclaw (wolf-i) + 1 zeroclaw (clawrium-d01). Scene 6's `agent get` will show the full fleet; user will truncate the recording to focus on the new row.
3. `quickstart-demo` agent persists after recording. User will remove via `clawctl agent remove quickstart-demo` post-demo (out of skill scope).
4. Scene 3 (`host create` against an already-registered alias) will produce a real error or no-op message — captured as-is. The Tailscale hostname `wolf.tailf7742d.ts.net` will need to be masked/replaced in the captured output before the tape generation step if the recording is going public.

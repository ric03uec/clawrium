# clawrium-gtm — Change Log

Tracks every change to the clawrium-gtm agent (charter, profiles, skills,
templates, model bindings, host bindings) and every file created in support
of those changes. Newest entries on top.

Each entry follows:

```
## YYYY-MM-DD — <short title>
- **Why**: <reason>
- **Changes**:
  - <bullet>
- **Files created/modified**:
  - <path>
- **Validation**:
  - <bullet>
```

---

## 2026-06-14 — Model swap to Qwen3-Next + reviewer SOUL rewrite + long-form blog format

- **Why**: Switch off ollama-hosted qwen3/gemma toward a single vLLM
  backbone (Qwen3-Next-80B-A3B-Instruct-FP8 behind a LiteLLM proxy
  on `inx`), shed the noise that was making the reviewer profile
  unusable, and prove the pipeline can produce a 1.5-week, 1k–1.2k
  word blog post end-to-end. PR #703 updated twice today through
  the new stack to validate.
- **Changes**:

  ### Infrastructure / model swap
  - On `inx` (DGX Spark, GB10): replaced the
    `qwen3-next-80b-a3b-thinking-fp8` vLLM container with
    `qwen3-next-80b-a3b-instruct-fp8` per the
    `system/tasks/002-2026-06-14-01-qwen3-next-instruct-swap.md`
    plan. vLLM flags: `--enable-auto-tool-choice
    --tool-call-parser hermes --max-model-len 65536
    --gpu-memory-utilization 0.80`. Tool calling now lands reliably
    under `tool_choice: "auto"` — closes the
    Thinking-variant under-emission bug (vLLM #39056).
  - **Diagnosis trail (for the next person)**: the Thinking variant
    reasons about tool calls inside `<think>...</think>` and then
    emits nothing after `</think>`, producing
    `tool_calls: null` + `content: ""`. We tried
    `--tool-call-parser qwen3_xml` and `tool_choice: required`
    workarounds; required works for monomorphic profiles
    (sources) but breaks mixed-mode profiles on text-only
    turns. The Instruct variant has no `<think>` block, so the
    failure mode does not apply. Sources verified:
    `https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`,
    `https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-Next.html`.
  - clawctl: detached `clawrium-gtm-qwen3-64k`,
    `clawrium-gtm-writer-gemma4`, `clawrium-gtm-reviewer-gemma4`
    from `clawrium-gtm`. Created new provider
    `clawrium-gtm-litellm` (type=litellm, endpoint
    `http://192.168.1.17:4000`, default model `writer`). Attached
    `--role primary`. `agent sync` clean (1 written, 1 unchanged,
    drift=0). No GH_TOKEN safety-gate this round.
  - LiteLLM model_list (rendered by ansible from
    `system/hosts/inx/vllm/models/qwen3-next-80b-a3b-instruct-fp8.yml`'s
    `virtual_models:` block) exposes three aliases routing to the
    same backbone: `writer`, `reviewer`, `sources`. (Plus
    `qwen3-4b-instruct` from a separate container, unused by gtm.)
    `enable_thinking: false` on all three is a structural no-op
    on Instruct (no thinking mode to toggle) — kept only because
    the `litellm/config.yaml.j2` template requires a non-empty
    `chat_template_kwargs` dict per virtual model.

  ### Profile config rebinds
  - All 3 host distributions' `config.yaml` updated to point at
    LiteLLM (`base_url: http://192.168.1.17:4000/v1`) with the
    bearer key inline (`api_key: sk-...`), `default:` set to the
    correct alias per profile. Snapshot `.snapshots/2026-06-14T053058Z-pre-litellm-swap.tgz`.
    `profile update --force-config -y` for all 3 profiles. SSH-direct
    smoke per profile green (writer/sources/reviewer each return one
    clean sentence). Writer route confirmed working through hermes
    after vLLM was restarted with the missing `--enable-auto-tool-choice`
    / `--tool-call-parser hermes` flags (initial smoke failed with
    "auto tool choice requires ... to be set").

  ### Validation Metrics block — removed from SOUL + SKILL (issue #704 data not available)
  - Snapshot `.snapshots/2026-06-14T200311Z-pre-validation-metrics-removal.tgz`.
  - `gtm-writer/SOUL.md`: removed "A required `## Validation Metrics`
    block" constraint (lines 118–122) + deleted the dedicated
    "Validation Metrics block (added 2026-06-12)" section
    (lines 155–187). 253 → 213 lines. sha `8240c278…`.
  - `gtm-reviewer/SOUL.md`: removed structural rules 7 (V Metrics
    presence) and 8 (no outro after V Metrics); reworded rule 9 to
    drop "EXCLUDING the Validation Metrics block" from the word
    count check; renumbered 10 → 9. 156 → 149 lines. sha `059e2299…`.
  - `gtm-writer/skills/clawrium-blog-pipeline/SKILL.md`: removed
    the trailing "The `## Validation Metrics` block lives in the
    blog post itself, NOT in the PR body" sentence. 243 → 242
    lines. sha `d4811473…`.

  ### Toolset pruning per profile (token-budget hygiene)
  - Discovered while debugging the reviewer's context cap that
    skills are **lazy-loaded** (~3K tokens for the L0 catalog, not
    a per-skill eager load) per hermes docs at
    `https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/`,
    but **toolsets are eagerly defined** in the system prompt. Each
    enabled toolset adds 200–500 tokens of tool-definition JSON.
  - Disabled the following on all 3 profiles via
    `hermes -p <profile> tools disable …`:
    `web`, `browser`, `code_execution`, `vision`, `image_gen`,
    `tts`, `session_search`, `delegation`, `cronjob`,
    `computer_use`. Also disabled `skills` on reviewer (it has
    0 skills installed).
  - Kept on all 3: `file`, `terminal`, `todo`, `memory`, `clarify`,
    `messaging`. Plus `skills` on writer + sources.
  - Estimated savings: 2–5K tokens per request, every request.

  ### Reviewer SOUL — 3-dimension rewrite + max 5 block-level edits
  - Snapshot `.snapshots/2026-06-14T214451Z-pre-reviewer-3dim.tgz`.
  - Dropped ICP-FIT and NOVELTY dimensions; reviewer now scores
    only **CLARITY**, **TECHNICAL**, **STRUCTURE**.
  - Edits cap at **5, block-level only** (no line numbers,
    no per-sentence critique). Structural-template violations
    collapse into AT MOST ONE edit covering the whole class.
  - Banned phrases collapse into ONE edit if any present.
  - Output contract simplified to `## Scores / ## Edits / ## VERDICT`.
  - Explicit "after `write_file` succeeds, I stop. I do not iterate,
    re-read, or refine." 149 → ~110 lines. sha `06e6bc96…`.
  - Hermes `agent.max_turns: 30` set on reviewer profile (was 90)
    via `hermes -p gtm-reviewer config set agent.max_turns 30`.

  ### Long-form blog format — 280–400 → 1000–1200 words
  - Writer SOUL line 118 updated: `Total word count 1000–1200
    across all ## blocks`. sha `82676dfa…`.
  - Reviewer SOUL structural rule updated: `Body word count
    1000–1200`. sha `a28032e5…`.
  - Snapshot `.snapshots/2026-06-14T220147Z-pre-1k-words.tgz`.
  - Writer `agent.max_turns: 50` (was 90 → 30 implicit, now 50).
  - Sources window broadened: 2026-06-08..06-14 → **2026-06-03..06-14**.

  ### Pipeline runs through the new stack
  - **First run (1-week, 280–400 word format)**: sources 1m 38s
    (6 tools, 59-line sources.md); writer 1m 3s (5 tools, 571
    words); reviewer 31s (6 tool calls!) producing clean 3-dim
    review with VERDICT REVISE; writer round-2 3m 45s (19 tools,
    465 words) applying 5 reviewer edits.
  - **Final ship to PR #703**: commit `29baa60` `blog: regenerate
    via Qwen3-Next-80B-A3B-Instruct-FP8 pipeline`. Local
    Docusaurus build green; CI checks re-queued. Replaces iter6
    content with the new 5-block 465-word post.
  - **Second run (1.5-week, 1000–1200 word format)**: sources
    12m 33s (6 tools, 46KB sources.md covering ~80 PRs +
    issues); writer hit 90/90 iter budget on first attempt
    (incremental-patch behavior), succeeded on second attempt
    after adding "single write_file call, no patching" directive
    to prompt + bumping `agent.max_turns: 50` → 1003 words.
    Reviewer **blew turn budget twice** through hermes profile
    (30/30 then 50/50 with 101 tool calls, both NOT_WRITTEN);
    fell back to **direct LiteLLM `reviewer` route**, which
    produced a clean review in 30s with same SOUL behavior.
    Edits applied manually (2 real of 5 proposed; 3 dropped:
    2 reviewer self-retractions, 1 over-strict tag rule, 1 moot
    since Related: link already present).
  - **Final ship to PR #703**: commit `6dd5302` `blog: expand to
    1.5-week recap (1000-1200 word format)`. 1012 words, 6 ##
    blocks. Local Docusaurus build green.

- **Files created/modified**:
  - On host (`/home/clawrium-gtm/.hermes/distributions/`):
    `gtm-writer/SOUL.md`, `gtm-writer/config.yaml`,
    `gtm-writer/skills/clawrium-blog-pipeline/SKILL.md`,
    `gtm-reviewer/SOUL.md`, `gtm-reviewer/config.yaml`,
    `gtm-sources/config.yaml`. Plus profile-level
    `gtm-reviewer/config.yaml` (`agent.max_turns: 30`) and
    `gtm-writer/config.yaml` (`agent.max_turns: 50`).
  - On host (`.snapshots/`): four `.tgz` snapshots listed above.
  - In `ric03uec/system` repo:
    `tasks/002-2026-06-14-01-qwen3-next-instruct-swap.md` (the
    swap plan handed to the system manager; PR
    [#9](https://github.com/ric03uec/system/pull/9) shipped).
    `hosts/inx/vllm/models/qwen3-next-80b-a3b-instruct-fp8.yml`
    added; `hosts/inx/ansible/vllm-setup.yml`
    `vllm_active_models` updated.
  - In `ric03uec/clawrium` repo:
    `website/blog/2026-06-12-declarative-fleets-and-agent-expansion.md`
    rewritten twice (PR #703 commits `29baa60` then `6dd5302`).
    `.sdlc/clawrium-gtm/CHANGELOG.md` (this entry).

- **Validation**:
  - vLLM `/v1/models` returns
    `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`.
  - LiteLLM exposes 3 aliases (`writer`, `reviewer`, `sources`)
    plus `qwen3-4b-instruct`. Native `tool_calls` JSON returns
    under `tool_choice: "auto"` on all three (V3 in the swap plan).
  - `clawctl agent provider get --agent clawrium-gtm` shows
    `clawrium-gtm-litellm primary`.
  - `hermes -p gtm-reviewer config show | grep 'Max turns'` →
    `30`. `hermes -p gtm-writer config show | grep 'Max turns'`
    → `50`.
  - sha256 of all 6 host files match local canonical post-push.
  - PR #703 build check green after both commits.

- **Open issues carried forward (D3 / future backlog)**:
  1. **Reviewer hermes profile doesn't scale past ~500-word
     drafts + ~10K-token sources.md.** Spirals into 100+ tool
     calls without writing review-1.md. Workaround: bypass to
     direct LiteLLM `reviewer` route (lean prompt, ~30s,
     produces clean output). Root cause: model ignores SOUL's
     "one read, then write" directive when context grows.
     Real fix candidates: split reviewer SKILL into LiteLLM-direct
     shape (no hermes session loop); or precompute fact-grounding
     outside the model.
  2. **Writer needs an explicit "single write_file call, no
     patching" directive in prompt OR SOUL/SKILL** to avoid
     spiraling into incremental edits and hitting iter budget on
     long-form drafts. Bake into writer SKILL.md for the 1k-word
     path.
  3. **HOST-ONLY-DISTRIBUTIONS.md canonical bodies are now
     drifted** from the on-host state (V Metrics removed,
     SOUL/SKILL rewritten). Doc-sync pass needed before next
     bootstrap-from-scratch attempt.
  4. **Reviewer over-strict on tag allowlist** — flagged
     `[release]` as needing `announcements` even though `release`
     is in the SOUL's allowlist. Minor tuning needed in reviewer
     SOUL or test.
  5. **Writer SOUL drift not yet captured**: the writer's
    `clawrium-blog-pipeline` SKILL.md still references the
    5-round write/review loop that no longer fits the
    1k-word format. SKILL update deferred.

## 2026-06-10 — Phase A foundations executed (per EXECUTION-PLAN.md)

- **Why**: Begin building the daily blog pipeline. Phase A stands up the
  new model provider and the on-host working clone without changing
  agent behavior yet.
- **Changes**:
  - **0.1** clawctl 26.6.1 confirmed.
  - **0.2** clawrium-gtm reachable, hermes 2026.5.29.2 on wolf-i.
  - **0.3** Pre-state snapshot
    `snapshots/2026-06-11T041140Z-pre.txt` (3021 B).
  - **A1** Confirmed `excalidraw` skill present, status `enabled`,
    source `builtin`.
  - **A2** Created provider `clawrium-gtm-qwen3-64k` (type=ollama,
    model=qwen3:30b-64k, endpoint=http://192.168.1.17:11434). 22
    models visible on endpoint including `qwen3:30b-64k`.
  - **A3** Attached `clawrium-gtm-qwen3-64k` to clawrium-gtm with
    `--role curator`. `clm-openrouter` remains primary.
    `agent sync` completed: 1 written, 1 unchanged, drift=0, 7s.
    `agent provider get --agent clawrium-gtm` shows both
    attachments. (Unrelated warning surfaced about "registry record
    missing for hermes" — pre-existing; sync succeeded.)
  - **A4** Asked the agent via `chat -q` to bootstrap its working
    repo. Agent ran the idempotent
    `if [ -d $HOME/clawrium/.git ]; then ... pull --ff-only;
    else git clone https://github.com/ric03uec/clawrium $HOME/clawrium; fi`
    block. Repo cloned to `/home/clawrium-gtm/clawrium`,
    `AGENTS.md` confirmed, `BOOTSTRAP_OK` printed.
    `GITHUB_TOKEN` from `clawrium-github` integration was in scope —
    no extra plumbing needed.
  - **A5** Post-Phase-A snapshot
    `snapshots/2026-06-11T041327Z-post-phaseA.txt` (3340 B).
    Diff vs pre shows ONLY the new provider attachment and the new
    provider in the registry list (plus column-width reformatting).
- **Files created/modified**:
  - `.sdlc/clawrium-gtm/CHECKLIST.md` (new)
  - `.sdlc/clawrium-gtm/snapshots/2026-06-11T041140Z-pre.txt` (new)
  - `.sdlc/clawrium-gtm/snapshots/2026-06-11T041327Z-post-phaseA.txt` (new)
- **Validation**:
  - All 0.1–A5 pass criteria from EXECUTION-PLAN.md met.
  - A4 burn-in clone took 2.7s; future runs will take the
    `pull --ff-only` branch.

## 2026-06-10 — Phase B B0–B3 green (host-only distributions installed)

- **Why**: User decided distributions for `gtm-writer` and
  `gtm-reviewer` should not be committed to git. I2 invariant
  suspended for these two profiles only. Distributions live on host
  under `/home/clawrium-gtm/.hermes/distributions/<name>/`. New doc
  `HOST-ONLY-DISTRIBUTIONS.md` is the canonical source for file
  bodies + bootstrap.
- **Changes**:
  - **B0** Agent created `/home/clawrium-gtm/.hermes/distributions/{gtm-writer/skills,gtm-reviewer/skills,.snapshots}/`
    via chat-driven `mkdir -p`.
  - **B1** Wrote 3 files for `gtm-writer`:
    - `distribution.yaml` (244 B, sha256 `46cba865…`)
    - `config.yaml` (98 B, sha256 `629eda8e…`)
    - `SOUL.md` (2890 B, sha256 `38aa1b9d…`, 78 lines)
  - **B2** Wrote 3 files for `gtm-reviewer`:
    - `distribution.yaml` (176 B, sha256 `ea2b50c8…`)
    - `config.yaml` (98 B, sha256 `629eda8e…`, identical to writer)
    - `SOUL.md` (2303 B, sha256 `7a74891f…`, 67 lines)
    All 6 sha256s computed locally first, then verified byte-exact
    on host.
  - **B3.1** `profile install /home/clawrium-gtm/.hermes/distributions/gtm-writer --alias -y`
    → installed `gtm-writer` v0.1.0, alias `gtm-writer`,
    model `qwen3:30b-64k`.
  - **B3.2** Same for `gtm-reviewer` v0.1.0, alias `gtm-reviewer`.
  - `profile list` confirms: `default` (running, openrouter→qwen3
    swap from prior step holds), `gtm-writer` (stopped), `gtm-reviewer`
    (stopped). Stopped is expected — per-profile gateways start on
    first invocation.
- **Transport deviation (documented in HOST-ONLY-DISTRIBUTIONS.md)**:
  Originally planned chat-driven heredocs. In practice `clawctl agent
  exec` has a hard 120 s timeout and qwen3:30b-64k's first-token
  latency for a chat reply routinely exceeds that. The shell command
  on host completed in 0.1 s every time; only the agent's reply was
  late. Switched to operator-side SCP+SSH+sudo using
  `~/.config/clawrium/keys/wolf-i/xclm_ed25519` (the clawctl host
  key). `xclm` has passwordless sudo to `clawrium-gtm`. Install
  still goes through `clawctl agent exec ... profile install`
  (agent-owned).
- **Files created/modified**:
  - `.sdlc/clawrium-gtm/HOST-ONLY-DISTRIBUTIONS.md` (new — canonical
    bodies for all 6 files, bootstrap-from-scratch procedure,
    inspection commands, trade-off table)
  - `.sdlc/clawrium-gtm/BLOG-PIPELINE-PLAN.md` (I2 suspended with
    forward link)
  - `.sdlc/clawrium-gtm/EXECUTION-PLAN.md` (§B rewritten for
    host-only flow; original git-based B1–B5 marked superseded)
  - `.sdlc/clawrium-gtm/CHECKLIST.md` (B-row checkmarks + transport
    deviation note)
- **Validation**:
  - `find ... -type f -printf "%p %s\n"`: 6 files present with non-zero size.
  - `sha256sum` on host: all 6 match canonical bodies in
    HOST-ONLY-DISTRIBUTIONS.md.
  - `profile list`: both distributions show
    `<name>@0.1.0` under Distribution column.
- **Deferred**: B4 (iteration sanity), B5 (smoke per profile). Both
  need a long chat round-trip; will likely fail the 120 s timeout.
  Approach for B5: invoke with `--resume` or short prompts; or accept
  one-shot chat with a streamed reply that may time out at the wrapper
  while completing on host. Approach for B4: do the SOUL edit
  operator-side via SSH, then `profile update`, then `profile show`
  (which doesn't hit the model and won't time out).

## 2026-06-10 — Phase B B4–B5 green (iteration + smoke verified)

- **Why**: Prove the iteration loop and confirm both profiles
  actually speak in-persona before moving to Phase C.
- **B4 — iteration sanity (operator-side SSH edit + `profile update`)**:
  - Pre-snapshot:
    `.snapshots/2026-06-11T050344Z-pre-B4.tgz` (writer+reviewer trees).
  - SSH-appended `<!-- iteration-probe 2026-06-10 -->` to
    `distributions/gtm-writer/SOUL.md`.
  - `clawctl agent exec clawrium-gtm -- profile update gtm-writer -y`
    → `✓ Updated 'gtm-writer' → v0.1.0`.
  - SSH-confirmed probe present in
    `profiles/gtm-writer/SOUL.md` (the *installed* path).
  - SSH-removed probe; sha256 of distribution SOUL back to canonical
    `38aa1b9d…` (matches HOST-ONLY-DISTRIBUTIONS.md byte-for-byte).
  - Second `profile update` propagated removal; grep returns 0.
  - **U4 resolved**: `hermes profile update` does **not** require a
    `version:` bump in `distribution.yaml`. The plan's caution to
    bump 0.1.0 → 0.1.1 on every iteration is now known to be
    unnecessary.
- **B5 — smoke each profile (direct SSH, bypassing clawctl timeout)**:
  - Approach: SSH to wolf-i as `xclm`, `sudo -n -u clawrium-gtm
    bash -lc "cd /home/clawrium-gtm && /home/clawrium-gtm/.local/bin/hermes
    -p <profile> chat -q '...'"`. Two snags on the path that were
    fixed in-flight:
    1. Sudo's sanitized PATH drops `~/.local/bin` → use the full
       `/home/clawrium-gtm/.local/bin/hermes` path.
    2. Hermes tries to read the cwd's `.git` directory; default cwd
       after sudo is `/home/xclm` which clawrium-gtm can't access →
       `cd /home/clawrium-gtm` first.
  - **gtm-writer smoke**: "Introduce yourself in 2 sentences. Mention
    your audience and your working directory." Reply (20 s): mentions
    homelabbers + team leads + AI experimenters AND
    `/home/clawrium-gtm/clawrium`. SOUL is loaded.
  - **gtm-reviewer smoke**: "Introduce yourself ... how you score
    drafts and how you behave by default." Reply (25 s): names the
    5 dimensions (Clarity, Technical, ICP-Fit, Novelty, Structure)
    AND the REVISE default AND banned marketing terms. Rubric is
    loaded.
- **Transport deviation expansion**: the existing deviation
  ("chat heredoc → SSH+sudo for byte transport") now extends to any
  step that needs the model to respond ("chat-driven prompts →
  direct SSH `hermes ... chat -q`"). Documented in CHECKLIST.md
  callout; will fold into HOST-ONLY-DISTRIBUTIONS.md and EXECUTION-PLAN.md
  in a follow-up doc pass.
- **Validation**:
  - All B4 pass criteria met.
  - B5 both profiles named all required SOUL artifacts unprompted.
  - `clawctl agent provider get --agent clawrium-gtm` still shows
    `clawrium-gtm-qwen3-64k primary` — provider state unchanged by
    Phase B.

## 2026-06-10 — Phase C green: blog-pipeline skill + dry-run loop

- **Why**: Build and prove the daily blog pipeline skill the writer
  profile will execute. Phase C was reframed under the host-only
  philosophy from Phase B:
  - C1 (edit repo `templates/blog-post.md`) skipped — output
    contract is already in writer SOUL.md, and the procedural loop
    moves into a single self-contained SKILL.md. No repo template
    edit, no commit.
  - C2 authors `clawrium-blog-pipeline/SKILL.md` directly under the
    writer distribution on host.
  - C3 dry-runs one writer→reviewer pass.
- **C2 — clawrium-blog-pipeline SKILL.md**:
  - Path: `~/.hermes/distributions/gtm-writer/skills/clawrium-blog-pipeline/SKILL.md`.
  - Final body: 215 lines, sha256 `24a377f8…`. Frontmatter follows
    hermes skill convention (modeled on bundled gtm-env skill —
    `name`, `version`, `license`, `author`, `platforms`,
    `prerequisites`, `metadata.hermes.tags`).
  - Procedure: setup → inventory 24h merges via `gh pr list` →
    empty-batch shortcut (chore/docs/style/refactor/test/ci-only) →
    rounds 1..5 (write/review alternation) → round-counter gate →
    ship to `~/clawrium/website/blog/<date>-<slug>.md` → PR with
    `type:blog` label, body = concatenated transcripts.
  - Installed via `clawctl agent exec ... profile update gtm-writer
    -y`; `hermes -p gtm-writer skills list` shows
    `clawrium-blog-pipeline | local | enabled`.
- **C3 — dry-run, first attempt (revealed a real problem)**:
  - Writer wrote round-1.md with 0 tool calls (claimed to save but
    didn't); had to add `-t file,terminal` to force tool use.
  - Even with `-t`, the reviewer ran on round-1.md but hallucinated
    a critique against content NOT in the draft (cited
    `game-changing`, `leverage`, `git clone .../gtm-writer.git`,
    `next-generation` title — none present in the actual draft).
    Reviewer never read the source file.
  - Mechanical gates (frontmatter present, rubric present, VERDICT
    present, banned phrases absent) all passed, but the semantic
    loop was broken: the loop would produce nonsense critiques and
    therefore nonsense revisions.
- **Fix applied (option 3 + option 4 from the surfaced choices)**:
  - **Reviewer model swap**: `qwen3:30b-64k` → `qwen3-coder:30b-128k`.
    Required `profile update gtm-reviewer --force-config -y`
    because `profile update` preserves `config.yaml` by default.
    Writer kept on `qwen3:30b-64k`.
  - **Reviewer SOUL hardened**: added a "My procedure (always, in
    this exact order)" section that mandates step 1 = read_file,
    step 2 = verify it parsed, step 3 = score with **real**
    substring quotes, step 4 = write critique. Banned phrases now
    only flagged when actually present in the read file.
  - **SKILL.md prompts rewritten**: round-1 reviewer prompt is now
    "Step 1: Use read_file to read $WS/round-N.md. Step 2: Score
    that exact content. Every numbered edit MUST quote a real
    substring. Step 3: Write critique." Same shape for rounds 2..5
    writer prompts (read prior draft + prior review first, then
    revise).
  - 3 file sha256s on host after fix:
    - `gtm-reviewer/config.yaml` `84fa7e38…`
    - `gtm-reviewer/SOUL.md` `4357f82c…`
    - `gtm-writer/skills/clawrium-blog-pipeline/SKILL.md` `24a377f8…`
- **C3 — dry-run, second attempt (green)**:
  - Writer round-1: 4 tool calls (read CHANGELOG.md, then wrote the
    draft). Body 159 words (below SOUL's 250 floor — flagged but
    not blocking for C3 mechanical gates).
  - Reviewer round-1: **24 tool calls**, properly read round-1.md,
    cited real line numbers and real substrings.
    - Scores: CLARITY 4/5, TECHNICAL 2/5, ICP-FIT 4/5, NOVELTY 3/5,
      STRUCTURE 5/5; VERDICT REVISE.
    - Caught a real writer error: cited `clawctl provider create`
      and corrected to `clawctl provider registry create`.
  - All mechanical C3 pass criteria met.
- **Side observations carried into Phase D tuning**:
  - Writer 159 words < 250 floor: rely on reviewer's STRUCTURE
    rubric to catch and force a longer rewrite in subsequent rounds;
    tighten writer SOUL if not enough.
  - Reviewer wrote replacement copy in `EDITS` (`→ "<new sentence>"`)
    even though SOUL says "I do not write replacement copy". Minor
    SOUL drift to track; not blocking the loop.
- **Files created/modified**:
  - On host:
    `~/.hermes/distributions/gtm-writer/skills/clawrium-blog-pipeline/SKILL.md`
    (new); `gtm-reviewer/SOUL.md` (overwritten);
    `gtm-reviewer/config.yaml` (overwritten);
    `.snapshots/2026-06-11T051407Z-pre-C2.tgz` (new);
    `.snapshots/2026-06-11T052836Z-pre-C3-fix.tgz` (new).
  - In repo: `.sdlc/clawrium-gtm/CHECKLIST.md` (Phase C row updates);
    `.sdlc/clawrium-gtm/CHANGELOG.md` (this entry).
  - HOST-ONLY-DISTRIBUTIONS.md canonical bodies for reviewer
    config.yaml + SOUL.md and the new SKILL.md are **not yet
    updated** — outstanding doc debt; will fold into a single
    doc-sync pass before D1.
- **Validation**:
  - On-host sha256 of all 3 updated files matches local canonical.
  - `profile list` shows reviewer model `qwen3-coder:30b-128k`.
  - `hermes skills list` (gtm-writer) shows
    `clawrium-blog-pipeline | local | enabled`.
  - Dry-run loop produces structurally-correct AND semantically-grounded
    round-1.md + review-1.md.

## 2026-06-12 — §D2 mid-flight: gtm-sources profile installed, writer/reviewer SOULs hardened

- **Why**: After three D1 burn-ins (v1/v2/v3) the writer kept
  fabricating claims even with prompt tightening + reviewer model
  swap. Root cause: the writer had `gh` + general reasoning; when
  source content was sparse it invented. D2 collapses the invention
  surface by:
  1. Introducing a third profile `gtm-sources` whose only job is
     gather-and-write-to-file (no prose, no judgment).
  2. Hardening writer + reviewer SOULs with a "My grounding" section
     that bans `gh` calls and requires every factual claim to trace
     to a verbatim block in `sources.md`.
  Full design in [`D2-PLAN.md`](D2-PLAN.md).
- **Changes (D2.0 → D2.8)**:
  - **D2.0**: confirmed providers + profiles healthy; archived
    `workspace/blog/2026-06-11` → `…-final-v3` for diagnostic state.
  - **D2.1**: authored 4 local files for `gtm-sources` distribution
    (distribution.yaml 7L sha `c50dfacb…`, config.yaml 4L sha
    `84fa7e38…` byte-identical to reviewer config, SOUL.md 83L sha
    `837deb6a…`, skill SKILL.md 89L sha `0c644c4a…`).
  - **D2.2**: `mkdir -p` on host for distribution + skill dir,
    pushed 4 files via SCP+sudo, all 4 sha256s match byte-for-byte
    against local canonical.
  - **D2.3**: `profile install gtm-sources --alias -y` succeeded;
    profile list shows `gtm-sources @ qwen3-coder:30b-128k` with
    alias `gtm-sources` and `Distribution: gtm-sources@0.1.0`.
  - **D2.4**: SSH-direct smoke ("introduce yourself") — reply
    correctly mentions gathering, closed issues + merged PRs, and
    canonical structure. SOUL loaded.
  - **D2.5/D2.6**: edited local copies of writer and reviewer SOULs
    to insert a `## My grounding (added 2026-06-12)` section. New
    shas: writer `78312fbf…` (was `38aa1b9d…`, +14 lines),
    reviewer `2eb9cbd5…` (was `4357f82c…`, +15 lines).
  - **D2.7**: pre-change snapshot
    `.snapshots/<ts>-pre-D2.tgz` (writer+reviewer+sources); pushed
    both SOULs via SCP+sudo; sha256s match; `profile update
    gtm-writer -y` + `profile update gtm-reviewer -y` both green;
    `grep -c 'My grounding'` on installed SOULs returns 1 in each.
    Default config preservation worked — no `--force-config`
    needed since only SOUL changed.
  - **D2.8 (in progress)**: updated
    `HOST-ONLY-DISTRIBUTIONS.md` — directory tree shows the new
    profile, canonical bodies added for 4 new files + grounding
    sections inserted in writer/reviewer canonical bodies,
    bootstrap-from-scratch list updated to install all 3 profiles.
- **Files modified**:
  - `.sdlc/clawrium-gtm/D2-PLAN.md` (new, 608 lines)
  - `.sdlc/clawrium-gtm/HOST-ONLY-DISTRIBUTIONS.md` (canonical bodies
    + bootstrap list extended for `gtm-sources`)
  - `.sdlc/clawrium-gtm/CHECKLIST.md` (D2 section added with 17
    checkboxes; D2.0–D2.7 marked green)
  - `.sdlc/clawrium-gtm/CHANGELOG.md` (this entry)
  - On host: 4 new files under
    `~/.hermes/distributions/gtm-sources/`; 2 modified SOULs
    overwritten via SCP+sudo, then propagated to installed profiles
    by `profile update`.
- **Validation**:
  - `agent provider get`: unchanged (single primary, qwen3:30b-64k).
  - `profile list`: 4 profiles total (default + 3 gtm-*).
  - sha256 of every on-host file matches local canonical.
  - Grounding section present in installed profile SOULs.
- **Pending (D2.9–D2.16)**: clean workspace, invoke each profile
  sequentially via `clawctl agent exec`, show output to user at
  three gates, user decides ship/hold/iterate at D2.16.

### Investigation note (not a bug, doc-only): gtm-sources gh auth dance

During D2.10 the gtm-sources profile failed to call `gh` from its
terminal tool until we (a) added `GH_TOKEN` to `~/.hermes/.env`,
(b) restarted the agent, AND (c) prefixed every `gh` call with
`HOME=/home/clawrium-gtm`. Direct SSH as `clawrium-gtm` runs `gh`
fine without any of this — `gh auth status` shows `✓ Logged in to
github.com account ric03uec (/home/clawrium-gtm/.config/gh/hosts.yml)`.

Per devashish: "GH command is working fine for all other profiles. I
do not know why it is not working from this profile. There has to be
some configuration issue. It is not a bug, it is a config gap." Not
filing a GitHub issue; logging here for future investigation. Likely
candidates: profile-specific MCP/tool-shim config, hermes terminal
tool env-passthrough rules, or interaction with the `tirith` security
scanner ("enabled but not available — command scanning will use
pattern matching only") which may have been pattern-blocking
unprefixed gh calls. Working prompt template: prefix every `gh` call
with `HOME=/home/clawrium-gtm`.

Final sources.md (D2.10/D2.11 result): 301 lines, captures issue
#694 + closing PR #696 with full bodies (incl. PR's 9 Callouts and
4-iteration ATX review summary). Skipped non-linked PRs per SOUL.
Minor format issue: `gh pr diff --stat` block has `\n` literal
instead of newlines (JSON-escape leakage); data still usable for
writer. Logged for SKILL.md tightening before D3.

## 2026-06-12 — First end-to-end PR shipped + skill labeled-PR update

- **Why**: Close the D2 loop by shipping a real PR through the
  pipeline. Then update the `clawrium-blog-pipeline` skill so future
  shipped PRs carry the right provenance labels (so the project can
  filter/sort agent-shipped vs human-shipped work later).
- **Pipeline run** (manual, no cron):
  - **gtm-sources** (`qwen3-coder:30b-128k`) → 305-line sources.md
    for window 2026-06-10..2026-06-12 (issue #694 + closing PR #696).
  - **gtm-writer R1** (`gemma4:31b`) → 353-word round-1.md. Caught
    the malformed PR URL bug (`/ric03uec/pull/N` missing
    `/clawrium/`) in the Related: line.
  - **gtm-reviewer R1** (qwen3-coder, after a stuck-gemma reviewer
    pass was killed) → TECHNICAL 2/5, flagged the URL bug as edit
    #6. ICP-grounding exception worked: edits #3 and #4 noted that
    "experimenters" / "AI experimenters" are ALLOWED per the new
    SOUL rule.
  - **gtm-writer R2** (gemma) → 353-word round-2.md with URL bug
    fixed in all 4 Related: lines.
  - **gtm-reviewer R2** (qwen3-coder) → CLARITY 5, TECHNICAL 5,
    ICP-FIT 4, NOVELTY 5, STRUCTURE 5. **VERDICT: APPROVED.**
  - **Ship** via gtm-writer chat (SOUL grounding rule scoped to
    drafting; git+gh ship operations explicitly authorized in the
    prompt). Branch `gtm/blog/2026-06-12`, commit `1a414ea`, PR
    [#703](https://github.com/ric03uec/clawrium/pull/703).
- **SOUL changes during this iteration** (loosen ICP rule on both
  writer and reviewer per user direction "at-least-one ICP"):
  - Writer SOUL audience section: "If a sentence wouldn't land with
    all three, I rewrite it" → "Each block must land with at least
    one of these three segments — not all three. … Naming a segment
    explicitly is allowed but not required."
  - Reviewer SOUL grounding section: added "Grounding exception:
    ICP-segment naming" — sentences naming homelabbers/team
    leads/AI experimenters are ALLOWED without source backing
    because they are the writer's authorial overlay, not a fact.
    Reviewer should still strike non-ICP unsourced claims.
  - Snapshot before change: `.snapshots/<ts>-pre-icp-relax.tgz`.
- **Model swap** during the iteration:
  - Created two clawctl ollama providers:
    `clawrium-gtm-writer-gemma4` (model gemma4:31b)
    and `clawrium-gtm-reviewer-gemma4` (same).
  - Attached both to clawrium-gtm (aux roles: curator + compression).
  - `agent sync` blocked by the .env GH_TOKEN safety gate; skipped
    sync since attachments are metadata and profile config.yaml is
    the real binding.
  - `gtm-writer/config.yaml` → `gemma4:31b` (writer stays on this).
  - `gtm-reviewer/config.yaml` → `gemma4:31b` initially, then
    reverted to `qwen3-coder:30b-128k` because gemma reviewer
    hung (~17 min) on the second round.
  - Profile updates used `--force-config` for both.
- **Label provisioning + skill update**:
  - Confirmed `agent-created` label exists (color B0E0E6).
  - Created `agent:clawrium-gtm` label (color 7FFFD4).
  - Updated `clawrium-blog-pipeline/SKILL.md` PR-create command:
    was `gh pr create --label type:blog ...`, now adds
    `--label agent-created --label agent:clawrium-gtm`. New skill
    sha256 `47a69949…` (was `24a377f8…`), 222 lines (was 215).
  - HOST-ONLY-DISTRIBUTIONS.md canonical body updated to the new
    222-line body; recovery sha verified byte-exact via awk extract.
  - Applied all three labels to the already-shipped PR #703
    (`agent-created`, `agent:clawrium-gtm`, `type:blog`).
- **Files modified**:
  - On host:
    `gtm-writer/SOUL.md` (audience section loosened),
    `gtm-reviewer/SOUL.md` (ICP exception added),
    `gtm-writer/config.yaml` (gemma4:31b),
    `gtm-reviewer/config.yaml` (qwen3-coder:30b-128k after revert),
    `gtm-writer/skills/clawrium-blog-pipeline/SKILL.md` (3 labels).
    Snapshots before each major change in `.snapshots/`.
  - Local:
    `.sdlc/clawrium-gtm/HOST-ONLY-DISTRIBUTIONS.md` (new SKILL body,
    label notes, label-flag verbiage),
    `.sdlc/clawrium-gtm/CHANGELOG.md` (this entry).
- **Friction (carry to D3 backlog)**:
  - 120 s `clawctl agent exec` wall on every chat call — pattern:
    submit prompt, expect timeout, SSH-poll for file, kill lingering
    process.
  - Reviewer model trade-off: qwen3-coder fast but no-op edits +
    occasional hallucinated content references; gemma reliable
    quality but slow and sometimes hangs.
  - First-draft PR URL bug (writer dropped `/clawrium/` from PR
    URL) — caught by reviewer but worth pre-flighting in the SOUL.
  - GH_TOKEN safety-gate blocks `agent sync` because of our manual
    .env edit; need a clean reattachment path or an explicit
    "allow keep" affordance.
- **Validation**:
  - PR #703 open, branch `gtm/blog/2026-06-12`, commit `1a414ea`,
    file `website/blog/2026-06-12-organizing-the-providers-experience.md`
    on disk in repo clone.
  - PR labels confirmed via `gh pr view`: agent-created, type:blog,
    agent:clawrium-gtm.
  - awk-extracted SKILL body sha matches host (`47a69949…`).
  - `profile list` confirms writer = gemma4:31b, reviewer =
    qwen3-coder:30b-128k, sources = qwen3-coder:30b-128k.
- **Follow-up — Docusaurus build fix (2026-06-12, same day)**:
  - PR #703's `build` check failed: docusaurus rejected the post
    because `tags: [release]` is not defined in `website/blog/tags.yml`
    (defined tags were `announcements`, `breaking-changes`,
    `release-notes`).
  - Added a new `release:` tag definition to `website/blog/tags.yml`
    on the same branch (commit `9ac79df`).
  - Second build failure: missing `<!-- truncate -->` marker. Added
    after intro (commit `09cb9b8`).
  - Third build failure (pre-existing on `main` since 2026-06-08):
    `<name>` literal in `docs/agent-support/hermes.md:189` inside
    markdown emphasis broke MDX parser. Wrapped in backticks per
    the same pattern used elsewhere in the file (commit `45f062d`).
    Verified local docusaurus build green.
  - PR #703 build: pass ✓

- **2026-06-12 same day — Validation Metrics + blog PR template + publishing SOUL**:
  - **GitHub issue #704 filed**: "atx: expose per-agent model info
    for inclusion in blog Validation Metrics". Labeled
    `agent-created` + `agent:clawrium-gtm`.
  - **`## Validation Metrics` block** appended to the published
    blog post. Constant-shape table: PRs covered, automated review
    iterations, blocking issues resolved (single integer), total
    cost, total time, models used by ATX (currently "_Not exposed
    per agent; see #704_"), models used by gtm pipeline.
  - **`.github/PULL_REQUEST_TEMPLATE/blog.md`** created. Predictable
    shape: Summary, Validation checklist (7 boxes including local
    `npm run build`), full pipeline transcript in 5 `<details>`
    blocks. NO `## Validation Metrics` in PR body — the block lives
    only in the blog post. No robot footer.
  - **PR #703 body** rewritten using the new template. All 7
    checklist boxes ticked.
  - **Writer SOUL v7** (`e91ff924…` → `4156e307…`): new sections
    "Website publishing constraints" (tags allowlist, truncate
    marker, one-H1, MDX angle-bracket escape), "Validation Metrics
    block" (constant-shape table spec), "Local pre-flight"
    (mandatory `npm run build` before ship).
  - **Reviewer SOUL v7** (`f771e69e…` → `f57bc373…`): structural
    template check gains 4 new rules — rule 6 (truncate marker
    presence), rule 7 (Validation Metrics block shape with exact
    row set), rule 9 (word count excludes Validation Metrics
    block), rule 10 (tag allowlist).
  - **SKILL.md v2** (`47a69949…` → `471539d4…`): new mandatory
    "Local Docusaurus pre-flight" step before any git operation;
    git/gh commands updated with `HOME=/home/clawrium-gtm` prefix;
    `git add` now also stages `.github/PULL_REQUEST_TEMPLATE/blog.md`;
    note added that PR body uses the new template and `## Validation
    Metrics` lives only in the blog post.
  - Pre-change snapshot:
    `.snapshots/<ts>-pre-validation-soul.tgz`.
- **Files modified**:
  - On host (distributions): `gtm-writer/SOUL.md`,
    `gtm-reviewer/SOUL.md`,
    `gtm-writer/skills/clawrium-blog-pipeline/SKILL.md`.
  - On PR branch (commit `9e1780e`):
    `website/blog/2026-06-12-organizing-the-providers-experience.md`
    (appended Validation Metrics block),
    `.github/PULL_REQUEST_TEMPLATE/blog.md` (new).
- **Validation**:
  - Local docusaurus build green (worktree at HEAD).
  - PR #703 build pass ✓, macos test pass ✓, ubuntu pending,
    deploy skipped (expected on PR).
  - Issue #704 filed and linked.
  - sha256 of all 3 distribution files match local canonical.

## 2026-06-10 — Doc sync: HOST-ONLY-DISTRIBUTIONS.md canonical bodies

- **Why**: After C3 we updated 3 on-host files (reviewer config.yaml,
  reviewer SOUL.md, writer SKILL.md) but the canonical-bodies
  section in `HOST-ONLY-DISTRIBUTIONS.md` still showed the
  pre-change bodies. That section is the only path to rebuild host
  state from scratch if wolf-i is wiped, so drift there silently
  regresses any restore. Closed the gap before D1.
- **Changes** to `HOST-ONLY-DISTRIBUTIONS.md`:
  - `gtm-reviewer/config.yaml` canonical body updated to model
    `qwen3-coder:30b-128k`. Inline note explains why (C3
    hallucinated-critique fix).
  - `gtm-reviewer/SOUL.md` canonical body replaced with the
    C3-hardened version: adds the "My procedure (always, in this
    exact order)" section that forces `read_file` first and bans
    inventing banned-phrase findings.
  - New section `gtm-writer/skills/clawrium-blog-pipeline/SKILL.md`
    with the full 215-line body inside four-backtick fences (so
    inner triple-backtick code blocks render correctly). Verified
    that extracting the body via `awk '/^\`\`\`\`markdown$/{flag=1;next}
    /^\`\`\`\`$/{flag=0} flag'` produces a file with sha256
    `24a377f8fe23e8bc594521273c817b2d3a670c34418d14ce112fd3b0aca7abe0`
    — same as the on-host file. The doc's "recovery test" claim
    is verifiable, not aspirational.
  - "Bootstrap from scratch" section expanded:
    - explicit file list including the new SKILL.md and its
      `mkdir -p` requirement,
    - note that reviewer model is different from writer model,
    - `profile update gtm-reviewer --force-config -y` step (because
      `profile update` preserves `config.yaml` by default — surprise
      we discovered in C3),
    - smoke command rewritten to SSH-direct (skipping the
      `clawctl agent exec ... chat` 120 s wall).
- **Files modified**:
  - `.sdlc/clawrium-gtm/HOST-ONLY-DISTRIBUTIONS.md`
  - `.sdlc/clawrium-gtm/CHANGELOG.md` (this entry)
- **Validation**:
  - awk-extracted SKILL.md body's sha256 = the host file's sha256
    (`24a377f8…`).
  - All three drifted bodies now match host state.

## 2026-06-10 — Primary provider swap: openrouter → qwen3:30b-64k

- **Why**: User decided the default/primary model should not be
  openrouter for clawrium-gtm. Local model ownership (and consistency
  with the writer/reviewer profile pins coming in Phase B) makes
  `clawrium-gtm-qwen3-64k` the natural primary.
- **Changes**:
  - Detached `clawrium-gtm-qwen3-64k` (was role=curator).
  - Detached `clm-openrouter` (was role=primary). Note: hermes refuses
    to detach primary while aux attachments remain — order matters.
  - Re-attached `clawrium-gtm-qwen3-64k` with `--role primary`.
  - First `agent sync` was rejected by the secrets-safety gate
    (`refusing to sync: rendered body removes host-side secrets
    (.hermes/.env: would remove ['OPENROUTER_API_KEY'])`). Resolved by
    asking the agent (chat-driven) to strip the line from
    `/home/clawrium-gtm/.hermes/.env` (`sed -i.bak
    '/^OPENROUTER_API_KEY=/d' …`). Backup left at `.env.bak`.
  - Second `agent sync` succeeded: 2 written (`.env`, `config.yaml`),
    drift=0, 3s. Unit restarted by sync.
  - Smoke chat: agent self-reports model `qwen3:30b-64k`.
- **Files created/modified**:
  - `.sdlc/clawrium-gtm/CHECKLIST.md` (status updated)
- **Validation**:
  - `agent describe`: `Provider: clawrium-gtm-qwen3-64k`.
  - `agent provider get --agent clawrium-gtm`: single row, `primary`.
  - chat smoke test confirms model id.

## 2026-06-09 (rev 3) — Plan revised after second-round answers

- **Why**: User answers locked in: (a) provider naming convention
  `clawrium-<agent>-<short-model>` (and the new provider becomes
  `clawrium-gtm-qwen3-64k`, not `local-inx-qwen3-64k`); (b) no bash
  scripts — the hermes agent itself drives the 5-round loop via the
  skill; (c) all pipeline state lives in
  `~/.hermes/profiles/gtm-writer/workspace/`, never in `~/clawrium`;
  (d) operator commands use `uv run clawctl`.
- **Changes** to `BLOG-PIPELINE-PLAN.md`:
  - Added invariants I6 (provider naming), I7 (state location),
    I8 (no scripts — skill-driven loop), I9 (`uv run clawctl`).
  - Decision D1 renamed provider to `clawrium-gtm-qwen3-64k`.
  - Phase A: `uv run clawctl` prefix; provider rename throughout.
  - Phase B: added accurate distribution recognized-files list from
    [hermes docs](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions);
    added install + update commands with `--alias` and explicit
    update path after a `git pull`.
  - Phase D: replaced bash script (D1 + D2 + D3) with a
    skill-driven loop (D1 prose + D2 SKILL.md commit + D3 burn-in via
    `clawctl agent exec ... chat -q "/skill ..."` + D4 cron without
    `--script`/`--no-agent`).
  - Phase E: paths now `~/.hermes/profiles/gtm-writer/workspace/...`;
    bootstrap invoked via `mode=bootstrap` arg on the skill, not an
    env var; `uv run` prefix added.
- **Files created/modified**:
  - `.sdlc/clawrium-gtm/BLOG-PIPELINE-PLAN.md` (rev 3)
  - `.sdlc/clawrium-gtm/CHANGELOG.md`
- **Validation**:
  - Confirmed via webfetch that `hermes profile install` recognizes
    `distribution.yaml`, `SOUL.md`, `config.yaml`, `mcp.json`,
    `skills/`, `cron/`, `README.md` at the distribution root.
  - Confirmed `hermes profile update` overwrites only SOUL/skills/cron/mcp.json
    and never touches `workspace/` — which is why I7 is safe.

## 2026-06-09 (rev 2) — Plan revised after first-round answers

- **Why**: User confirmed Ansible-only changes, profile distributions
  (no SCP), new provider rather than swapping `local-inx`, label-based
  PR dedup (`type:blog`), author=maurice, and `~/clawrium` as the
  agent working dir.
- **Changes** to `BLOG-PIPELINE-PLAN.md`:
  - Added "Invariants" section (I1–I5).
  - Decision D1 rewritten: new provider `local-inx-qwen3-64k`,
    `local-inx` untouched.
  - Architecture diagram updated: working dir is `~/clawrium`.
  - Phase A: new step A2 (create provider), A3 (attach), A4 (Ansible
    role that clones repo + auth gh). A5 = snapshot.
  - Phase B: replaced "create + scp" with hermes profile
    distributions installed via `hermes profile install` and
    iterated via `hermes profile update`. Added in-repo distribution
    layout for `gtm-writer` and `gtm-reviewer`.
  - Phase D: loop script now ships inside writer distribution; uses
    `~/clawrium`; PR labeled `type:blog`; frontmatter
    `authors: [maurice]`. Cron command uses `--profile gtm-writer`.
  - Phase E: rewritten — announce skill keys off `type:blog` label
    (no full-text search), uses `~/clawrium/.gtm-work/announced-prs.json`
    for atomic dedup, has a one-shot bootstrap mode for backfill.
  - Phase F: SOUL update to pin working dir to `~/clawrium` and
    author=maurice.
- **Files created/modified**:
  - `.sdlc/clawrium-gtm/BLOG-PIPELINE-PLAN.md` (rev 2)
  - `.sdlc/clawrium-gtm/CHANGELOG.md`
- **Validation**:
  - `clawctl agent exec clawrium-gtm -- profile --help` confirmed
    `install` + `update` subcommands and their flags.
  - `clawctl agent exec clawrium-gtm -- cron create --help` confirmed
    `--profile`, `--script`, `--no-agent`, `--workdir`, `--deliver`
    flags align with the plan.
  - `website/blog/authors.yml` confirms `maurice` is a registered
    Docusaurus author with title "Program Manager, clawrium".
  - `gh label list -R ric03uec/clawrium` confirms `type:blog` exists.

## 2026-06-09 — Comprehensive blog-pipeline plan drafted (BLOG-PIPELINE-PLAN.md)

- **Why**: User requested a researched, incremental plan with validation
  gates for a daily blog pipeline (writer + reviewer profiles, excalidraw,
  PR-merge-gated publish, Discord announce). Plan doubles as source
  narrative for the eventual meta-post.
- **Changes**:
  - Drafted `BLOG-PIPELINE-PLAN.md` with phases A–G, 5-iteration loop,
    model justification, risk register, DoD.
  - Confirmed `excalidraw` skill is already bundled-enabled on gtm
    (no install needed).
  - Confirmed `local-inx` ollama provider already exists in clawrium.
  - Picked model: `qwen3:30b-64k` for both writer and reviewer in v1.
- **Files created/modified**:
  - `.sdlc/clawrium-gtm/CHANGELOG.md` (new)
  - `.sdlc/clawrium-gtm/BLOG-PIPELINE-PLAN.md` (new)
- **Validation**:
  - `clawctl agent describe clawrium-gtm` → confirmed type=hermes,
    host=wolf-i, current provider=clm-openrouter, channels=discord.
  - `clawctl agent exec clawrium-gtm -- skills list` → confirmed
    `excalidraw`, `architecture-diagram`, `claude-design` enabled.
  - `clawctl provider registry get` → confirmed `local-inx` (ollama).
  - `clawctl agent exec clawrium-gtm -- cron create --help` → confirmed
    `--profile`, `--skill`, `--script`, `--no-agent`, `--deliver` flags
    exist and match plan's automation needs.

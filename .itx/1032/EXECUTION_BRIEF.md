# Pi implementation — interactive worker brief for #1032

You are the **implementing worker**, running interactively in tmux on the
`issue-1032-pi-agent` branch. The human can attach to this session and review
your work. The OpenCode orchestrator handles sequencing other branches and
must not implement code. Read `AGENTS.md`, `.claude/skills/itx-execute/SKILL.md`,
`.itx/1032/00_PLAN.md`, and the parent GitHub issue before working. Follow the
task-checklist, prompt-log, commit, review and PR-body requirements of
`/itx-execute`, except where the user's explicit conditions below are stricter.

## The stack and your boundary

1. **This PR (base `main`):** customer milestone 1 — a real operator can
   create, inspect, execute `--version`, and remove an isolated, pinned Pi
   agent on Linux `wolf-i` and macOS `mac-test`. Implement the daemonless
   first-class lifecycle, registry/manifest, Linux/macOS install and removal,
   appropriate CLI and fleet GUI visibility, tests, docs, and changelog. Do
   not quietly add a daemon, native dashboard, or ownership of project `.pi`
   files. Keep the provider/model selection in Clawrium's control plane; Pi
   will consume only access provisioned to its own fleet-host account. Leave
   live provider responses for subsequent stacked PRs.
2. #1038 (base this branch): existing OpenRouter provider and actual model
   response on `wolf-i` through CLI/native exec and GUI, including session
   continuation/reset. It owns milestones 2–3.
3. #1039 (base #1038): AWS SSO/Bedrock live validation, including short-lived
   credential behavior.
4. #1040 (base #1039): Codex OAuth live validation, no API-key substitution.
5. Final #1032 hardening PR (base #1040): switching/detach, cleanup across all
   providers, final real-host UAT and documentation for milestone 6.

Implement ONLY the first milestone in this session. Do not spawn another
agent, create other branches, open follow-on PRs, or merge anything. Include
`.itx/1032/00_PLAN.md`, `architecture.html`, this brief and an execution prompt
log under `.itx/1032/` in the first PR. Existing worktrees are unrelated and
must not be modified. Track work via a checklist before edits; use incremental
changes and meaningful tests. Run **`make test` and `make lint`** yourself.

## Mandatory real-host gate for this PR

- Confirm `wolf-i` and `mac-test` status, pre-existing agents, and host OS
  before making changes. Use fresh uniquely named Pi UAT agents; do not reuse
  or delete existing accounts, agents or credential state.
- On **`wolf-i`**, use the *working-tree* CLI rather than an old globally
  installed release to create the Pi agent, inspect it, run
  `clawctl agent exec <uat-agent> -- --version` on its dedicated remote OS
  account, verify no Pi service/native UI was created, then remove it. Check
  both remote agent-owned resources and local agent state are gone and that
  the pre-existing fleet is unchanged.
- The mandatory live UAT gate for this PR is `wolf-i`: create, inspect,
  version, daemon/UI absence, removal, and preservation checks must pass there.
  Also exercise the macOS implementation through automated tests. Attempt
  `mac-test` live UAT when reachable; if host access is unavailable, record
  precisely that macOS live UAT is unverified in the PR Callouts. This does
  not block the PR once the mandatory `wolf-i` gate and all other checks pass.
- Record only **redacted** commands, results and before/after evidence in
  `.itx/1032/01_EXECUTION.md` and in the PR. Never print credentials, auth
  files or tokens. Cleanup any test agents even if verification fails.

## Review and handoff gate — stricter than skill's nonblocking fallback

- ATX CLI is running. For Pi-authored changes, stage intended files so new
  files are visible, then invoke **`atx review request -p "Review the full
  staged and unstaged diff of this branch against main, including untracked
  files; identify blockers and rate /5" --format json --timeout 15m`** in
  this worktree. Do not use the Claude-session-scoped `atx review` command.
- Fix every blocking issue and rerun review until the leader's **review body**
  reports **rating >3/5 with zero unresolved blockers**. Persist the ATX
  metadata in `.itx/1032/atx-session.json` as required by the skill. Review
  before commit, and re-review after material fixes. No three-try bypass:
  **do not create a PR if ATX or UAT cannot pass**. Flag a real blocker in
  this tmux session so the human/orchestrator can see it.
- Inspect `git status`, `git diff`, `git log --oneline -10` before committing;
  stage only intended files, do not commit secrets. Follow the repository ATX
  commit and PR templates, document all review rounds and UAT evidence, add
  `Co-Authored-By: @atx-ci <269048218+atx-ci@users.noreply.github.com>`
  in commit and PR body and a `## Callouts` section. Credit Pi as author, not
  Claude Code. This first PR must **not** close parent #1032 prematurely.
- Push this feature branch, open the PR **against `main`** only after all
  gates pass, then leave the interactive session available and report PR URL,
  ATX rating, tests, and live-host evidence in the terminal. The orchestrator
  starts the next Pi worker only after verifying the PR and gates.

## Original user instruction

> ok. fine. then use /itx-execute to implement this feature. you're the orchestrator and will NOT EXECUTE any code. you'll spin up tmux+pi(gpt terra, medium thinking) and ask that agent to execute these tasks. send stacked prs once atx review (use atx cli) are passing acording to the repo rules  use pi in an interactive mode so i can rview the changes if needed. send stacked prs when done. verify it on a real agent. use wolf-i as the test host to create a new agent and remove it. uAT is mandatory before you claim  you're done

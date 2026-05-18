#!/bin/bash
# Orchestrate-mode runner for parent #364.
#
# Polls the current phase's PR every 5 min. When the PR opens (signal that
# the child cleared ATX and exit criteria), spawns the next phase's child
# in a new tmux window, stacked on the predecessor's branch.
#
# Halts on [ITX-STUCK] comments on the predecessor's issue.
#
# Logs to .itx/364/orchestrate.log

set -uo pipefail

REPO_ROOT=/home/devashish/workspace/ric03uec/clawrium
LOG="$REPO_ROOT/.itx/364/orchestrate.log"
STATE_FILE="$REPO_ROOT/.itx/364/orchestrate-state.json"
TMUX_SESSION="itx/364"
REPO_PARENT=$(dirname "$REPO_ROOT")
REPO_NAME=$(basename "$REPO_ROOT")
POLL_INTERVAL_SEC=300

# Phase chain: <issue> <branch>
# (Phase 0 already spawned by the orchestrator session before this script runs.)
PHASES=(
  "386 issue-386-phase0-research"
  "380 issue-380-cli-skill-catalog-browse"
  "381 issue-381-cli-skill-install-hermes"
  "382 issue-382-cli-skill-install-openclaw-zeroclaw"
  "383 issue-383-gui-skill-catalog-browse"
  "384 issue-384-gui-skill-install-all-claws"
  "385 issue-385-skills-docs-ci"
)

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"
}

check_pr_open() {
  local branch=$1
  gh pr list --repo ric03uec/clawrium --head "$branch" --state open --json number --jq '.[0].number // empty' 2>/dev/null
}

check_stuck() {
  local issue=$1
  gh issue view "$issue" --repo ric03uec/clawrium --json comments \
    --jq '.comments[] | select(.body | startswith("[ITX-STUCK]")) | .url' 2>/dev/null | head -1
}

spawn_phase() {
  local issue=$1
  local branch=$2
  local prev_branch=$3
  local worktree="$REPO_PARENT/$REPO_NAME-issue-$issue"
  local window="phase-${issue}"

  if [ -d "$worktree" ]; then
    log "Worktree $worktree already exists; skipping create"
  else
    log "Creating worktree $worktree on branch $branch from $prev_branch"
    cd "$REPO_ROOT" && git worktree add "$worktree" -b "$branch" "$prev_branch" >>"$LOG" 2>&1
  fi

  log "Spawning tmux window $window for issue #$issue (pr-base=$prev_branch)"
  tmux new-window -t "$TMUX_SESSION" -n "$window" -c "$worktree"

  local prompt
  if [ "$prev_branch" = "main" ]; then
    prompt="/itx-execute $issue"
  else
    prompt="/itx-execute $issue --pr-base=$prev_branch"
  fi

  tmux send-keys -t "$TMUX_SESSION:$window" \
    "claude --dangerously-skip-permissions '$prompt'" Enter
  log "Child claude launched for #$issue"
}

main() {
  log "Orchestrator runner started for parent #364, ${#PHASES[@]} phases"

  for i in "${!PHASES[@]}"; do
    set -- ${PHASES[$i]}
    local issue=$1
    local branch=$2

    log "----- Phase index $i: issue #$issue branch $branch -----"

    # Wait until this phase's PR opens
    while true; do
      pr_num=$(check_pr_open "$branch")
      if [ -n "$pr_num" ]; then
        log "Phase #$issue PR #$pr_num is OPEN — gate cleared"
        break
      fi

      stuck=$(check_stuck "$issue")
      if [ -n "$stuck" ]; then
        log "[ITX-STUCK] detected on #$issue: $stuck"
        log "Halting orchestration. User intervention required."
        exit 1
      fi

      sleep "$POLL_INTERVAL_SEC"
    done

    # Spawn next phase if there is one
    next_i=$((i + 1))
    if [ "$next_i" -ge "${#PHASES[@]}" ]; then
      log "Last phase #$issue PR is open. Orchestration complete."
      break
    fi

    set -- ${PHASES[$next_i]}
    local next_issue=$1
    local next_branch=$2
    spawn_phase "$next_issue" "$next_branch" "$branch"
  done

  log "Orchestrator runner finished"
}

main

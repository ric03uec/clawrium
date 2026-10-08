# Issue #1031 — Integration and acceptance verification

## Integrated status (2026-10-08 UTC)

- #1034 (Codex foundation), #1035 (local OAuth provider), and #1036
  (refresh-safe credential activation) were merged to `main`.
- #1037 (finite CLI/GUI chat) is open as PR #1050. This parent integration
  branch is stacked on `issue-1037-codex-chat`; it must be rebased/retargeted
  to `main` after #1050 merges.
- The #1037 branch passed `make test` (5,673 Python passed, 2 skipped;
  369 GUI passed) and `make lint`. The parent documentation-only changes
  independently passed `make test` (5,673 Python passed, 2 skipped;
  369 GUI passed) and `make lint` after building the GUI assets in the
  fresh worktree with `make build-ui`.

## Real-host verification ledger

| Check | Result | Evidence and limitations |
|---|---|---|
| Ubuntu no-auth install | Passed | `uv run clawctl agent create codex-1031-wolf-uat --type codex --host wolf-i --yes` installed dedicated Codex 0.160.1; audit `0284a5b6`. |
| Ubuntu native version | Passed | `uv run clawctl agent exec codex-1031-wolf-uat -- --version` returned `codex-cli 0.160.1`. No inference was requested. |
| Ubuntu cleanup | Passed | `uv run clawctl agent delete codex-1031-wolf-uat --yes` removed remote account and local record; audit `fbe66516`; the agent no longer appears in `agent get`. |
| macOS no-auth install | Blocked | `uv run clawctl agent create codex-1031-uat --type codex --host mac-test --yes` timed out connecting to 100.120.88.97:22 before any Ansible tasks; audit `1fc2c937`. `mac-test` was absent from `tailscale status`. The failed local record remains for retry and safe remote cleanup. The CLI displayed failure but returned exit status 0; investigate separately rather than treating it as success. |
| Native OAuth activation, remote refresh preservation and CLI/GUI chat | Blocked | Controller `~/.codex/auth.json` is absent; `codex login status` reports `Not logged in`; no `codex-oauth` provider exists. Requires an operator-authorized file-backed Codex login and an entitled account. No live credential was copied or printed. |

The lifecycle checks do not satisfy the parent's OAuth or chat end-to-end
acceptance criteria. Do not check off the issue or close it until authenticated
sync, repeat-sync after remote refresh, native CLI and GUI inference, and
macOS cleanup are observed and documented.

## Next verification steps

1. Operator completes a file-backed Codex login on this controller and verifies
   `codex login status`; do not paste `auth.json` or tokens into issues or PRs.
2. Bring mac-test online; retry the failed `codex-1031-uat` record and confirm
   remote cleanup through `clawctl agent delete codex-1031-uat --yes`.
3. On a disposable Codex agent, create and attach a `codex-oauth` provider,
   sync, inspect remote credential ownership/mode without viewing the contents,
   and verify native CLI and GUI chat continuation and reset. After a genuine
   remote token refresh, sync again and verify inference still works without
   overwriting refreshed state. Delete the test agent and provider.
4. Update this ledger with redaction-safe results, rerun verification, and
   only then mark the relevant parent acceptance checks and close #1031.

## Execution

**Stage**: execution
**Skill**: /itx-execute
**Timestamp**: 2026-10-08T04:25:00Z
**Model**: openai/gpt-6-sol

```prompt
you're now the orchestraot to take this to completion. contine to send prs till this is done
```

**Output**: Stacked parent integration verification on the Codex chat branch;
documented real-host lifecycle results and the prerequisites for authenticated
end-to-end acceptance.

# Issue #1031 — Integration and acceptance verification

## Integrated status (2026-10-09 UTC)

- #1034 (Codex foundation), #1035 (local OAuth provider), #1036
  (refresh-safe credential activation), and #1037 (CLI/GUI chat) are all
  merged to `main` (the latter via PR #1050). Parent docs PR #1051 is merged.
- Live UAT discovered two integration defects: native Codex 0.160.1 ChatGPT
  login files include an optional `OPENAI_API_KEY: null` root field, and
  native chat from an isolated non-Git home requires `--skip-git-repo-check`
  on fresh and resumed exec. Both are fixed on the follow-up branch.
- The follow-up branch passed `make test` (5,677 Python passed, 2 skipped;
  369 GUI passed) and `make lint`. The earlier #1037 and parent PRs passed
  their own complete suites before merge.

## Real-host verification ledger

| Check | Result | Evidence and limitations |
|---|---|---|
| Ubuntu no-auth install | Passed | `uv run clawctl agent create codex-1031-wolf-uat --type codex --host wolf-i --yes` installed dedicated Codex 0.160.1; audit `0284a5b6`. |
| Ubuntu native version | Passed | `uv run clawctl agent exec codex-1031-wolf-uat -- --version` returned `codex-cli 0.160.1`. No inference was requested. |
| Ubuntu cleanup | Passed | `uv run clawctl agent delete codex-1031-wolf-uat --yes` removed remote account and local record; audit `fbe66516`; the agent no longer appears in `agent get`. |
| macOS no-auth install | Blocked | `uv run clawctl agent create codex-1031-uat --type codex --host mac-test --yes` timed out connecting to 100.120.88.97:22 before any Ansible tasks; audit `1fc2c937`. `mac-test` was absent from `tailscale status`. The failed local record remains for retry and safe remote cleanup. The CLI displayed failure but returned exit status 0; investigate separately rather than treating it as success. |
| Controller login and provider import | Passed with fix | Operator authorized `codex login --device-auth`; native `codex login status` reported ChatGPT login. Selection-only provider `codex-1031-uat-oauth` was created (audit `6e272fde`); initial attach rejected the real file as malformed without persisting an attachment (`d0b65476`). After allowing only `OPENAI_API_KEY: null`, attach passed (`33fdcd44`) and stored only the instance-scoped `CODEX_OAUTH_DOCUMENT` secret. No token values printed. |
| Ubuntu authenticated install/activation | Passed | `codex-1031-live` created as a separate agent account on wolf-i (audit `c27d8b18`), with Codex 0.160.1. Provider attached and synced (`e0506b11`); remote `~/.codex/auth.json` was owned by the dedicated account with mode `0600`, and native `codex login status` reported ChatGPT login. Native exec and shell returned `codex-cli 0.160.1`. |
| Native CLI inference and history | Passed with fix | In the isolated home the initial chat command failed safely (nonzero exit). A native `codex exec --json --skip-git-repo-check` returned the exact requested `WOLF-CODEX-1031-OK`; adding the same flag to fresh and resume chat allowed `clawctl agent chat --once` to respond exactly. Interactive turns remembered `TURQUOISE-741`, `/reset` cleared history, and the next turn returned `NONE`. |
| GUI inference and history | Passed | Installed the follow-up branch locally and restarted the GUI. A real Chat tab exchange on `codex-1031-live` remembered `AMBER-518` across two turns; **New chat** cleared the conversation and a follow-up returned `NONE`. No auth material was sent to the browser. |
| Ordinary repeat sync | Passed; no actual token rotation observed | Remote auth metadata before/after was identical (`mode 0600`, agent owner, same modification timestamp). `agent sync` completed (audit `5ed8fb71`), and authenticated inference returned `SYNC-KEPT-OAUTH-1031`. This proves ordinary sync did not overwrite the remote file; it does **not** prove preservation after a real remote refresh. Automated tests cover changed-token preservation. |
| Explicit re-attach | Passed | Re-attaching the same selection-only provider refreshed the agent-scoped local snapshot (audit `0ae8b24a`); sync replaced one private remote document (audit `b6bac984`); native `login status` still reported ChatGPT login and chat returned `REATTACH-1031-OK`. |
| Disposable agent/provider cleanup | Passed | `agent delete codex-1031-live --yes` removed the dedicated remote account and instance secrets/record (audit `6b2f67de`), then `provider registry delete codex-1031-uat-oauth --yes` removed the provider (audit `c3f76ec4`). Both describe commands report not found; other fleet agents remain listed. |

The authenticated Linux end-to-end acceptance path is now exercised. A live
remote token refresh and macOS real-host run were not observed. The old failed
mac-test record is a separate cleanup follow-up once that host is reachable;
do not imply any remote cleanup occurred there.

## Next verification steps

1. Merge and deploy the reviewed schema/chat follow-up PR #1055 after CI passes.
2. When mac-test returns, retry/delete its failed `codex-1031-uat` record via
   remote lifecycle operations; do not drop the local record without a remote
   outcome. A genuine token-refresh UAT can be observed separately; tests
   already cover refreshed remote state versus ordinary sync and re-attach.
3. Update the parent issue's acceptance status and close #1031 when the
   merged code and required real-host checks agree.

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

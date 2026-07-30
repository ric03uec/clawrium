Read .claude/skills/clawctl-lmwork/judge.md and follow it for issue #418, round 1.

Path note (this run predates the skill's `.itx/<N>/` convention change): the brief and corrections live at `.lmwork/418/brief.md`, `.lmwork/418/correction-1.md`, and `.lmwork/418/correction-2.md`. Read all three — correction-1 tightened the middleware allowed_hosts and split the `secrets_configured` test into True/False cases; correction-2 widened the scope fence to update existing GUI test files to `TestClient(app, base_url="http://localhost:36000")`.

Also: lmworker's pi session ended after committing `d973f2e`. Interactive revision is not available — if you find REVISE findings, write them to `.lmwork/418/judge-1.md` and stop; the orchestrator will decide whether to restart pi with `pi --session 019fb417-56dc-7bb5-9136-4f1ddd8f3079` or resolve the finding another way.

Special check for this run: verify `gui/src/lib/types.ts` was updated to match the new `/api/settings` response shape (drop `hosts_file`/`providers_file`/`secrets_file`, add `secrets_configured: boolean`). This is a spot pi initially missed and later fixed via commit amend — confirm the final HEAD contains the right shape.

Emit your verdict as the last line of your response: either `VERDICT: SATISFIED` or `VERDICT: REVISE`.

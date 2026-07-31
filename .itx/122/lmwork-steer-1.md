STOP. Delete your current plan. Reset todos to exactly these five items and follow them literally:

1. Add a new `--description` / `-d` flag to the EXISTING `edit()` function in `src/clawrium/cli/clawctl/host/edit.py`. Do NOT create any new command file. Do NOT create a `host update` command. `host edit` already exists — extend it.
2. Extend `host_to_row(...)` in `src/clawrium/cli/clawctl/host/_shared.py` with one line: `"description": host.get("description", "")`.
3. Add one line to `src/clawrium/cli/clawctl/host/describe.py` after the `Port:` line: `lines.append(f"Description: {_s(row['description'] or '-')}")`.
4. Add three tests to `tests/cli/clawctl/host/test_update.py` mirroring `test_edit_hostname_success` and `test_edit_no_args_error`:
   - `test_edit_description_success` — invoke `["host", "edit", "wolf-i", "--description", "my-desc"]`, assert `get_host("wolf-i")["description"] == "my-desc"`.
   - `test_edit_description_clear_with_empty_string` — invoke with `"--description", ""`, assert the description key is absent or empty on the host.
   - Extend `test_edit_no_args_error` so its assertion also mentions `--description` in the hint.
5. Add ONE line to `CHANGELOG.md` under `## [Unreleased]` → `### Added` referencing #122.

HARD CONSTRAINTS:
- DO NOT create `src/clawrium/cli/clawctl/host/update.py`. Delete it if you already made it.
- DO NOT add `--tag` / `--tags` / labels support. Out of scope.
- DO NOT touch `host/__init__.py` — no new command to register.
- DO NOT touch `host/create.py`, `host/get.py`, or anything else not listed above.
- The verb is `edit`, not `update`. The command is `clawctl host edit --description <text>`.
- Description is a free-form string on the host dict. No schema changes needed anywhere.

After you finish the five items:
- Run `make lint && make test` in the worktree — both must pass.
- Commit locally (do NOT push).
- `echo done > .itx/122/lmwork-worker.done`

Confirm you understand by first showing me the updated todo list matching the five items above, then start work.

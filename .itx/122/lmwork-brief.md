Apply the following four small edits and then run `make lint && make test`. Do NOT read the GitHub issue body — everything you need is here. Do NOT create any new files. Do NOT touch `host/__init__.py`. Do NOT add any tags/labels flag. The verb is `edit`, not `update`.

## Edit 1 — `src/clawrium/cli/clawctl/host/edit.py`

The existing `edit(...)` function already accepts `--user`, `--port`, `--alias`, `--hostname`. Add a fifth flag with identical shape:

- New parameter (place it after `hostname_new`):
  ```python
  description: Optional[str] = typer.Option(
      None, "--description", "-d", help="New host description (free-form)."
  ),
  ```
- Update the "no edits requested" guard to include `description`:
  ```python
  if user is None and port is None and alias is None and hostname_new is None and description is None:
      emit_error(
          "no edits requested",
          hint="pass at least one of --user, --port, --alias, --hostname, --description",
      )
  ```
- Inside the inner `apply(h: dict) -> dict` closure, add:
  ```python
  if description is not None:
      if description == "":
          h.pop("description", None)
      else:
          h["description"] = description
  ```

## Edit 2 — `src/clawrium/cli/clawctl/host/_shared.py`

Inside `host_to_row(host: dict) -> dict`, add one line to the returned dict alongside the other top-level fields:
```python
"description": host.get("description", ""),
```

## Edit 3 — `src/clawrium/cli/clawctl/host/describe.py`

Inside `describe(...)`, in the text-format branch, add ONE line immediately after the `Port:` line:
```python
lines.append(f"Description: {_s(row['description'] or '-')}")
```

## Edit 4 — `tests/cli/clawctl/host/test_update.py`

Append three tests at the bottom of the file, mirroring the shape of `test_edit_hostname_success` / `test_edit_no_args_error` already in the file:

```python
def test_edit_description_success(fleet_dir) -> None:
    result = runner.invoke(
        app, ["host", "edit", "wolf-i", "--description", "primary lab box"]
    )
    assert result.exit_code == 0, result.output
    assert "updated" in result.output

    host = get_host("wolf-i")
    assert host is not None
    assert host.get("description") == "primary lab box"


def test_edit_description_clear_with_empty_string(fleet_dir) -> None:
    runner.invoke(app, ["host", "edit", "wolf-i", "--description", "temp"])
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--description", ""])
    assert result.exit_code == 0, result.output

    host = get_host("wolf-i")
    assert host is not None
    assert "description" not in host or not host["description"]


def test_edit_description_hint_lists_flag(fleet_dir) -> None:
    result = runner.invoke(app, ["host", "edit", "wolf-i"])
    assert result.exit_code != 0
    assert "--description" in result.output
```

## Edit 5 — `CHANGELOG.md`

Under `## [Unreleased]` → `### Added`, add exactly one bullet:
```
- `clawctl host edit --description <text>` sets or updates a free-form description on a host record; passing an empty string clears it (#122).
```

If `### Added` does not exist yet under `## [Unreleased]`, create just that subsection (leave `### Changed` / `### Fixed` untouched).

## After the five edits

1. `make lint` — must pass.
2. `make test` — must pass. If a failing test is unrelated to your changes, skip it explicitly and note in the commit body.
3. `git add -A` (only the files you edited plus `.itx/122/`)
4. `git commit -m "feat(#122): clawctl host edit --description"` — with a short body describing the flag.
5. `echo done > .itx/122/lmwork-worker.done`

## Absolute prohibitions

- Do NOT create `src/clawrium/cli/clawctl/host/update.py` (or any new file under `host/`).
- Do NOT edit `host/__init__.py`.
- Do NOT add `--tag` / `--tags` / any labels flag.
- Do NOT touch `host/create.py`, `host/get.py`, `host/label.py`, or the wiring code.
- Do NOT touch anything under `src/clawrium/core/`.
- Do NOT run `git push`. Do NOT open a PR.

Start immediately. Do not spawn an Explore subagent — the four files are already named above.

"""Ansible Jinja filter plugin — provides `workspace_excluded` for the
hermes workspace playbook.

Mirrors `clawrium.core.workspace_sync._is_excluded` exactly. The Python
enumerator already drops excluded files before they are staged; this
filter is the belt-and-suspenders re-check at the playbook copy
boundary (hook-review S — platform-playbooks). Drift between the two
would either let an excluded file through (Python applies the filter
but the playbook does not) or silently drop a legitimate file (the
playbook is stricter than Python).

Ansible auto-discovers filter_plugins/ directories adjacent to the
playbook, so dropping this file alongside `workspace.yaml` is enough —
no ansible.cfg / ANSIBLE_FILTER_PLUGINS plumbing required.

Issue #769 (Phase 3 of #760).
"""


def workspace_excluded(rel, excludes_files, excludes_dirs):
    """Return True if `rel` matches the manifest workspace exclude set.

    `excludes_files` are exact-path entries (no trailing slash).
    `excludes_dirs` are directory-prefix entries (stored WITHOUT trailing
    slash by the Python enumerator; the comparison adds it back so
    `state.db` does not silently match `state.db-journal` etc.).

    Matches `clawrium.core.workspace_sync._is_excluded`. Any change to
    that function MUST land in this filter in the same commit (S — drift
    enforcement).
    """
    if rel in (excludes_files or []):
        return True
    for d in (excludes_dirs or []):
        prefix = d.rstrip("/") + "/"
        if rel == d or rel.startswith(prefix):
            return True
    return False


class FilterModule:
    def filters(self):
        return {"workspace_excluded": workspace_excluded}

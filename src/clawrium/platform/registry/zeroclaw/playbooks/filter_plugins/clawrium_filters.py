"""Ansible Jinja filter plugin — provides `toq` for zeroclaw configure.yaml.

The same TOML escape is applied in the Python canonical render path at
`clawrium.core.render._toml_escape` (registered as the `toq` filter at
`render.py:965`). The Ansible playbook renders the SAME template file
(`zeroclaw-config.toml.j2`) via `ansible.builtin.template`, so its
Jinja environment also needs the filter or every `clawctl agent
configure --stage providers` run will fail with `No filter named 'toq'`.

Ansible auto-discovers filter_plugins/ directories adjacent to the
playbook, so dropping this file alongside `configure.yaml` is enough —
no ansible.cfg / ANSIBLE_FILTER_PLUGINS plumbing required.

Closes #583 (zeroclaw configure path).
"""


def toq(value):
    """Escape a value for use inside a TOML basic (double-quoted) string.

    Mirrors `clawrium.core.render._toml_escape` exactly — any drift between
    the two would silently produce different config.toml bytes depending on
    which render path the operator hit (sync vs configure).
    """
    s = str(value)
    return (
        s.replace("\x00", "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


class FilterModule:
    def filters(self):
        return {"toq": toq}

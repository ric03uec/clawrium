"""Website docs mirror invariants (ATX #411 B4/B5/B6)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _strip_frontmatter(text: str) -> str:
    """Drop a Docusaurus YAML frontmatter block (--- ... ---) from text."""
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("---"):
        return text
    # Find the closing ---
    for i in range(1, len(lines)):
        if lines[i].startswith("---"):
            # Body starts after the closing --- and any single blank line.
            rest = lines[i + 1 :]
            if rest and rest[0].strip() == "":
                rest = rest[1:]
            return "".join(rest)
    return text


@pytest.mark.parametrize(
    "canonical,mirror",
    [
        ("docs/skills/index.md", "website/docs/skills/intro.md"),
        ("docs/skills/authoring-clawrium.md", "website/docs/skills/authoring.md"),
    ],
)
def test_website_mirrors_canonical_body(canonical: str, mirror: str):
    """ATX #411 B4/B5: website doc bodies must mirror the canonical
    source verbatim. Frontmatter is allowed to differ."""
    canon_text = (REPO / canonical).read_text()
    mirror_text = (REPO / mirror).read_text()
    assert _strip_frontmatter(mirror_text) == canon_text, (
        f"{mirror} body diverges from {canonical}. "
        "Re-sync via 'cat docs/skills/<name>.md >> website/docs/skills/<name>.md'."
    )


def test_no_clm_in_homepage_features():
    """ATX #411 B6: HomepageFeatures must not reintroduce `clm` CLI refs."""
    path = REPO / "website/src/components/HomepageFeatures/index.tsx"
    text = path.read_text()
    # Allow the word inside larger identifiers (none currently match), but
    # block any literal occurrence of the retired `clm` token.
    assert "clm " not in text and "clm`" not in text and "clm CLI" not in text, (
        "`clm` CLI reference reintroduced in HomepageFeatures. Use `clawctl`."
    )


def test_zeroclaw_skills_apply_has_staging_dir_assert():
    """ATX #411 B7: zeroclaw playbook must contain the staging_dir
    confinement assert."""
    path = REPO / "src/clawrium/platform/registry/zeroclaw/playbooks/skills_apply.yaml"
    text = path.read_text()
    assert "Assert staging_dir is a non-empty absolute path" in text
    assert "'/clawrium/staging/skills/' in staging_dir" in text

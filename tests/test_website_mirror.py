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
        ("docs/skills/authoring.md", "website/docs/skills/authoring.md"),
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


def _scan_intradoc_links(root: Path) -> list[str]:
    """Walk every .md in `root`, return a list of broken relative-md
    link descriptors (`filename -> target`).

    Matches both `./foo.md` and bare `foo.md` (without `./`). Strips
    `#fragment` qualifiers before resolving. (ATX #411 iter-4 W1/W2.)
    """
    import re

    # Capture group 1 is the file path; group 2 (optional) is the
    # fragment that we discard.
    link_re = re.compile(r"\]\(((?:\./)?[^)\s#]+\.md)(?:#[^)]*)?\)")
    failures: list[str] = []
    for md in root.rglob("*.md"):
        text = md.read_text()
        for match in link_re.finditer(text):
            target = (md.parent / match.group(1)).resolve()
            if not target.is_file():
                failures.append(f"{md.relative_to(REPO)} -> {match.group(1)}")
    return failures


def test_website_skills_intradoc_links_resolve():
    """ATX #411 iter-3 New-B6: every relative .md link in a website
    skills doc must resolve to a file that actually exists."""
    failures = _scan_intradoc_links(REPO / "website" / "docs" / "skills")
    assert not failures, "Broken intra-doc links: " + ", ".join(failures)


def test_canonical_skills_intradoc_links_resolve():
    """ATX #411 iter-4 W3: equivalent scan for the canonical docs tree
    so a broken link in `docs/skills/` is also caught at `make test`."""
    failures = _scan_intradoc_links(REPO / "docs" / "skills")
    assert not failures, "Broken intra-doc links: " + ", ".join(failures)

import React, {type ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type Tag = {label: string; to: string};

// Slugs must match the keys in website/blog/tags.yml — Docusaurus generates
// /blog/tags/<slug> from those frontmatter entries. Renaming a tag there
// requires updating this list to avoid 404s from the right rail.
const TAGS: Tag[] = [
  {label: 'Announcements', to: '/blog/tags/announcements'},
  {label: 'Release Notes', to: '/blog/tags/release-notes'},
  {label: 'Release', to: '/blog/tags/release'},
  {label: 'Breaking Changes', to: '/blog/tags/breaking-changes'},
];

const GITHUB_REPO = 'https://github.com/ric03uec/clawrium';
const DISCUSSIONS = 'https://github.com/ric03uec/clawrium/discussions';
const ISSUES = 'https://github.com/ric03uec/clawrium/issues';

export default function BlogRightRail(): ReactNode {
  return (
    <aside
      className={styles.rail}
      aria-label="About Clawrium and blog tags">
      <section className={styles.section}>
        <Heading as="h3" className={styles.heading}>
          About Clawrium
        </Heading>
        <p className={styles.blurb}>
          A CLI tool for managing AI agent fleets across your local network.
          One pane of glass for installing, configuring, and operating agents
          on every host you own.
        </p>
      </section>

      <section className={styles.section}>
        <Heading as="h3" className={styles.heading}>
          Tags
        </Heading>
        <ul className={styles.tagList}>
          {TAGS.map((tag) => (
            <li key={tag.to}>
              <Link className={styles.tagPill} to={tag.to}>
                {tag.label}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.section}>
        <Heading as="h3" className={styles.heading}>
          Community
        </Heading>
        <ul className={styles.linkList}>
          <li>
            <Link
              to={GITHUB_REPO}
              target="_blank"
              rel="noopener noreferrer">
              GitHub repository
            </Link>
          </li>
          <li>
            <Link
              to={DISCUSSIONS}
              target="_blank"
              rel="noopener noreferrer">
              Discussions
            </Link>
          </li>
          <li>
            <Link
              to={ISSUES}
              target="_blank"
              rel="noopener noreferrer">
              Report an issue
            </Link>
          </li>
        </ul>
      </section>
    </aside>
  );
}

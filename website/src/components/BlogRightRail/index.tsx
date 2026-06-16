import React from 'react';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type Tag = {label: string; to: string};

const TAGS: Tag[] = [
  {label: 'Announcements', to: '/blog/tags/announcements'},
  {label: 'Release Notes', to: '/blog/tags/release-notes'},
  {label: 'Release', to: '/blog/tags/release'},
  {label: 'Breaking Changes', to: '/blog/tags/breaking-changes'},
];

const GITHUB_REPO = 'https://github.com/ric03uec/clawrium';
const DISCUSSIONS = 'https://github.com/ric03uec/clawrium/discussions';
const ISSUES = 'https://github.com/ric03uec/clawrium/issues';

export default function BlogRightRail(): React.JSX.Element {
  return (
    <aside className={styles.rail} aria-label="Blog sidebar">
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
            <Link to={GITHUB_REPO}>GitHub repository</Link>
          </li>
          <li>
            <Link to={DISCUSSIONS}>Discussions</Link>
          </li>
          <li>
            <Link to={ISSUES}>Report an issue</Link>
          </li>
        </ul>
      </section>
    </aside>
  );
}

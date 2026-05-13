import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <img
          src="/clawrium/img/clawrium-logo.png"
          alt="Clawrium Logo"
          className={styles.heroLogo}
        />
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <p className={styles.heroDescription}>
          <strong>Clawrium is a CLI to manage all your AI assistants.</strong>
          <br />
          Point it at any machine on your network, and deploy agents like{' '}
          <a href="https://github.com/openclaw/openclaw" className={styles.heroLink}>OpenClaw</a>{' '}
          and{' '}
          <a href="https://github.com/NousResearch/hermes-agent" className={styles.heroLink}>Hermes</a>{' '}
          with a single command.
        </p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/guides/quickstart">
            5-Minute Quickstart
          </Link>
          <Link
            className="button button--outline button--secondary button--lg"
            to="https://github.com/ric03uec/clawrium">
            View on GitHub
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title="Manage Your AI Claw Fleet"
      description="CLI tool for managing AI assistant fleets on local networks. Deploy and manage multiple claw instances across hosts from a single command center.">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}

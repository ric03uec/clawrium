import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  icon: string;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Universal Claw Support',
    icon: '🦀',
    description: (
      <>
        Manage any claw from a single command center: OpenClaw, ZeroClaw,
        NemoClaw, NanoClaw, IronClaw, and more.
      </>
    ),
  },
  {
    title: 'Normalized Configuration',
    icon: '⚙️',
    description: (
      <>
        One config format for every claw. Define your preferences once and
        Clawrium translates them for each claw&apos;s native format.
      </>
    ),
  },
  {
    title: 'Multi-Model Freedom',
    icon: '🔓',
    description: (
      <>
        Run any model across your fleet: open models like Nemotron,
        providers like OpenAI and Anthropic, or local with Ollama.
      </>
    ),
  },
];

function Feature({title, icon, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center">
        <span className={styles.featureIcon} role="img" aria-label={title}>
          {icon}
        </span>
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}

import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  icon: ReactNode;
  description: ReactNode;
};

function GlobeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="64" height="64">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2m-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93m6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39"/>
    </svg>
  );
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="64" height="64">
      <path d="M12 15.5A3.5 3.5 0 0 1 8.5 12A3.5 3.5 0 0 1 12 8.5a3.5 3.5 0 0 1 3.5 3.5a3.5 3.5 0 0 1-3.5 3.5m7.43-2.53c.04-.32.07-.64.07-.97c0-.33-.03-.66-.07-1l2.11-1.63c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.31-.61-.22l-2.49 1c-.52-.39-1.06-.73-1.69-.98l-.37-2.65A.506.506 0 0 0 14 2h-4c-.25 0-.46.18-.5.42l-.37 2.65c-.63.25-1.17.59-1.69.98l-2.49-1c-.22-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64L4.57 11c-.04.34-.07.67-.07 1c0 .33.03.65.07.97l-2.11 1.66c-.19.15-.25.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1.01c.52.4 1.06.74 1.69.99l.37 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.37-2.65c.63-.26 1.17-.59 1.69-.99l2.49 1.01c.22.08.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.66Z"/>
    </svg>
  );
}

function UnlockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" width="64" height="64">
      <path d="M10 13a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-2m6-2V8a4 4 0 0 0-4-4 4 4 0 0 0-4 4h2a2 2 0 0 1 2-2 2 2 0 0 1 2 2v3H8a2 2 0 0 0-2 2v5a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-5a2 2 0 0 0-2-2h-2Z"/>
    </svg>
  );
}

const FeatureList: FeatureItem[] = [
  {
    title: '🌐 Universal Claw Support',
    icon: <GlobeIcon />,
    description: (
      <>
        Today, Clawrium supports{' '}
        <a href="https://github.com/openclaw/openclaw">OpenClaw</a> and{' '}
        <a href="https://github.com/NousResearch/hermes-agent">Hermes</a> for end-to-end
        install, onboarding, and lifecycle management. Additional claw types are planned.
      </>
    ),
  },
  {
    title: '⚙️ Normalized Configuration',
    icon: <GearIcon />,
    description: (
      <>
        One config format for every claw. Define your preferences once and
        Clawrium translates them for each claw&apos;s native format.
      </>
    ),
  },
  {
    title: '🔓 Multi-Model Freedom',
    icon: <UnlockIcon />,
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
        <div className={styles.featureIcon}>{icon}</div>
      </div>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

function BeforeAfterSection(): ReactNode {
  return (
    <section className={styles.beforeAfter}>
      <div className="container">
        <Heading as="h2" className="text--center">Before &amp; After Clawrium</Heading>
        <div className="row">
          <div className={clsx('col col--6', styles.beforeAfterCol)}>
            <Heading as="h3">Before: Manual SSH chaos</Heading>
            <pre className={styles.asciiDiagram}>
{`You (laptop)
    │
    ├── SSH to pi-lab ──────> configure agent
    │                         restart service
    │                         check logs
    │                         update config...
    │
    ├── SSH to nuc-01 ──────> same manual steps
    │
    └── SSH to dev-box ─────> same manual steps
    
    ❌ No unified view
    ❌ Config drift between machines
    ❌ Manual secret management`}
            </pre>
          </div>
          <div className={clsx('col col--6', styles.beforeAfterCol)}>
            <Heading as="h3">After: One CLI, all agents</Heading>
            <pre className={styles.asciiDiagram}>
{`You (laptop + clm CLI)
    │
    └── clm ────┬── pi-lab ───> openclaw
                │
                ├── nuc-01 ───> openclaw
                │
                └── dev-box ──> hermes
    
    ✅ Single command center
    ✅ Consistent configuration
    ✅ Centralized secrets`}
            </pre>
          </div>
        </div>
        <div className={styles.clmPsOutput}>
          <Heading as="h4" className="text--center">See your entire fleet with one command:</Heading>
          <pre className={styles.terminalOutput}>
{`$ clm ps

HOST        AGENT          TYPE       STATUS    UPTIME
─────────────────────────────────────────────────────────
pi-lab      oc-discord     openclaw   running   3d 4h
nuc-01      oc-work        openclaw   running   12h
dev-box     hm-research    hermes     running   2h`}
          </pre>
        </div>
      </div>
    </section>
  );
}

function UseCasesSection(): ReactNode {
  return (
    <section className={styles.useCases}>
      <div className="container">
        <Heading as="h2" className="text--center">Who Uses Clawrium?</Heading>
        <div className="row">
          <div className={clsx('col col--4', styles.useCase)}>
            <Heading as="h3">Homelabbers</Heading>
            <p>
              Run AI assistants on your Raspberry Pis, NUCs, and spare hardware.
              Experiment with different models without cloud costs.
            </p>
          </div>
          <div className={clsx('col col--4', styles.useCase)}>
            <Heading as="h3">Teams</Heading>
            <p>
              Standardize agent deployment across developer machines.
              Share configurations and ensure everyone runs the same setup.
            </p>
          </div>
          <div className={clsx('col col--4', styles.useCase)}>
            <Heading as="h3">Small Orgs</Heading>
            <p>
              Deploy purpose-built agents for different departments.
              A research agent, a support agent, a coding agent - each isolated.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <>
      <BeforeAfterSection />
      <section className={styles.features}>
        <div className="container">
          <div className="row">
            {FeatureList.map((props, idx) => (
              <Feature key={idx} {...props} />
            ))}
          </div>
        </div>
      </section>
      <UseCasesSection />
    </>
  );
}

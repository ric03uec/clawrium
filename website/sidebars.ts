import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// Sidebar ordered for adoption funnel:
// 1. Quick wins first (Quickstart, Installation)
// 2. Practical guides
// 3. Agent surface area (Agent Support, Web Dashboard)
// 4. Operational sections (Scenarios, Host Configuration, Providers, Channels, Integrations)
// 5. Reference and architecture last

const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    'intro',
    'installation',
    {
      type: 'category',
      label: 'Guides',
      collapsed: false,
      items: [
        'guides/quickstart',
        'guides/host-setup',
        'guides/agent-onboarding',
        'guides/fleet-management',
      ],
    },
    {
      type: 'category',
      label: 'Agent Support',
      link: {
        type: 'doc',
        id: 'agent-support/index',
      },
      items: [
        'agent-support/openclaw',
        'agent-support/hermes',
        'agent-support/zeroclaw',
      ],
    },
    'web-dashboard',
    {
      type: 'category',
      label: 'Skills',
      collapsed: true,
      items: [
        'skills/intro',
        'skills/authoring',
      ],
    },
    {
      type: 'category',
      label: 'Scenarios',
      collapsed: true,
      items: [
        'scenarios/overview',
        'scenarios/101',
      ],
    },
    {
      type: 'category',
      label: 'Host Configuration',
      collapsed: true,
      items: [
        'host-configuration/overview',
        {
          type: 'category',
          label: 'OS Support',
          link: {
            type: 'doc',
            id: 'host-configuration/os-support/index',
          },
          collapsed: true,
          items: [
            {
              type: 'category',
              label: 'Ubuntu',
              collapsed: true,
              items: [
                'host-configuration/os-support/ubuntu/24-04',
              ],
            },
            'host-configuration/os-support/macos',
          ],
        },
      ],
    },
    {
      type: 'category',
      label: 'Providers',
      link: {
        type: 'doc',
        id: 'agent-support/providers/index',
      },
      items: [
        'agent-support/providers/anthropic',
        'agent-support/providers/openai',
        'agent-support/providers/openrouter',
        'agent-support/providers/bedrock',
        'agent-support/providers/vertex',
        'agent-support/providers/ollama',
        'agent-support/providers/zai',
        'agent-support/providers/azure-openai',
      ],
    },
    {
      type: 'category',
      label: 'Channels',
      link: {
        type: 'doc',
        id: 'agent-support/channels/index',
      },
      items: [
        'agent-support/channels/cli',
        'agent-support/channels/discord',
        'agent-support/channels/slack',
        'agent-support/channels/web',
        'agent-support/channels/whatsapp',
      ],
    },
    {
      type: 'category',
      label: 'Integrations',
      link: {
        type: 'doc',
        id: 'agent-support/integrations/index',
      },
      items: [
        'agent-support/integrations/github',
        'agent-support/integrations/atlassian',
        'agent-support/integrations/gitlab',
        'agent-support/integrations/linear',
        'agent-support/integrations/notion',
      ],
    },
    {
      type: 'category',
      label: 'Reference',
      items: [
        'reference/configuration',
        {
          type: 'category',
          label: 'CLI Commands',
          link: {
            type: 'doc',
            id: 'reference/cli/index',
          },
          items: [
            'reference/cli/host',
            'reference/cli/agent',
            'reference/cli/provider',
            'reference/cli/integration',
            'reference/cli/secret',
            'reference/cli/registry',
            'reference/cli/gui',
          ],
        },
      ],
    },
    'architecture',
    'troubleshooting',
    'contributing',
  ],
};

export default sidebars;

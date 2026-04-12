import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Clawrium',
  tagline: 'An aquarium for *claws',
  favicon: 'img/favicon.png',

  future: {
    v4: true,
  },

  url: 'https://ric03uec.github.io',
  baseUrl: '/clawrium/',

  organizationName: 'ric03uec',
  projectName: 'clawrium',
  trailingSlash: false,

  onBrokenLinks: 'throw',

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/ric03uec/clawrium/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themes: ['@docusaurus/theme-mermaid'],

  themeConfig: {
    image: 'img/clawrium-logo.png',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'Clawrium',
      logo: {
        alt: 'Clawrium Logo',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'tutorialSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          href: 'https://github.com/ric03uec/clawrium',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Documentation',
          items: [
            {
              label: 'Getting Started',
              to: '/docs/',
            },
            {
              label: 'Installation',
              to: '/docs/installation',
            },
            {
              label: 'Quickstart',
              to: '/docs/guides/quickstart',
            },
            {
              label: 'Architecture',
              to: '/docs/architecture',
            },
          ],
        },
        {
          title: 'Community',
          items: [
            {
              label: 'GitHub Issues',
              href: 'https://github.com/ric03uec/clawrium/issues',
            },
            {
              label: 'Discussions',
              href: 'https://github.com/ric03uec/clawrium/discussions',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'GitHub',
              href: 'https://github.com/ric03uec/clawrium',
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Clawrium. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'python', 'yaml'],
    },
    mermaid: {
      theme: {
        light: 'default',
        dark: 'dark',
      },
      options: {
        themeVariables: {
          primaryColor: '#0D9488',
          primaryTextColor: '#fff',
          primaryBorderColor: '#0F766E',
          lineColor: '#14B8A6',
          secondaryColor: '#5EEAD4',
          tertiaryColor: '#F0FDFA',
        },
      },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;

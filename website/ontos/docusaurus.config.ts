import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)
const BRAND_NAME = process.env.APP_BRAND_NAME || 'Ontos';

const config: Config = {
  title: BRAND_NAME,
  tagline: `${BRAND_NAME} from Databricks Labs`,
  favicon: '/img/ontos-logo2.svg',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  // Improve compatibility with the upcoming Docusaurus v4
  future: {
    v4: true, 
  },

  // Set the production url of your site here
  url: 'https://your-docusaurus-site.example.com',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/ontos/',

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'danielrozo-db', // Usually your GitHub org/user name.
  projectName: 'ontos.github.io', // Usually your repo name.

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'throw',
  onDuplicateRoutes: 'throw',
  onBrokenAnchors: 'throw',
  deploymentBranch: 'gh-pages',
  trailingSlash: false,

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  customFields: {
    brandName: BRAND_NAME,
  },

  plugins: [
    async (context, options) => {
      return {
        name: "docusaurus-plugin-tailwindcss",
        configurePostCss(postcssOptions) {
          postcssOptions.plugins = [
            require('@tailwindcss/postcss'),
            require('autoprefixer'),
          ];
          return postcssOptions;
        },
      }
    },
    'docusaurus-plugin-image-zoom',
    'docusaurus-lunr-search'
  ],

  presets: [
    [
      '@docusaurus/preset-classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          exclude: ['dev_guide/api_reference.md', 
            'dev_guide/custom_migrations.md',
            'admin_guide/**',
            'getting_started/install_local.md',
            'getting_started/demo_project.md',
            'troubleshooting.md'],
          // Please change this to your repo.
          // Remove this to remove the "edit this page" links.
          editUrl:
            'https://github.com/databrickslabs/ontos',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // Replace with your project's social card
    colorMode: {
      defaultMode: 'light',
      respectPrefersColorScheme: false,
    },
    navbar: {
      title: BRAND_NAME,
      logo: {
        alt: `${BRAND_NAME} Logo`,
        src: 'img/ontos-logo2.svg',
      },
      items: [
        {
          type: 'search',
          position: 'right',
        },
        {
          href: 'https://github.com/databrickslabs/ontos',
          position: 'right',

          className: 'header-github-link',
          'aria-label': 'GitHub repository',
        },

      ],
    },
    footer: {
      style: 'dark',
      links: [
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Copyright © 2025 Databricks Labs. Docs built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.oneLight,
      darkTheme: prismThemes.oneDark,
      additionalLanguages: ['bash']
    },
    zoom: {
      selector: 'article img',
      background: {
        light: '#F8FAFC',
        dark: '#F8FAFC',
      },
    }
  } satisfies Preset.ThemeConfig,
};

export default config;



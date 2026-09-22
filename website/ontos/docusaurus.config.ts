import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';
import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'Ontos',
  tagline: 'Ontos from Databricks Labs',
  favicon: '/img/ontos-logo2.svg',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  // Improve compatibility with the upcoming Docusaurus v4.
  // We enable the v4 flags individually rather than via `v4: true`, because two
  // of the implied flags don't work for this site yet:
  //  - fasterByDefault turns on the Docusaurus Faster (rspack) bundler, which
  //    requires the @docusaurus/faster package; we can't add that dependency
  //    here (its transitive deps aren't on our npm proxy), so we keep webpack.
  //  - mdx1CompatDisabledByDefault enables strict MDX, which breaks the
  //    `{#heading-id}` anchors in getting_started/install_databricks.md.
  // The remaining flags are safe and keep the site v4-ready.
  future: {
    v4: {
      removeLegacyPostBuildHeadAttribute: true,
      useCssCascadeLayers: true,
      siteStorageNamespacing: true,
      fasterByDefault: false,
      mdx1CompatDisabledByDefault: false,
    },
  },

  // Set the production url of your site here
  url: 'https://databrickslabs.github.io',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/ontos/',

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'databrickslabs', // Usually your GitHub org/user name.
  projectName: 'ontos', // Usually your repo name.

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'throw',
  onDuplicateRoutes: 'throw',
  onBrokenAnchors: 'throw',
  // Deployment is handled by the "Deploy Docs to GitHub Pages" GitHub Actions
  // workflow (Actions -> Pages artifact), so no deploymentBranch is needed here.
  // Only set this if you switch back to the classic `docusaurus deploy` command.
  // deploymentBranch: 'gh-pages',
  trailingSlash: false,

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
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
          exclude: ['admin_guide/jobs_workflows.md',
            'admin_guide/personas.md',
            'admin_guide/previews.md',
            'admin_guide/roles.md',
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
      title: 'Ontos',
      logo: {
        alt: 'Ontos Logo',
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





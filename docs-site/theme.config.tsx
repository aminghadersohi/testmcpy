import { useRouter } from 'next/router';
import type { DocsThemeConfig } from 'nextra-theme-docs';
import { useConfig } from 'nextra-theme-docs';

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';
const GITHUB_REPO_URL = 'https://github.com/preset-io/testmcpy';
const defaultSiteUrl = 'https://preset-io.github.io/testmcpy';
const defaultOgImage = `${defaultSiteUrl}/screenshots/mcp-explorer.png`;
const defaultDescription =
  'pytest for MCP servers — test, evaluate, and benchmark Model Context Protocol services with YAML test suites, 40+ evaluators, a CLI, and a web UI.';

const config: DocsThemeConfig = {
  logo: (
    <span style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
      <strong
        style={{
          fontSize: '20px',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          background: 'linear-gradient(90deg, #7aa2f7 0%, #bb9af7 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
        }}
      >
        testmcpy
      </strong>
    </span>
  ),
  project: {
    link: GITHUB_REPO_URL,
  },
  docsRepositoryBase: 'https://github.com/preset-io/testmcpy/tree/main/docs-site',

  navigation: {
    prev: true,
    next: true,
  },

  sidebar: {
    defaultMenuCollapseLevel: 1,
    toggleButton: true,
  },

  footer: {
    component: (
      <span style={{ padding: '1.5rem', fontSize: '0.875rem' }}>
        Apache 2.0 © {new Date().getFullYear()} Preset, Inc.
      </span>
    ),
  },

  toc: {
    backToTop: true,
  },

  editLink: {
    component: ({ filePath }) => (
      <a
        href={`https://github.com/preset-io/testmcpy/tree/main/docs-site/${filePath}`}
        target="_blank"
        rel="noreferrer"
      >
        Edit this page on GitHub →
      </a>
    ),
  },

  feedback: {
    content: 'Question? Give us feedback →',
    labels: 'documentation',
  },

  search: {
    placeholder: 'Search documentation...',
  },

  head: () => {
    const { frontMatter, title } = useConfig();
    const { asPath } = useRouter();

    const pathname = asPath?.split('#')[0]?.split('?')[0] ?? '/';
    const siteUrl = frontMatter.canonical ?? `${defaultSiteUrl}${pathname === '/' ? '' : pathname}`;

    const pageTitle = frontMatter.title ?? title ?? 'testmcpy';
    const description = frontMatter.description || defaultDescription;
    const fullTitle =
      pageTitle === 'testmcpy' ? 'testmcpy – pytest for MCP servers' : `${pageTitle} – testmcpy`;
    const rawOgImage = frontMatter.ogImage || frontMatter.image || defaultOgImage;
    const ogImage = rawOgImage.startsWith('http') ? rawOgImage : `${defaultSiteUrl}${rawOgImage}`;

    return (
      <>
        <title>{fullTitle}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />

        {/* Standard Meta Tags */}
        <meta name="description" content={description} />
        <meta
          name="keywords"
          content="MCP, Model Context Protocol, MCP testing, MCP server, LLM evaluation, tool calling, pytest for MCP, MCP evaluators, AI testing"
        />
        <meta name="author" content="Preset, Inc." />

        {/* Open Graph */}
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="testmcpy" />
        <meta property="og:title" content={fullTitle} />
        <meta property="og:description" content={description} />
        <meta property="og:image" content={ogImage} />
        <meta property="og:url" content={siteUrl} />

        {/* Twitter Card */}
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={fullTitle} />
        <meta name="twitter:description" content={description} />
        <meta name="twitter:image" content={ogImage} />

        {/* Additional Meta */}
        <meta name="theme-color" content="#1a1b26" />
        <link rel="icon" type="image/svg+xml" href={`${basePath}/favicon.svg`} />
        <link rel="canonical" href={siteUrl} />

        {/* JSON-LD Structured Data */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              '@context': 'https://schema.org',
              '@type': 'SoftwareApplication',
              name: 'testmcpy',
              description: defaultDescription,
              applicationCategory: 'DeveloperApplication',
              operatingSystem: 'macOS, Linux, Windows',
              offers: {
                '@type': 'Offer',
                price: '0',
                priceCurrency: 'USD',
              },
              url: siteUrl,
              codeRepository: GITHUB_REPO_URL,
              author: {
                '@type': 'Organization',
                name: 'Preset, Inc.',
              },
            }),
          }}
        />
      </>
    );
  },

  color: {
    hue: 221, // Tokyo Night blue (#7aa2f7)
    saturation: 85,
  },

  nextThemes: {
    defaultTheme: 'dark',
  },
};

export default config;

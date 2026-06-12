import nextra from 'nextra';

const withNextra = nextra({
  theme: 'nextra-theme-docs',
  themeConfig: './theme.config.tsx',
  defaultShowCopyCode: true,
});

// Deployed to GitHub Pages at https://preset-io.github.io/testmcpy
// (NEXT_PUBLIC_BASE_PATH=/testmcpy is set by the deploy workflow)
export default withNextra({
  reactStrictMode: true,
  output: 'export',
  images: {
    unoptimized: true,
  },
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || '',
});

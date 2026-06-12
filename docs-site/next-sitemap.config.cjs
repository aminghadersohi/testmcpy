/** @type {import('next-sitemap').IConfig} */
module.exports = {
  siteUrl: 'https://preset-io.github.io/testmcpy',
  generateRobotsTxt: false, // We use custom robots.txt in public/
  outDir: './out',
  changefreq: 'weekly',
  priority: 0.7,
  sitemapSize: 5000,
  exclude: ['/404', '/_app', '/_document', '*/_meta'],

  // Include static LLM-related files
  additionalPaths: async () => [{ loc: '/llms.txt', changefreq: 'monthly', priority: 0.3 }],

  transform: async (config, path) => {
    if (path === '/') {
      return {
        loc: path,
        changefreq: 'daily',
        priority: 1.0,
        lastmod: new Date().toISOString(),
      };
    }

    if (path.startsWith('/cli') || path.startsWith('/web-ui')) {
      return {
        loc: path,
        changefreq: 'weekly',
        priority: 0.9,
        lastmod: new Date().toISOString(),
      };
    }

    if (path.startsWith('/concepts') || path.startsWith('/guides')) {
      return {
        loc: path,
        changefreq: 'weekly',
        priority: 0.8,
        lastmod: new Date().toISOString(),
      };
    }

    return {
      loc: path,
      changefreq: config.changefreq,
      priority: config.priority,
      lastmod: new Date().toISOString(),
    };
  },
};

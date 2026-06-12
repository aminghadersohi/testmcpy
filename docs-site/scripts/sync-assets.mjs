// Copies canonical assets from the repo's docs/ directory into public/ so the
// docs site reuses them without duplicating binaries in git.
// Synced outputs (public/screenshots/, public/logo.svg) are gitignored.
import { cpSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(root);

const screenshotsSrc = join(repoRoot, 'docs', 'screenshots');
const screenshotsDest = join(root, 'public', 'screenshots');
const logoSrc = join(repoRoot, 'docs', 'logos', 'logo.svg');
const logoDest = join(root, 'public', 'logo.svg');

mkdirSync(screenshotsDest, { recursive: true });
cpSync(screenshotsSrc, screenshotsDest, { recursive: true });
cpSync(logoSrc, logoDest);

console.log(`Synced ${screenshotsSrc} -> ${screenshotsDest}`);
console.log(`Synced ${logoSrc} -> ${logoDest}`);

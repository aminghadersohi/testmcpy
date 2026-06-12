import Link from 'next/link';
import styles from './Hero.module.css';

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

export function Hero() {
  return (
    <div className={styles.hero}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`${basePath}/logo.svg`} alt="testmcpy" className={styles.logo} />
      <p className={styles.subtitle}>pytest for MCP servers</p>
      <p className={styles.description}>
        Test, evaluate, and benchmark Model Context Protocol services — YAML test suites, 40+
        built-in evaluators, multi-provider LLM support, CI gating, and a full web UI.
      </p>
      <div className={styles.buttons}>
        <Link href="/getting-started" className={styles.primaryButton}>
          Get Started
        </Link>
        <Link href="/cli" className={styles.secondaryButton}>
          CLI Reference
        </Link>
        <a
          href="https://github.com/preset-io/testmcpy"
          className={styles.secondaryButton}
          target="_blank"
          rel="noreferrer"
        >
          GitHub
        </a>
      </div>
      <div className={styles.quickstart}>
        <code>pip install testmcpy && testmcpy setup</code>
      </div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${basePath}/screenshots/mcp-explorer.png`}
        alt="testmcpy MCP Explorer"
        className={styles.screenshot}
      />
    </div>
  );
}

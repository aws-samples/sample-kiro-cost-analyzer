/**
 * i18n bundle-size observability report.
 *
 * Scans `frontend/dist/assets/` after a production build, identifies the
 * chunks that are i18n-relevant (dedicated locale-catalog chunks plus any
 * file that contains the i18next runtime inlined) and prints a summary
 * table of raw and gzipped sizes.
 *
 * Per Requirement 15.3 / 15.4 this is an **observed, not gated** report —
 * the script always exits 0 even when the dist directory is missing or a
 * file cannot be read. The output is informational: it lets maintainers
 * watch i18n-related bundle growth over time without blocking a release.
 *
 * Uses Node stdlib only (no new dependencies).
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const REPO_ROOT = resolve(__dirname, '..');
const ASSETS_DIR = resolve(REPO_ROOT, 'frontend/dist/assets');

/**
 * Heuristics for classifying a dist chunk as i18n-relevant. We operate on
 * filenames because Vite does not always emit a manifest.json (behavior
 * varies across Vite 5/8 configs). Each heuristic is a `(file) => label`
 * function returning a human-friendly category or `null` to skip.
 */
const CLASSIFIERS = [
  // Dedicated locale-catalog chunks (Vite emits one per dynamic-imported locale).
  (name) => (/^pt-BR-[A-Za-z0-9_-]+\.js$/.test(name) ? 'pt-BR catalog' : null),
  (name) => (/^en-[A-Za-z0-9_-]+\.js$/.test(name) ? 'en catalog' : null),
  // Cloudscape i18n messages, if they ended up as separate chunks.
  (name) =>
    /cloudscape.*i18n.*messages.*\.js$/i.test(name) ? 'Cloudscape i18n messages' : null,
];

/** Detects the main app chunk by filename pattern. Its size is reported for context. */
function isMainBundle(name) {
  return /^index-[A-Za-z0-9_-]+\.js$/.test(name);
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(2)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function safeReaddir(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return null;
  }
}

function rowFor(file) {
  const full = join(ASSETS_DIR, file);
  let raw, gzipped;
  try {
    const content = readFileSync(full);
    raw = content.byteLength;
    gzipped = gzipSync(content).byteLength;
  } catch (err) {
    return { file, label: '-', raw: null, gzipped: null, error: err.message };
  }

  for (const classify of CLASSIFIERS) {
    const label = classify(file);
    if (label) return { file, label, raw, gzipped };
  }
  if (isMainBundle(file)) {
    return { file, label: 'main bundle (for context)', raw, gzipped };
  }
  return null;
}

function printTable(rows) {
  if (rows.length === 0) {
    process.stdout.write('[report-i18n-sizes] No i18n-relevant chunks found in dist/assets.\n');
    return;
  }

  const header = ['Chunk', 'Category', 'Raw', 'Gzipped'];
  const body = rows.map((r) => [
    r.file,
    r.label,
    r.raw == null ? '—' : formatBytes(r.raw),
    r.gzipped == null ? '—' : formatBytes(r.gzipped),
  ]);

  const widths = header.map((h, i) =>
    Math.max(h.length, ...body.map((row) => row[i].length)),
  );

  const renderRow = (cells) =>
    cells.map((c, i) => c.padEnd(widths[i])).join('  ');

  const separator = widths.map((w) => '-'.repeat(w)).join('  ');

  process.stdout.write('\n[report-i18n-sizes] i18n bundle-size report\n');
  process.stdout.write(`  dist: ${ASSETS_DIR}\n`);
  process.stdout.write(`  ${renderRow(header)}\n`);
  process.stdout.write(`  ${separator}\n`);
  for (const row of body) {
    process.stdout.write(`  ${renderRow(row)}\n`);
  }
  process.stdout.write('\n');
}

function main() {
  const files = safeReaddir(ASSETS_DIR);
  if (files === null) {
    process.stdout.write(
      `[report-i18n-sizes] dist/assets not found at ${ASSETS_DIR}. ` +
        'Run `npm run build` first. Skipping report (this is informational only).\n',
    );
    process.exit(0);
  }

  const rows = files
    .filter((f) => {
      const ext = extname(f);
      return ext === '.js' || ext === '.json' || ext === '.css';
    })
    .filter((f) => {
      try {
        return statSync(join(ASSETS_DIR, f)).isFile();
      } catch {
        return false;
      }
    })
    .map(rowFor)
    .filter((r) => r !== null)
    // Put locale catalogs first so they are easy to spot.
    .sort((a, b) => {
      const rank = (label) =>
        label.includes('catalog') ? 0 : label.includes('messages') ? 1 : 2;
      return rank(a.label) - rank(b.label);
    });

  printTable(rows);

  // Always exit 0 — this is an observability-only report (Requirement 15.4).
  process.exit(0);
}

main();

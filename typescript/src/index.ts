import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { Readability } from '@mozilla/readability';
import { PlaywrightCrawler, RequestQueue } from 'crawlee';
import { franc } from 'franc-min';
import { iso6393 } from 'iso-639-3';
import { JSDOM } from 'jsdom';
import TurndownService from 'turndown';
import turndownPluginGfm from 'turndown-plugin-gfm';

type Manifest = Record<string, { content_hash: string; filename: string }>;

function arg(name: string, fallback?: string): string {
  const index = process.argv.indexOf(name);
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1];
  if (fallback !== undefined) return fallback;
  throw new Error(`missing ${name}`);
}

function normalizeLanguage(value: string): string {
  const language = value.trim().toLowerCase().replace('_', '-').split('-', 1)[0];
  if (!/^[a-z]{2}$/.test(language)) {
    throw new Error("language must be a two-letter code such as 'en' or 'tr'");
  }
  return language;
}

function sha256(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

function outputPath(outputDir: string, url: string): string {
  const parsed = new URL(url);
  const raw = parsed.pathname.replace(/^\/+|\/+$/g, '') || 'index';
  const slug = raw.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'index';
  return path.join(outputDir, `${slug}-${sha256(url).slice(0, 12)}.md`);
}

async function loadManifest(file: string): Promise<Manifest> {
  try {
    return JSON.parse(await readFile(file, 'utf8')) as Manifest;
  } catch {
    return {};
  }
}

async function saveManifest(file: string, manifest: Manifest): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp`;
  await writeFile(temporary, JSON.stringify(manifest, null, 2) + '\n', 'utf8');
  await rename(temporary, file);
}

function languageMatches(text: string, language: string): boolean {
  const expected = iso6393.find((entry) => entry.iso6391 === language)?.iso6393;
  if (!expected) throw new Error(`unsupported language code: ${language}`);
  const detected = franc(text);
  return detected === 'und' || detected === expected;
}

const startUrl = process.argv[2];
if (!startUrl || startUrl.startsWith('-')) throw new Error('start URL is required');

const language = normalizeLanguage(arg('--language', 'en'));
const outputDir = path.resolve(arg('--output-dir', 'docs'));
const stateDir = path.resolve(arg('--state-dir', 'storage/docsync'));
const hostname = new URL(startUrl).hostname;
const scopeId = sha256(startUrl.replace(/\/+$/, '')).slice(0, 12);
const manifestFile = path.join(stateDir, `${hostname}-${scopeId}.json`);

await mkdir(outputDir, { recursive: true });
await mkdir(stateDir, { recursive: true });

process.env.CRAWLEE_STORAGE_DIR = path.join(stateDir, 'crawlee', 'typescript', scopeId);
process.env.CRAWLEE_PURGE_ON_START = 'false';

const manifest = await loadManifest(manifestFile);
const queue = await RequestQueue.open('docsync');
const turndown = new TurndownService();
turndown.use(turndownPluginGfm.gfm);

const counters = { processed: 0, saved: 0, unchanged: 0 };
let outputWrite = Promise.resolve();

const crawler = new PlaywrightCrawler({
  requestQueue: queue,
  minConcurrency: 1,
  maxConcurrency: 2,
  maxRequestsPerMinute: 20,
  maxRequestsPerCrawl: 10_000,
  maxRequestRetries: 2,
  respectRobotsTxtFile: true,

  async requestHandler({ request, page, enqueueLinks }) {
    await enqueueLinks({ strategy: 'same-origin' });

    const url = request.loadedUrl ?? request.url;
    const dom = new JSDOM(await page.content(), { url });
    const article = new Readability(dom.window.document).parse();
    if (!article?.content || !article.textContent?.trim()) return;
    if (!languageMatches(article.textContent, language)) return;

    const markdown = turndown.turndown(article.content).trim();
    if (!markdown) return;

    outputWrite = outputWrite.then(async () => {
      const digest = sha256(markdown);
      const target = outputPath(outputDir, url);
      const previous = manifest[url];

      counters.processed += 1;
      try {
        await readFile(target);
        if (previous?.content_hash === digest) {
          counters.unchanged += 1;
        } else {
          await writeFile(target, markdown + '\n', 'utf8');
          counters.saved += 1;
        }
      } catch {
        await writeFile(target, markdown + '\n', 'utf8');
        counters.saved += 1;
      }

      manifest[url] = { content_hash: digest, filename: path.basename(target) };
      await saveManifest(manifestFile, manifest);
    });

    await outputWrite;
  },
});

await crawler.run([startUrl]);
await outputWrite;

if (await queue.isFinished()) await queue.drop();

console.log(
  `done processed=${counters.processed} saved=${counters.saved} unchanged=${counters.unchanged}`,
);

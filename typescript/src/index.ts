import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PlaywrightCrawler, RequestQueue } from 'crawlee';

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

async function toGfm(html: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const process = spawn('pandoc', ['--from=html', '--to=gfm', '--wrap=none']);
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];

    process.stdout.on('data', (chunk: Buffer) => stdout.push(chunk));
    process.stderr.on('data', (chunk: Buffer) => stderr.push(chunk));
    process.on('error', reject);
    process.on('close', (code) => {
      if (code === 0) {
        resolve(Buffer.concat(stdout).toString('utf8').trim());
      } else {
        reject(
          new Error(
            `pandoc exited with code ${code}: ${Buffer.concat(stderr).toString('utf8').trim()}`,
          ),
        );
      }
    });

    process.stdin.end(html);
  });
}

const startUrl = process.argv[2];
if (!startUrl || startUrl.startsWith('-')) throw new Error('start URL is required');

const language = normalizeLanguage(arg('--language', 'en'));
const outputDir = path.resolve(arg('--output-dir', 'docs'));
const stateDir = path.resolve(arg('--state-dir', 'storage/docsync'));
const hostname = new URL(startUrl).hostname;
const scopeRoot = startUrl.replace(/\/+$/, '');
const scopeGlob = `${scopeRoot}/**`;
const scopeId = sha256(scopeRoot).slice(0, 12);
const manifestFile = path.join(stateDir, `${hostname}.json`);

await mkdir(outputDir, { recursive: true });
await mkdir(stateDir, { recursive: true });

const crawlStorage = await mkdtemp(path.join(os.tmpdir(), `docsync-${scopeId}-`));
process.env.CRAWLEE_STORAGE_DIR = crawlStorage;
process.env.CRAWLEE_PURGE_ON_START = 'true';

const manifest = await loadManifest(manifestFile);
const counters = { processed: 0, saved: 0, unchanged: 0 };
let outputWrite = Promise.resolve();

try {
  const queue = await RequestQueue.open('docsync');
  const crawler = new PlaywrightCrawler({
    requestQueue: queue,
    minConcurrency: 1,
    maxConcurrency: 2,
    maxRequestsPerMinute: 20,
    maxRequestsPerCrawl: 10_000,
    maxRequestRetries: 2,
    respectRobotsTxtFile: true,

    async requestHandler({ request, page, enqueueLinks }) {
      await enqueueLinks({ strategy: 'same-origin', globs: [scopeGlob] });

      const pageLanguage = await page.evaluate(
        () => document.documentElement.lang || '',
      );
      if (pageLanguage && normalizeLanguage(pageLanguage) !== language) return;

      const html = await page.evaluate(() => {
        const mains = [...document.querySelectorAll('main')];
        if (!mains.length) return null;
        const main = mains.reduce((best, current) =>
          (current.textContent?.trim().length ?? 0) >
          (best.textContent?.trim().length ?? 0)
            ? current
            : best,
        );
        const root = main.cloneNode(true) as HTMLElement;
        root
          .querySelectorAll('script,style,noscript,template,svg,button,nav,aside')
          .forEach((element) => element.remove());
        root
          .querySelectorAll(
            '.sr-only,[aria-hidden="true"],[role="status"],[role="button"]',
          )
          .forEach((element) => element.remove());

        for (const pre of [...root.querySelectorAll('pre')]) {
          const code = pre.querySelector('code');
          const language =
            code?.getAttribute('data-language')?.trim() ||
            pre.getAttribute('data-language')?.trim() ||
            [...(code?.classList ?? [])]
              .find((value) => value.startsWith('language-'))
              ?.slice(9) ||
            [...pre.classList]
              .find((value) => value.startsWith('language-'))
              ?.slice(9) ||
            '';
          const cleanPre = document.createElement('pre');
          const cleanCode = document.createElement('code');
          if (language) cleanCode.className = language;
          cleanCode.textContent = code?.textContent ?? pre.textContent ?? '';
          cleanPre.appendChild(cleanCode);
          pre.replaceWith(cleanPre);
        }

        for (const span of [...root.querySelectorAll('span')]) {
          span.replaceWith(...span.childNodes);
        }
        return root.innerHTML;
      });
      if (!html) return;

      const markdown = await toGfm(html);
      if (!markdown) return;

      const url = request.loadedUrl ?? request.url;
      outputWrite = outputWrite.then(async () => {
        const digest = sha256(markdown);
        const target = outputPath(outputDir, url);
        const previous = manifest[url];
        let exists = true;
        try {
          await readFile(target);
        } catch {
          exists = false;
        }

        counters.processed += 1;
        if (exists && previous?.content_hash === digest) {
          counters.unchanged += 1;
        } else {
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
} finally {
  await rm(crawlStorage, { recursive: true, force: true });
}

console.log(
  `done processed=${counters.processed} saved=${counters.saved} unchanged=${counters.unchanged} output=${outputDir} state=${stateDir}`,
);

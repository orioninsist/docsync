import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { PlaywrightCrawler, RequestQueueV1 } from 'crawlee';
import { convert } from '@xberg-io/html-to-markdown';

type Manifest = Record<string, { content_hash: string; filename: string }>;

type Checkpoint = {
  version: number;
  status: 'running' | 'complete';
  engine: 'typescript';
  start_url: string;
  language: string;
};

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

function scopeRoot(startUrl: string): string {
  return startUrl.replace(/\/+$/, '');
}

function scopeId(startUrl: string): string {
  return sha256(scopeRoot(startUrl)).slice(0, 12);
}

function defaultOutputDir(startUrl: string): string {
  const hostname = new URL(startUrl).hostname;
  return path.join('docs', hostname, scopeId(startUrl));
}

function defaultStateDir(startUrl: string): string {
  const hostname = new URL(startUrl).hostname;
  return path.join('storage', 'docsync', hostname, scopeId(startUrl));
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

async function loadCheckpoint(file: string): Promise<Partial<Checkpoint>> {
  try {
    return JSON.parse(await readFile(file, 'utf8')) as Partial<Checkpoint>;
  } catch {
    return {};
  }
}

async function saveCheckpoint(file: string, checkpoint: Checkpoint): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp`;
  await writeFile(temporary, JSON.stringify(checkpoint, null, 2) + '\n', 'utf8');
  await rename(temporary, file);
}

async function prepareCrawlStorage(
  stateDir: string,
  startUrl: string,
  language: string,
  restart: boolean,
): Promise<{ storageDir: string; checkpointFile: string; resume: boolean }> {
  const crawlDir = path.join(stateDir, 'crawl', 'typescript');
  const storageDir = path.join(crawlDir, 'storage');
  const checkpointFile = path.join(crawlDir, 'checkpoint.json');
  const checkpoint = await loadCheckpoint(checkpointFile);

  const resume =
    !restart &&
    checkpoint.version === 1 &&
    checkpoint.status === 'running' &&
    checkpoint.start_url === startUrl &&
    checkpoint.language === language;

  if (!resume) {
    await rm(storageDir, { recursive: true, force: true });
  }

  await mkdir(storageDir, { recursive: true });
  await saveCheckpoint(checkpointFile, {
    version: 1,
    status: 'running',
    engine: 'typescript',
    start_url: startUrl,
    language,
  });

  return { storageDir, checkpointFile, resume };
}

function toGfm(html: string): string {
  return convert(html).content?.trim() ?? '';
}

const startUrl = process.argv[2];
if (!startUrl || startUrl.startsWith('-')) throw new Error('start URL is required');

const language = normalizeLanguage(arg('--language', 'en'));
const headful = process.argv.includes('--headful');
const restart = process.argv.includes('--restart');
const maxRequestsPerCrawl = Number.parseInt(arg('--max-requests', '10000'), 10);
if (!Number.isInteger(maxRequestsPerCrawl) || maxRequestsPerCrawl < 1) {
  throw new Error('--max-requests must be a positive integer');
}
const outputDir = path.resolve(arg('--output-dir', defaultOutputDir(startUrl)));
const stateDir = path.resolve(arg('--state-dir', defaultStateDir(startUrl)));
const hostname = new URL(startUrl).hostname;
const crawlScopeRoot = scopeRoot(startUrl);
const scopeGlob = `${crawlScopeRoot}/**`;
const manifestFile = path.join(stateDir, `${hostname}.json`);

await mkdir(outputDir, { recursive: true });
await mkdir(stateDir, { recursive: true });

const { storageDir: crawlStorage, checkpointFile, resume } =
  await prepareCrawlStorage(stateDir, startUrl, language, restart);

process.env.CRAWLEE_STORAGE_DIR = crawlStorage;
process.env.CRAWLEE_PURGE_ON_START = resume ? 'false' : 'true';

const manifest = await loadManifest(manifestFile);
const counters = { processed: 0, saved: 0, unchanged: 0 };
let outputWrite = Promise.resolve();

const queue = await RequestQueueV1.open('docsync');

{
  const crawler = new PlaywrightCrawler({
    requestQueue: queue,
    headless: !headful,
    launchContext: {
      useIncognitoPages: headful,
    },
    minConcurrency: 1,
    maxConcurrency: 2,
    maxRequestsPerMinute: 20,
    maxRequestsPerCrawl,
    maxRequestRetries: 2,
    respectRobotsTxtFile: true,
    experiments: {
      requestLocking: false,
    },

    async requestHandler({ request, page, enqueueLinks }) {
      const pageLanguage = await page.evaluate(
        () => document.documentElement.lang || '',
      );
      const shouldProcess =
        !pageLanguage || normalizeLanguage(pageLanguage) === language;

      const html = shouldProcess ? await page.evaluate(() => {
        const candidates = [...document.querySelectorAll('main')];
        if (!candidates.length) candidates.push(...document.querySelectorAll('article'));
        if (!candidates.length && document.body) candidates.push(document.body);
        if (!candidates.length) return null;
        const documentRoot = candidates.reduce((best, current) =>
          (current.textContent?.trim().length ?? 0) >
          (best.textContent?.trim().length ?? 0)
            ? current
            : best,
        );
        const root = documentRoot.cloneNode(true) as HTMLElement;
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
            pre.getAttribute('syntax')?.trim() ||
            [...(code?.classList ?? [])]
              .find((value) => value.startsWith('language-'))
              ?.slice(9) ||
            [...pre.classList]
              .find((value) => value.startsWith('language-'))
              ?.slice(9) ||
            '';
          const cleanPre = document.createElement('pre');
          const cleanCode = document.createElement('code');
          if (language) cleanCode.className = `language-${language.toLowerCase()}`;
          cleanCode.textContent = code?.textContent ?? pre.textContent ?? '';
          cleanPre.appendChild(cleanCode);
          pre.replaceWith(cleanPre);
        }

        for (const span of [...root.querySelectorAll('span')]) {
          span.replaceWith(...span.childNodes);
        }
        return root.innerHTML;
      }) : null;

      const markdown = html ? toGfm(html) : '';

      if (markdown) {
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
          await mkdir(path.dirname(target), { recursive: true });
          await writeFile(target, markdown + '\n', 'utf8');
          counters.saved += 1;
        }

          manifest[url] = {
            content_hash: digest,
            filename: path.basename(target),
          };
          await saveManifest(manifestFile, manifest);
        });
        await outputWrite;
      }

      await enqueueLinks({
        strategy: 'same-origin',
        globs: [scopeGlob],
        waitForAllRequestsToBeAdded: true,
      });
    },
  });

  const statistics = await crawler.run([startUrl]);
  await outputWrite;

  if (statistics.requestsFailed > 0) {
    throw new Error(`crawl failed: ${statistics.requestsFailed} request(s) failed`);
  }

  const stoppedAtRequestLimit = statistics.requestsTotal >= maxRequestsPerCrawl;
  if (!stoppedAtRequestLimit && await queue.isFinished()) {
    await saveCheckpoint(checkpointFile, {
      version: 1,
      status: 'complete',
      engine: 'typescript',
      start_url: startUrl,
      language,
    });
  }
}

console.log(
  `done processed=${counters.processed} saved=${counters.saved} unchanged=${counters.unchanged} output=${outputDir} state=${stateDir}`,
);

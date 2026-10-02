import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { PlaywrightCrawler, RequestQueueV1, RobotsTxtFile, Sitemap } from 'crawlee';
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

const TRACKING_QUERY_PARAMETERS = new Set([
  'dclid',
  'fbclid',
  'gclid',
  'msclkid',
]);

function canonicalizeUrl(rawUrl: string): string {
  const url = new URL(rawUrl);
  url.hash = '';

  for (const key of [...url.searchParams.keys()]) {
    const normalizedKey = key.toLowerCase();
    if (normalizedKey.startsWith('utm_') || TRACKING_QUERY_PARAMETERS.has(normalizedKey)) {
      url.searchParams.delete(key);
    }
  }

  return url.toString();
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
const maxRequestsRaw = process.argv.includes('--max-requests') ? arg('--max-requests') : undefined;
const maxRequestsPerCrawl = maxRequestsRaw === undefined ? undefined : Number.parseInt(maxRequestsRaw, 10);
if (maxRequestsPerCrawl !== undefined && (!Number.isInteger(maxRequestsPerCrawl) || maxRequestsPerCrawl < 1)) {
  throw new Error('--max-requests must be a positive integer');
}
const crawlStrategy = arg('--crawl-strategy', 'same-origin') as 'same-origin' | 'same-hostname' | 'same-domain';
if (!['same-origin', 'same-hostname', 'same-domain'].includes(crawlStrategy)) {
  throw new Error('--crawl-strategy must be same-origin, same-hostname, or same-domain');
}
const discoverSitemap = !process.argv.includes('--no-sitemap');
const outputDir = path.resolve(arg('--output-dir'));
const stateDir = path.resolve(arg('--state-dir'));
const hostname = new URL(startUrl).hostname;
const manifestFile = path.join(stateDir, `${hostname}.json`);

await mkdir(outputDir, { recursive: true });
await mkdir(stateDir, { recursive: true });

const { storageDir: crawlStorage, checkpointFile, resume } =
  await prepareCrawlStorage(stateDir, startUrl, language, restart);

process.env.CRAWLEE_STORAGE_DIR = crawlStorage;
process.env.CRAWLEE_PURGE_ON_START = resume ? 'false' : 'true';

const manifest = await loadManifest(manifestFile);
const counters = { processed: 0, saved: 0, unchanged: 0, removed: 0 };
const seenUrls = new Set<string>();
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
    ...(maxRequestsPerCrawl === undefined ? {} : { maxRequestsPerCrawl }),
    maxRequestRetries: 2,
    respectRobotsTxtFile: true,
    experiments: {
      requestLocking: false,
    },

    async requestHandler({ request, page, enqueueLinks }) {
      await page.locator('main, article, body').first().waitFor({ state: 'attached', timeout: 5000 });
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
          .querySelectorAll('script,style,noscript,template,svg,button,nav')
          .forEach((element) => element.remove());
        root
          .querySelectorAll(
            '.sr-only,[aria-hidden="true"],[role="status"]',
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
        const url = canonicalizeUrl(request.loadedUrl ?? request.url);
        outputWrite = outputWrite.then(async () => {
        seenUrls.add(url);
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
        strategy: crawlStrategy,
        waitForAllRequestsToBeAdded: true,
        transformRequestFunction: (request) => {
          request.url = canonicalizeUrl(request.url);
          return request;
        },
      });
    },
  });

  if (discoverSitemap) {
    const sitemapUrls = new Set<string>();
    try {
      const robots = await RobotsTxtFile.find(startUrl);
      for (const url of await robots.parseUrlsFromSitemaps({ enqueueStrategy: crawlStrategy })) sitemapUrls.add(url);
    } catch (error) {
      console.warn('Unable to discover sitemaps from robots.txt:', error);
    }
    try {
      const sitemap = await Sitemap.tryCommonNames(new URL(startUrl).origin);
      for (const url of sitemap.urls) sitemapUrls.add(url);
    } catch (error) {
      console.warn('Unable to discover common sitemaps:', error);
    }
    if (sitemapUrls.size) {
      await crawler.addRequests([...sitemapUrls].map(canonicalizeUrl));
    }
  }

  const statistics = await crawler.run([canonicalizeUrl(startUrl)]);
  await outputWrite;

  const stoppedAtRequestLimit =
    maxRequestsPerCrawl !== undefined && statistics.requestsTotal >= maxRequestsPerCrawl;
  const crawlComplete = !stoppedAtRequestLimit && await queue.isFinished();
  if (crawlComplete) {
    if (!resume) {
      for (const [url, entry] of Object.entries(manifest)) {
        if (seenUrls.has(url)) continue;
        await rm(path.join(outputDir, entry.filename), { force: true });
        delete manifest[url];
        counters.removed += 1;
      }
      await saveManifest(manifestFile, manifest);
    }
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
  `done processed=${counters.processed} saved=${counters.saved} unchanged=${counters.unchanged} removed=${counters.removed} output=${outputDir} state=${stateDir}`,
);

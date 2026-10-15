import { createHash, randomUUID } from 'node:crypto';
import { mkdir, open, readFile, rename, rm, unlink } from 'node:fs/promises';
import path from 'node:path';
import { PlaywrightCrawler, RequestQueueV1, RobotsTxtFile, SitemapRequestList } from 'crawlee';
import { execFileSync } from 'node:child_process';
import { archiveHtml } from './html_archive.js';

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

function urlIsWithinStartScope(startUrl: string, candidateUrl: string): boolean {
  const start = new URL(canonicalizeUrl(startUrl));
  const candidate = new URL(canonicalizeUrl(candidateUrl));

  if (candidate.protocol !== start.protocol || candidate.host !== start.host) {
    return false;
  }

  const rootPath =
    start.pathname === '/' ? '' : start.pathname.replace(/\/+$/, '');
  const candidatePath =
    candidate.pathname === '/' ? '' : candidate.pathname.replace(/\/+$/, '');

  if (!rootPath) {
    return true;
  }

  return candidatePath === rootPath || candidatePath.startsWith(`${rootPath}/`);
}



function urlMatchesLanguage(rawUrl: string, language: string): boolean {
  const selected = normalizeLanguage(language);
  const values = [...new URL(rawUrl).searchParams.entries()]
    .filter(([key]) => key.toLowerCase() === 'hl')
    .map(([, value]) => value);

  return values.every((value) => {
    if (!value.trim()) return false;
    try {
      return normalizeLanguage(value) === selected;
    } catch {
      return false;
    }
  });
}


function outputPath(outputDir: string, url: string): string {
  const parsed = new URL(url);
  const raw = parsed.pathname.replace(/^\/+|\/+$/g, '') || 'index';
  const slug = raw.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'index';
  return path.join(outputDir, `${slug}-${sha256(url).slice(0, 12)}.md`);
}


async function atomicWrite(file: string, content: string): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  const temporary = path.join(
    path.dirname(file),
    `.${path.basename(file)}.${randomUUID()}.tmp`,
  );

  try {
    const handle = await open(temporary, 'wx');
    try {
      await handle.writeFile(content, 'utf8');
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, file);
  } finally {
    await unlink(temporary).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    });
  }
}

async function loadManifest(file: string): Promise<Manifest> {
  try {
    return JSON.parse(await readFile(file, 'utf8')) as Manifest;
  } catch {
    return {};
  }
}

async function saveManifest(file: string, manifest: Manifest): Promise<void> {
  await atomicWrite(file, JSON.stringify(manifest, null, 2) + '\n');
}

async function loadCheckpoint(file: string): Promise<Partial<Checkpoint>> {
  try {
    return JSON.parse(await readFile(file, 'utf8')) as Partial<Checkpoint>;
  } catch {
    return {};
  }
}

async function saveCheckpoint(file: string, checkpoint: Checkpoint): Promise<void> {
  await atomicWrite(file, JSON.stringify(checkpoint, null, 2) + '\n');
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
  if (!html.trim()) {
    throw new Error('Empty HTML input');
  }

  const markdown = execFileSync(
    'pandoc',
    ['--from=html', '--to=gfm-raw_html', '--wrap=none'],
    {
      input: html,
      encoding: 'utf8',
      timeout: 120_000,
      maxBuffer: 64 * 1024 * 1024,
    },
  ).trim();

  if (!markdown) {
    throw new Error('Pandoc produced empty Markdown');
  }

  const validator = process.env.DOCSYNC_GFM_VALIDATOR || 'docsync-gfm-validator';
  execFileSync(validator, [], {
    input: markdown,
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 64 * 1024 * 1024,
  });

  return markdown;
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
  const sitemapSources = new Set<string>();

  if (discoverSitemap) {
    try {
      const robots = await RobotsTxtFile.find(startUrl);
      for (const url of robots.getSitemaps({ enqueueStrategy: crawlStrategy })) {
        sitemapSources.add(url);
      }
    } catch (error) {
      console.warn('Unable to discover sitemaps from robots.txt:', error);
    }

    sitemapSources.add(
      new URL('/sitemap.xml', new URL(startUrl).origin).toString(),
    );
  }

  const sitemapRequestList = discoverSitemap
    ? await SitemapRequestList.open({
        sitemapUrls: [...sitemapSources],
        enqueueStrategy: crawlStrategy,
        regexps: [
          new RegExp(
            `^${new URL(startUrl).origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}${new URL(startUrl).pathname.replace(/\/+$/, '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:/|\\?|$)`,
          ),
        ],
        exclude: [
          new RegExp(
            `[?&]hl=(?!${language}(?:[-_][a-zA-Z]+)?(?:&|$))[^&#]*`,
            'i',
          ),
        ],
        persistStateKey: 'DOCSYNC_SITEMAP_REQUEST_LIST',
      })
    : undefined;

  const crawler = new PlaywrightCrawler({
    requestQueue: queue,
    ...(sitemapRequestList ? { requestList: sitemapRequestList } : {}),
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
      const requestedUrl = canonicalizeUrl(request.loadedUrl ?? request.url);
      const originalUrl = canonicalizeUrl(request.url);
      const isStartRequest = originalUrl === canonicalizeUrl(startUrl);

      if (
        !isStartRequest &&
        (!urlIsWithinStartScope(startUrl, requestedUrl) ||
          !urlMatchesLanguage(requestedUrl, language))
      ) {
        return;
      }

      await page.locator('main, article, body').first().waitFor({ state: 'attached', timeout: 5000 });
      const pageLanguage = await page.evaluate(
        () => document.documentElement.lang || '',
      );
      const shouldProcess =
        !pageLanguage || normalizeLanguage(pageLanguage) === language;

      if (shouldProcess) {
        const originalHtml = await page.content();
        await archiveHtml(originalHtml, stateDir);
      }

      const html = shouldProcess ? await page.evaluate(() => {
        const root =
          document.querySelector('main') ||
          document.querySelector('article') ||
          document.body;

        if (!root) return null;

        const content = root.cloneNode(true) as HTMLElement;

        content.querySelectorAll('script,style').forEach(
          element => element.remove()
        );

        return content.innerHTML;
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
          await atomicWrite(target, markdown + '\n');
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
          const url = canonicalizeUrl(request.url);
          if (!urlIsWithinStartScope(startUrl, url) || !urlMatchesLanguage(url, language)) {
            return false;
          }
          request.url = url;
          return request;
        },
      });
    },
  });

  const statistics = await crawler.run([canonicalizeUrl(startUrl)]);
  await outputWrite;

  const stoppedAtRequestLimit =
    maxRequestsPerCrawl !== undefined && statistics.requestsTotal >= maxRequestsPerCrawl;
  const crawlComplete =
    !stoppedAtRequestLimit &&
    await queue.isFinished() &&
    (!sitemapRequestList ||
      (sitemapRequestList.isSitemapFullyLoaded() &&
        await sitemapRequestList.isFinished()));
  if (crawlComplete) {

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

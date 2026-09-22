# docsync

Documentation crawler and incremental Markdown synchronizer built on Crawlee Python 1.10.1.

## Requirements

- Python 3.13+
- uv
- Playwright browser binaries when browser rendering is used

Install:

```bash
uv sync
uv run playwright install chromium
```

## Usage

Adaptive HTTP-first crawling:

```bash
uv run docsync https://example.com/docs
```

Explicit browser mode:

```bash
uv run docsync https://example.com/docs \
  --mode playwright \
  --browser-type chromium
```

Useful options:

```text
--output-dir PATH
--state-dir PATH
--max-concurrency N
--max-requests N
--requests-per-minute N
--language {en,tr}
--refresh-hours N
--force-refresh
--mode {http,playwright}
--show-browser
--browser-type {chromium,firefox,webkit}
```

Run `uv run docsync --help` for the canonical CLI reference.

## Architecture

DocsSync keeps crawler responsibilities in Crawlee and owns only project-specific synchronization policy.

```text
docsync
├── Crawlee
│   ├── persistent FileSystemStorageClient / RequestQueue
│   ├── ThrottlingRequestManager
│   ├── concurrency and request-rate limits
│   ├── retries and robots.txt handling
│   ├── SitemapRequestLoader
│   ├── native link enqueue transforms
│   └── AdaptivePlaywrightCrawler / PlaywrightCrawler
└── DocsSync policy
    ├── URL scope and normalization
    ├── English / Turkish selection
    ├── Markdown conversion
    └── incremental URL metadata
```

`http` uses Crawlee's `AdaptivePlaywrightCrawler` with its BeautifulSoup static parser. Crawlee owns escalation to Playwright when the static result is not meaningful.

`playwright` uses Crawlee's `PlaywrightCrawler` directly.

## Persistent state and resume

Use the same `--state-dir` across repeated runs.

```text
<state-dir>/
├── <hostname>_url_state.json
└── crawlee/
    └── crawl/
        └── <hostname>/
            └── ...
```

Interrupted or otherwise incomplete crawls preserve request storage for resume. A completed crawl may drop its request storage.

The URL-state JSON is DocsSync's incremental metadata store. It records successful saves and HTTP validators used to avoid unnecessary downloads.

```bash
uv run docsync https://example.com/docs \
  --output-dir /mnt/local/docs/example/markdown \
  --state-dir /mnt/local/docs/example/state \
  --refresh-hours 24
```

`--force-refresh` bypasses the refresh-window decision.

## Sitemap and discovery

DocsSync uses Crawlee's native `SitemapRequestLoader` and native `enqueue_links` transform path. DocsSync adds only scope, excluded-resource, language, and incremental policy.

## Language policy

Supported target languages are `en` and `tr`. URL language hints provide an early filter; downloaded HTML is then classified before Markdown is saved.

## Project structure

```text
src/docsync/
├── __init__.py
├── __main__.py
├── cli.py
├── config.py
├── crawl_engine.py
├── crawler.py
├── crawler_runtime.py
├── incremental.py
├── language.py
├── markdown.py
├── metrics.py
├── sitemap.py
└── url_security.py
```

Canonical entry points:

```text
docsync           -> docsync.cli:main
python -m docsync -> docsync.__main__
```

## Development

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src tests
```

Tests cover DocsSync product behavior rather than source shape or Crawlee internals.

## License

MIT.

# docsync

Documentation crawler and incremental Markdown synchronizer built on Crawlee Python 1.10.1.

## Requirements

- Python 3.13+
- uv
- Playwright browser binaries only when using `--mode playwright`

Install:

```bash
uv sync
uv run playwright install chromium
```

## Usage

Static or automatically escalated crawling:

```bash
uv run docsync https://example.com/docs
```

Explicit browser mode:

```bash
uv run docsync https://example.com/docs \
  --mode playwright \
  --browser-type chromium
```

Inventory-only discovery:

```bash
uv run docsync https://example.com/docs --inventory-only
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
--inventory-only
```

Run `uv run docsync --help` for the canonical CLI reference.

## Current architecture

docsync keeps Crawlee responsibilities in Crawlee and only owns project-specific policy.

```text
docsync
├── Crawlee runtime
│   ├── persistent FileSystemStorageClient
│   ├── named RequestQueue
│   ├── ThrottlingRequestManager
│   ├── concurrency / RPM limits
│   ├── retries and robots.txt handling
│   ├── native sitemap loading
│   ├── native link extraction / enqueueing
│   └── HTTP / adaptive / Playwright crawler execution
└── docsync policy
    ├── URL scope and normalization
    ├── language policy
    ├── Markdown conversion
    ├── incremental URL state
    ├── crawl / inventory reports
    └── terminal UI
```

### Crawl modes

`http` uses Crawlee's `AdaptivePlaywrightCrawler` with the BeautifulSoup static parser. Static parsing is attempted first and Crawlee owns escalation to browser rendering when the adaptive result is not meaningful.

`playwright` uses Crawlee's `PlaywrightCrawler` directly.

There is no separate custom HTTP-to-browser fallback subsystem.

### Persistent request storage

Crawl request state is persistent on disk under the selected state directory.

For a crawl:

```text
<state-dir>/
├── <hostname>_url_state.json
└── crawlee/
    └── crawl/
        └── <hostname>/
            └── ...
```

For inventory:

```text
<state-dir>/
├── site-inventory.json
└── crawlee/
    └── inventory/
        └── <hostname>/
            └── ...
```

A completed crawl may drop its request storage. Interrupted or otherwise incomplete crawls preserve request storage so the run can resume.

The URL-state JSON is the single docsync incremental metadata store. It contains save timestamps, output filenames, content hashes, ETag values, and Last-Modified values.

## Incremental synchronization

Use the same `--state-dir` across repeated runs.

```bash
uv run docsync https://example.com/docs \
  --output-dir /mnt/local/docs/example/markdown \
  --state-dir /mnt/local/docs/example/state \
  --refresh-hours 24
```

`--force-refresh` ignores the refresh-window decision and requests pages again.

## Sitemap and discovery

docsync uses Crawlee's native `SitemapRequestLoader`. It probes these conventional sitemap locations on the target origin:

```text
/sitemap.xml
/sitemap_index.xml
/sitemap.txt
/sitemap.xml.gz
```

HTML link discovery uses Crawlee context link extraction and enqueueing. docsync applies only its scope and language policy around that native behavior.

## Language policy

Supported target languages:

```text
en
tr
```

URL language hints are used as an early filter. Downloaded HTML is then classified before Markdown is saved.

## Project structure

```text
src/docsync/
├── __main__.py
├── cli.py
├── config.py
├── crawl_engine.py
├── crawler.py
├── crawler_runtime.py
├── incremental.py
├── inventory.py
├── language.py
├── language_strategy.py
├── markdown.py
├── metrics.py
├── playwright_rendering.py
├── progress_events.py
├── sitemap.py
├── terminal_ui.py
└── url_security.py
```

The canonical application entry points are:

```text
docsync              -> docsync.cli:main
python -m docsync    -> docsync.__main__
```

There is no root `main.py` compatibility launcher.

## Development

Run the current quality checks:

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src tests
```

The test suite should describe current behavior, not implementation-shape contracts from removed architectures.

## License

MIT.

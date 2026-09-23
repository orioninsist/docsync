# DocsSync

DocsSync is a thin command-line documentation synchronizer.

Its design rule is simple:

> Native capability first. Minimal glue only where product-specific behavior is unavoidable.

DocsSync does **not** implement its own crawler, browser engine, retry system, request queue, language detector, HTML-to-Markdown converter, or site-specific scraping framework.

## Architecture

```text
docsync CLI
  |
  |-- argparse / asyncio / subprocess / pathlib          [Python stdlib]
  |
  |-- Playwright runtime bootstrap                        [Playwright]
  |
  |-- Crawlee PlaywrightCrawler                           [Crawlee native]
  |     |-- browser crawling
  |     |-- same-origin link discovery
  |     |-- RequestQueue
  |     |-- persistent crawl state / resume
  |     |-- retries
  |     |-- concurrency
  |     |-- requests-per-minute throttling
  |     |-- robots.txt handling
  |
  |-- rendered HTML
  |
  |-- Trafilatura                                         [Trafilatura native]
  |     |-- main-content extraction
  |     |-- Markdown conversion
  |     |-- links
  |     |-- tables
  |     |-- target-language filtering
  |
  |-- py3langid                                           [Trafilatura language detector]
  |
  '-- DocsSync output policy                              [minimal glue]
        |-- stable filename from URL
        |-- SHA-256 content fingerprint
        |-- skip rewriting unchanged Markdown
        '-- JSON manifest for URL -> hash / filename
```

## Ownership

| Responsibility | Owner | Type |
| --- | --- | --- |
| CLI argument parsing | Python `argparse` | stdlib |
| Async execution | Python `asyncio` | stdlib |
| Browser runtime installation | Playwright CLI | native tool |
| Browser crawling | Crawlee `PlaywrightCrawler` | native |
| Link discovery | Crawlee `enqueue_links(strategy="same-origin")` | native |
| Request queue / deduplication | Crawlee `RequestQueue` | native |
| Persistent crawl state / resume | Crawlee storage | native |
| Request throttling | Crawlee `ThrottlingRequestManager` | native |
| Concurrency | Crawlee `ConcurrencySettings` | native |
| Retry handling | Crawlee crawler | native |
| robots.txt | Crawlee crawler | native |
| Rendered DOM | Playwright through Crawlee | native |
| Main-content extraction | Trafilatura | native |
| Markdown conversion | Trafilatura | native |
| Link preservation / absolute URL conversion | Trafilatura | native |
| Table extraction | Trafilatura | native |
| Language filtering | Trafilatura + `py3langid` | native |
| URL parsing | Python `urllib.parse` | stdlib |
| Stable output filenames | DocsSync | minimal glue |
| Content fingerprint | Python `hashlib.sha256` | stdlib |
| Output manifest | Python `json` + `pathlib` | minimal glue |
| Unchanged-file skip | DocsSync | minimal glue |

## CLI

Basic usage:

```bash
uv sync
uv run docsync https://example.com/docs --language en
```

Chromium is installed automatically on first use if the Playwright Chromium runtime is missing.

Full public CLI surface:

```text
docsync URL
  [--language LANGUAGE]
  [--output-dir OUTPUT_DIR]
  [--state-dir STATE_DIR]
```

Example:

```bash
uv run docsync https://example.com/docs \
  --language en \
  --output-dir ./docs \
  --state-dir ./storage/docsync
```

### Public parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `url` | required | Documentation start URL |
| `--language` | `en` | Two-letter target language such as `en` or `tr` |
| `--output-dir` | `docs` | Markdown output directory |
| `--state-dir` | `storage/docsync` | Crawlee state + DocsSync manifest directory |

## Internal defaults

These are intentionally not exposed as CLI flags.

| Setting | Value | Owner |
| --- | ---: | --- |
| crawler | `PlaywrightCrawler` | Crawlee |
| discovery strategy | `same-origin` | Crawlee |
| minimum concurrency | `1` | Crawlee |
| desired concurrency | `2` | Crawlee |
| maximum concurrency | `2` | Crawlee |
| maximum requests per crawl | `10000` | Crawlee |
| maximum tasks per minute | `20` | Crawlee |
| maximum request retries | `2` | Crawlee |
| respect robots.txt | `true` | Crawlee |
| purge crawl storage on start | `false` | Crawlee configuration |
| Markdown comments | excluded | Trafilatura |
| Markdown links | included | Trafilatura |
| Markdown tables | included | Trafilatura |
| output format | `markdown` | Trafilatura |

## Data flow

For each invocation:

```text
start URL
  -> Crawlee persistent RequestQueue
  -> PlaywrightCrawler
  -> rendered page HTML
  -> same-origin links added by Crawlee
  -> Trafilatura extraction
  -> py3langid target-language check
  -> Markdown
  -> SHA-256 fingerprint
  -> stable URL-derived filename
  -> write only when new or changed
```

Crawl state and output state are separate concerns:

- Crawlee owns pending-request persistence and interrupted-run resume.
- DocsSync stores only the URL-to-content-fingerprint/filename manifest needed for output synchronization.

## Output behavior

A URL always maps to a deterministic filename based on:

```text
readable URL path slug + first 12 characters of SHA-256(URL)
```

This means:

- the same URL keeps the same filename;
- different URLs remain collision-resistant;
- changing page content does not rename the file;
- unchanged extracted Markdown is not rewritten.

DocsSync writes plain Markdown files and plain terminal output.

## What DocsSync intentionally does not contain

There is no:

- custom crawler engine;
- custom browser controller;
- custom retry implementation;
- custom request frontier;
- custom concurrency or rate limiter;
- custom robots.txt parser;
- custom sitemap engine;
- custom HTML-to-Markdown implementation;
- custom language detector;
- site-specific selectors;
- domain-specific rules;
- HTTP-vs-browser mode;
- TUI or Rich interface.

The project is intentionally an orchestration layer over established native capabilities.

## Project layout

```text
docsync/
├── .gitignore
├── .python-version
├── LICENSE
├── README.md
├── pyproject.toml
├── uv.lock
└── src/
    └── docsync/
        ├── __init__.py
        ├── __main__.py
        ├── cli.py
        └── crawler.py
```

Generated local data such as `.venv/`, tool caches, `docs/`, and `storage/` is ignored by Git.

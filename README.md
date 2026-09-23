# DocsSync

DocsSync is a thin command-line documentation synchronizer built on Crawlee Python and Trafilatura.

DocsSync does not implement its own crawling or extraction framework. Crawlee owns browser crawling, link discovery, request queues, persistence, retries, concurrency, throttling, robots.txt handling, and interrupted-run resume. Trafilatura owns main-content extraction, Markdown conversion, links, tables, and target-language filtering.

DocsSync adds only small product policy: stable Markdown filenames and content fingerprints so unchanged documents are not rewritten.

## Usage

```bash
uv sync
uv run docsync https://example.com/docs --language en
```

Chromium is installed automatically on first use when the Playwright runtime is missing.

Optional paths:

```bash
uv run docsync https://example.com/docs \
  --language en \
  --output-dir ./docs \
  --state-dir ./storage/docsync
```

Use `--help` for the complete command-line interface.

## Behavior

DocsSync uses Crawlee's native `PlaywrightCrawler` and follows same-origin links. Crawl state is persisted by Crawlee so interrupted work can resume.

Rendered HTML is passed directly to Trafilatura. Trafilatura extracts the main content, filters for the requested language, and produces Markdown.

DocsSync stores a SHA-256 content fingerprint for each URL. Unchanged Markdown is not rewritten; changed content updates the existing stable file for that URL.

## Output

The output is plain Markdown files and plain terminal text. There is no TUI, Rich interface, site-specific selector configuration, or custom crawler engine.

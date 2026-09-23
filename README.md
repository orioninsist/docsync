# DocsSync

DocsSync is a small command-line documentation synchronizer built directly on Crawlee Python.

It is intentionally thin: Crawlee owns crawling, discovery, request queues, persistence, retries, concurrency, robots.txt handling, and resume behavior. DocsSync adds only documentation-specific policy:

- choose a language;
- save documentation as Markdown;
- avoid rewriting unchanged content;
- resume an interrupted crawl through Crawlee's persistent storage.

## Usage

```bash
uv sync
uv run playwright install chromium
uv run docsync https://example.com/docs
```

Common options:

```bash
uv run docsync https://example.com/docs \
  --language en \
  --output-dir ./docs \
  --state-dir ./storage \
  --mode http
```

Use `--help` for the complete command-line interface.

## Modes

`http` uses Crawlee's native `AdaptivePlaywrightCrawler`: static HTTP parsing is preferred and Crawlee can fall back to Playwright when browser rendering is required.

`playwright` uses Crawlee's native `PlaywrightCrawler`.

## State

Crawlee owns crawl/request persistence and interrupted-run resume.

DocsSync stores only documentation synchronization metadata such as content hashes and HTTP validators. That state is used to decide whether already-synchronized content needs to be written again.

## Output

The interface is plain terminal text. There is no TUI or Rich-based interface.

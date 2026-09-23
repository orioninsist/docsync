# DocsSync

DocsSync is a thin command-line documentation synchronizer.

> Native capability first. Minimal glue only where product-specific behavior is unavoidable.

DocsSync does not implement a crawler framework. One CLI selects either the native Python or TypeScript engine and wires established tools together.

## Architecture

```text
docsync CLI
  ├─ --engine python
  │    └─ Crawlee Python / PlaywrightCrawler
  │         └─ Trafilatura → Markdown + target-language filtering
  │
  └─ --engine typescript
       └─ Crawlee TypeScript / PlaywrightCrawler
            └─ Readability → Turndown + GFM → Markdown
                 └─ franc-min language filtering
```

Both engines use Crawlee/Playwright for browser crawling, request queues, retries, concurrency, throttling, robots.txt handling, link discovery, and persistent crawl storage.

DocsSync adds only the small product policy shared by both engines: start-URL scope, stable URL-derived filenames, SHA-256 content fingerprints, engine-specific manifests, and skipping unchanged Markdown.

## CLI

Install/sync the Python environment:

```bash
uv sync
```

Basic usage:

```bash
uv run docsync https://example.com/docs --engine python --language en
```

TypeScript engine:

```bash
uv run docsync https://example.com/docs --engine typescript --language en
```

Chromium is installed automatically when the required Playwright Chromium runtime is missing.

Public CLI:

```text
docsync URL
  [--engine {python,typescript}]
  [--language LANGUAGE]
  [--output-dir OUTPUT_DIR]
  [--state-dir STATE_DIR]
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `url` | required | Documentation start URL |
| `--engine` | `python` | Native engine implementation |
| `--language` | `en` | Two-letter target language such as `en` or `tr` |
| `--output-dir` | `docs` | Markdown output directory |
| `--state-dir` | `storage/docsync` | Persistent DocsSync manifest directory |

## Engines

### Python

```text
Crawlee Python / PlaywrightCrawler
  → rendered HTML
  → Trafilatura
  → target-language filtering
  → Markdown
```

Python owns no crawler lifecycle itself. Crawlee provides the browser crawler, queue, retries, robots.txt support, concurrency, throttling, and discovery. Its request/storage data is temporary for the duration of a run. Trafilatura provides generic main-content extraction and Markdown conversion.

### TypeScript

```text
Crawlee TypeScript / PlaywrightCrawler
  → rendered HTML
  → Mozilla Readability
  → Turndown + GFM
  → franc-min language filtering
  → Markdown
```

The TypeScript implementation is a separate native Crawlee engine. The Python CLI only dispatches to it; the crawl itself runs as the TypeScript process.

## Scope

The supplied start URL defines the documentation tree.

For example:

```text
https://example.com/docs
```

allows that path and descendants such as:

```text
https://example.com/docs/guide
https://example.com/docs/api/reference
```

The crawler does not intentionally expand into unrelated same-origin paths outside the start-URL tree. No site-specific selectors or domain rules are used.

## Internal defaults

These are intentionally fixed rather than exposed as CLI flags.

| Setting | Value |
| --- | ---: |
| maximum concurrency | `2` |
| maximum requests per crawl | `10000` |
| maximum requests/tasks per minute | `20` |
| maximum request retries | `2` |
| respect robots.txt | `true` |
| crawl storage | operating-system temporary directory |

## Output and state

A URL maps to a stable filename:

```text
readable URL-path slug + first 12 characters of SHA-256(URL)
```

Each engine computes a SHA-256 fingerprint of its extracted Markdown. Existing Markdown is not rewritten when the fingerprint is unchanged.

Markdown is written incrementally as each document is successfully extracted. Results are not buffered in a Crawlee Dataset until the crawl finishes.

Persistent state is intentionally minimal. Each hostname has one JSON manifest directly under the selected `--state-dir`:

```text
STATE_DIR/
└── developers.openai.com.json
```

The manifest maps each URL to its content hash and Markdown filename:

```json
{
  "https://developers.openai.com/example": {
    "content_hash": "<sha256>",
    "filename": "example-<url-hash>.md"
  }
}
```

Python and TypeScript use the same manifest format and hostname-based filename. Crawlee's request queues and other operational storage are not persisted under `--state-dir`; they are created in an operating-system temporary directory for the current run and removed when the run exits normally.

Because crawl storage is temporary, DocsSync does not promise request-queue resume after an interrupted process or system restart. Already written Markdown remains durable, and the persistent manifest allows unchanged content to be recognized on later runs.

## Data flow

```text
start URL
  → selected native Crawlee engine
  → Playwright-rendered HTML
  → engine extraction / language filtering
  → Markdown
  → SHA-256 fingerprint
  → stable filename
  → write only when new or changed
```

The Python and TypeScript extractors can legitimately produce different document counts or Markdown for the same site. Each engine is deterministic against its own output/state.


## Operational notes

DocsSync uses conservative defaults for documentation crawling rather than maximum throughput. These values are fixed internally for both engines:

- maximum concurrency: `2`
- maximum requests per minute: `20`
- maximum requests per crawl: `10000`
- maximum request retries: `2`
- robots.txt: respected
- crawl scope: the supplied start-URL tree only

These defaults reduce load and limit accidental over-crawling, but they are not a universal guarantee for every target. DocsSync still performs real HTTP(S) requests and renders pages in Chromium, so target-site rules, rate limits, authentication boundaries, and authorization requirements still apply.

## Tool inventory

This is the complete tool/library inventory used by the project. It is intentionally explicit so the automation can be understood later without reading the source code.

| Tool / library | Engine | Role |
| --- | --- | --- |
| Python + `argparse` / `asyncio` / `subprocess` / `pathlib` | dispatcher / Python | CLI parsing, process dispatch, paths, small orchestration glue |
| uv | both | Python environment, dependency sync, and `docsync` command execution |
| Crawlee Python | Python | crawler lifecycle, queue, persistence, retries, robots.txt, concurrency, throttling, discovery |
| Playwright + Chromium | Python | browser runtime and rendered pages |
| Trafilatura | Python | main-content extraction, Markdown conversion, links/tables, target-language filtering |
| py3langid | Python | language detector used by Trafilatura |
| npm | TypeScript | TypeScript dependency/script runner |
| tsx | TypeScript | executes `typescript/src/index.ts` |
| Crawlee TypeScript | TypeScript | crawler lifecycle, queue, persistence, retries, robots.txt, concurrency, throttling, discovery |
| Playwright + Chromium | TypeScript | browser runtime and rendered pages |
| JSDOM | TypeScript | DOM representation for extracted rendered HTML |
| Mozilla Readability | TypeScript | main article/content extraction |
| Turndown | TypeScript | HTML-to-Markdown conversion |
| turndown-plugin-gfm | TypeScript | GitHub-Flavored Markdown support |
| franc-min | TypeScript | language detection |
| iso-639-3 | TypeScript | maps two-letter language input to ISO 639-3 codes used by language detection |
| SHA-256 (Python `hashlib` / Node `crypto`) | both | stable URL IDs and content fingerprints |
| JSON/filesystem primitives | both | engine-specific manifest and output-state persistence |

Development-only tools are separate from runtime: Ruff and mypy check the Python code; TypeScript/`tsc --noEmit` checks the TypeScript code.

### What one command automates

```text
uv run docsync URL --engine python|typescript ...
        │
        ├─ prepares the selected runtime when needed
        ├─ starts the selected native Crawlee engine
        ├─ opens/render pages through Playwright + Chromium
        ├─ discovers links inside the start-URL scope
        ├─ applies the fixed crawl limits and robots.txt policy
        ├─ extracts the main content with the selected engine's extractor stack
        ├─ filters for the requested language
        ├─ converts the result to Markdown
        ├─ fingerprints content and skips unchanged files
        ├─ writes Markdown to --output-dir
        ├─ persists one hostname-named manifest under --state-dir
        └─ prints Crawlee native progress plus the final DocsSync summary
```

So DocsSync itself is primarily the orchestration/policy layer. Crawling, browser rendering, extraction, Markdown conversion, and language detection are delegated to the established tools above.

## Toolchain used by each command

Python engine:

```bash
uv run docsync URL --engine python --language en
```

```text
Python CLI
  → Crawlee Python
  → Playwright / Chromium
  → Trafilatura
  → Markdown output
  → SHA-256 manifest/state update
```

TypeScript engine:

```bash
uv run docsync URL --engine typescript --language en
```

```text
Python CLI dispatcher
  → npm / tsx
  → Crawlee TypeScript
  → Playwright / Chromium
  → JSDOM
  → Mozilla Readability
  → Turndown + turndown-plugin-gfm
  → franc-min + iso-639-3 language check
  → Markdown output
  → SHA-256 manifest/state update
```

Development checks use Ruff and mypy for Python and `tsc --noEmit` for TypeScript.

At the end of every successful run, DocsSync adds one compact summary after Crawlee's native progress/statistics output:

```text
done processed=N saved=N unchanged=N output=/absolute/output/path state=/absolute/state/path
```

`processed`, `saved`, and `unchanged` summarize the synchronized documents; `output` shows where Markdown was written and `state` shows the local persistent state root. Crawlee's own native progress and statistics remain unchanged.

## Files created at runtime

DocsSync creates durable output/state and temporary crawler working data.

### Markdown output

The directory passed with `--output-dir` contains synchronized `.md` files. A document is written as soon as it is successfully extracted and is new or changed.

### Persistent state

The directory passed with `--state-dir` contains one JSON manifest per hostname:

```text
STATE_DIR/
└── HOSTNAME.json
```

For example:

```text
state/
└── developers.openai.com.json
```

The manifest stores URL → content hash / filename mappings used to skip unchanged Markdown. It is written atomically through a short-lived `.tmp` file.

Python and TypeScript share this manifest layout. Running different extraction engines against the same hostname can update the same URL entries because their extracted Markdown can differ.

### Temporary crawl storage

Crawlee's request queues, key-value stores, and other internal operational files live under an operating-system temporary directory such as `/tmp/docsync-...` on Linux. They are working data, not DocsSync's durable state, and are removed when the run exits normally. The operating system may also clean temporary storage.

This intentionally trades persistent request-queue resume for a small durable state surface. If a crawl is interrupted, Markdown already written and manifest entries already saved remain available, but the next run starts with a fresh Crawlee request queue.

Local dependency/cache directories such as `.venv/`, `node_modules/`, and tool caches are not part of the user-facing output.

## What DocsSync intentionally does not contain

There is no custom crawler engine, browser controller, retry system, request frontier, rate limiter, robots.txt parser, HTML-to-Markdown implementation, site-specific selector set, domain-specific rule set, browser-vs-HTTP mode, TUI, or Rich interface.

The project is intentionally a small orchestration layer over established tools.

## Project layout

```text
docsync/
├── README.md
├── pyproject.toml
├── uv.lock
├── src/
│   └── docsync/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       └── crawler.py
└── typescript/
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    └── src/
        ├── index.ts
        └── turndown-plugin-gfm.d.ts
```

Generated local data such as virtual environments, tool caches, documentation output, and crawl state is ignored by Git.

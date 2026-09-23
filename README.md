# DocsSync

DocsSync synchronizes rendered documentation pages to GitHub-Flavored Markdown through one CLI and two interchangeable Crawlee engines.

## Architecture

```text
                         docsync
                           │
                 --engine python|typescript
                           │
              ┌────────────┴────────────┐
              │                         │
       Crawlee Python             Crawlee TypeScript
              │                         │
              └────── Playwright ───────┘
                           │
                    rendered DOM
                           │
                 semantic <main>
                           │
                  DOM normalization
                           │
                         Pandoc
                           │
                          GFM
                           │
                 Markdown + shared state
```

The engine changes only the Crawlee runtime. Both paths use the same document policy: the largest rendered `<main>`, semantic DOM cleanup, canonical code blocks, Pandoc's `gfm` writer, stable filenames, SHA-256 content fingerprints, and the same hostname manifest.

## Requirements

- Python 3.10+
- uv
- Pandoc
- Node.js + npm when using the TypeScript engine
- Chromium through Playwright

Install the Python environment:

```bash
uv sync
```

TypeScript dependencies are installed automatically on the first TypeScript run. Chromium is installed automatically when the selected Playwright runtime is missing.

## CLI

Python engine:

```bash
uv run docsync https://example.com/docs \
  --engine python \
  --language en \
  --output-dir docs \
  --state-dir storage/docsync
```

TypeScript engine:

```bash
uv run docsync https://example.com/docs \
  --engine typescript \
  --language en \
  --output-dir docs \
  --state-dir storage/docsync
```

Public interface:

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
| `--engine` | `python` | Crawlee runtime |
| `--language` | `en` | Two-letter page language |
| `--output-dir` | `docs` | Markdown output directory |
| `--state-dir` | `storage/docsync` | Persistent manifest directory |

## Document pipeline

Each rendered page is reduced to its largest `<main>` element. Presentation-only elements are removed, heading text is unwrapped from decorative spans, and `<pre>/<code>` blocks are rebuilt from their text content so syntax-highlighting markup and line-number UI cannot leak into Markdown.

Language metadata from `data-language` and `language-*` classes is retained as a canonical code class before conversion. Pandoc then converts the normalized HTML with:

```text
--from=html --to=gfm --wrap=none
```

This keeps both Crawlee engines on one Markdown serializer and one content-hash standard.

The requested `--language` is compared with the rendered page's HTML language when the page declares one. Pages without a declared HTML language are not discarded solely for lacking that metadata.

## Crawl policy

The start URL defines the crawl tree. For example, `https://example.com/docs` allows descendants such as `/docs/guide` and `/docs/api/reference`. Discovery stays on the same origin and inside the start-URL path glob.

The crawl settings are intentionally fixed and equal in both engines:

| Setting | Value |
| --- | ---: |
| minimum concurrency | `1` |
| maximum concurrency | `2` |
| maximum requests per minute | `20` |
| maximum requests per crawl | `10000` |
| maximum request retries | `2` |
| respect robots.txt | `true` |

Crawlee operational storage is created under the operating-system temporary directory for each run and is not part of persistent DocsSync state.

## Output and shared state

A URL maps to a stable Markdown filename:

```text
URL-path slug + first 12 characters of SHA-256(URL)
```

DocsSync hashes the canonical GFM output. If the stored hash matches and the Markdown file still exists, the file is left unchanged.

Persistent state is one JSON manifest per hostname:

```text
STATE_DIR/
└── developers.openai.com.json
```

Each entry contains only the content hash and filename:

```json
{
  "https://developers.openai.com/example": {
    "content_hash": "<sha256>",
    "filename": "example-<url-hash>.md"
  }
}
```

Python and TypeScript read and update this same manifest. Switching engines does not reset, namespace, or rebuild it. Existing URL entries remain in place; new URLs are added and changed URLs are updated.

Writes are incremental. Each successful document is written immediately, and the manifest is atomically replaced through a temporary file.

## Runtime behavior

Crawlee owns crawling, queues, retries, throttling, robots.txt handling, concurrency, discovery, browser lifecycle, and native statistics. DocsSync does not add a second progress framework or custom crawler lifecycle.

At the end of a successful run, DocsSync prints one compact summary:

```text
done processed=N saved=N unchanged=N output=/absolute/output/path state=/absolute/state/path
```

Because request-queue storage is temporary, an interrupted process does not resume its in-flight queue. Markdown and manifest entries already written remain durable.

## Project layout

```text
docsync/
├── README.md
├── pyproject.toml
├── src/
│   └── docsync/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       └── crawler.py
└── typescript/
    ├── package.json
    ├── tsconfig.json
    └── src/
        └── index.ts
```

Dependency lockfiles are generated from the current manifests by `uv sync` and `npm install`.

## Design boundary

DocsSync intentionally contains no custom browser controller, request frontier, retry engine, rate limiter, robots.txt parser, Markdown parser, site-specific selector set, TUI, or Rich interface.

The project is a small policy layer over Crawlee, Playwright, the browser DOM, and Pandoc.

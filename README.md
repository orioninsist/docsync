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
                  html-to-markdown
                           │
                          GFM
                           │
                 Markdown + shared state
```

The engine changes only the Crawlee runtime. Both paths use the same document policy: the largest rendered `<main>`, semantic DOM cleanup, canonical code blocks, html-to-markdown 3.14.3, stable filenames, SHA-256 content fingerprints, and the same hostname manifest.

## Quick start with Docker

Docker is the recommended path when you want the project to behave the same on Linux, macOS, and Windows.

If you are preparing this repository on one computer and want to run it later on Windows 11, push the project to GitHub first:

```bash
git add .
git commit -m "Add Docker setup"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/docsync.git
git push -u origin main
```

If the `origin` remote already exists, use this instead of `git remote add`:

```bash
git remote set-url origin https://github.com/YOUR_GITHUB_USERNAME/docsync.git
git push -u origin main
```

Build the local image:

```bash
docker compose build
```

Run a sync with the Python engine:

```bash
docker compose run --rm docsync sync https://example.com/docs --engine python
```

Run a sync with the TypeScript engine:

```bash
docker compose run --rm docsync sync https://example.com/docs --engine typescript
```

Generated Markdown and persistent crawl state use separate default roots. Markdown is written directly under `/home/murat/Media/5-Documentation/<site-name>/`, while manifests and operational crawl state are written under `/home/murat/Media/8-Document/docsync/<site-name>/`.

### Windows notes

Use Windows 11 with Docker Desktop installed and running. During Docker Desktop setup, enable the WSL 2 backend. Then open PowerShell or Windows Terminal and clone the GitHub repository:

```powershell
git clone https://github.com/YOUR_GITHUB_USERNAME/docsync.git
cd docsync
```

Build the Docker image:

```powershell
docker compose build
```

Run the CLI help command to confirm everything is working:

```powershell
docker compose run --rm docsync --help
```

Run a real sync with the Python engine:

```powershell
docker compose run --rm docsync sync https://example.com/docs --engine python
```

Run the same sync with the TypeScript engine:

```powershell
docker compose run --rm docsync sync https://example.com/docs --engine typescript
```

Replace `https://example.com/docs` with the documentation URL you want to convert. Generated Markdown is written directly under `/home/murat/Media/5-Documentation/<site-name>/` by default.

If you prefer plain `docker run`, use `${PWD}` in PowerShell:

```powershell
docker build -t docsync:local .
docker run --rm -v ${PWD}:/workspace docsync:local sync https://example.com/docs
```

In `cmd.exe`, use `%cd%`:

```bat
docker build -t docsync:local .
docker run --rm -v %cd%:/workspace docsync:local sync https://example.com/docs
```

### Docker permission notes

If Docker is installed but `docker compose build` fails with a socket permission error, the current user cannot access the Docker daemon. On Linux, add the user to the Docker group and open a new login session:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker compose build
```

If `sudo` asks for a password, run those commands in your normal terminal. On Windows, start Docker Desktop first and confirm that WSL integration is enabled for the distro that contains this repository.

## Local requirements

- Python 3.10+
- uv
- html-to-markdown 3.14.3 (Python and Node bindings)
- Node.js + npm when using the TypeScript engine
- Chromium through Playwright

Install the Python environment:

```bash
uv sync
```

Prepare browser/runtime dependencies explicitly:

```bash
uv run docsync setup
```

This installs the selected Playwright Chromium runtime and, for the TypeScript engine, installs Node dependencies with `npm ci`. Sync runs do not silently install dependencies unless `--install-runtime` is passed.

## CLI

Python engine:

```bash
uv run docsync sync https://example.com/docs \
  --engine python \
  --language en
```

TypeScript engine:

```bash
uv run docsync sync https://example.com/docs \
  --engine typescript \
  --language en
```

Public interface:

```text
docsync setup [--engine {python,typescript,all}]

docsync sync URL
  [--engine {python,typescript}]
  [--language LANGUAGE]
  [--output-dir OUTPUT_DIR]
  [--state-dir STATE_DIR]
  [--install-runtime]
  [--headful]
  [--restart]
```

The legacy `docsync URL` form is still accepted and maps to `docsync sync URL`.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `url` | required | Documentation start URL |
| `--engine` | `python` | Crawlee runtime |
| `--language` | `en` | Two-letter page language |
| `--output-dir` | `/home/murat/Media/5-Documentation/<site-name>` | Markdown output directory; an explicit value overrides the default |
| `--state-dir` | `/home/murat/Media/8-Document/docsync/<site-name>` | Persistent manifest and crawl-state directory; an explicit value overrides the default |
| `--restart` | off | Discard resumable operational crawl progress and start from the root URL |

## Document pipeline

Each rendered page is reduced to its largest `<main>` element. Presentation-only elements are removed, heading text is unwrapped from decorative spans, and `<pre>/<code>` blocks are rebuilt from their text content so syntax-highlighting markup and line-number UI cannot leak into Markdown.

Language metadata from `data-language`, `syntax`, and existing `language-*` classes is retained as a canonical `language-*` code class before conversion. Both engines then convert the normalized HTML with html-to-markdown 3.14.3.

The Python engine uses the `html-to-markdown` Python binding and the TypeScript engine uses `@xberg-io/html-to-markdown`. Both are pinned to 3.14.3 so equivalent normalized HTML follows the same Markdown serialization and content-hash standard.

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
| retry blocked sessions | `false` |
| respect robots.txt | `true` |

Crawlee operational request-queue storage is persistent. If a crawl is interrupted, the next run with the same engine, start URL, language, and state directory resumes the unfinished queue. Python and TypeScript keep separate operational storage because their Crawlee storage formats are engine-specific.

Use `--restart` to discard an unfinished engine-specific queue and start again from the root URL. This does not delete generated Markdown or the shared content manifest.

## Output and shared state

A URL maps to a stable Markdown filename:

```text
URL-path slug + first 12 characters of SHA-256(URL)
```

DocsSync hashes the canonical GFM output. If the stored hash matches and the Markdown file still exists, the file is left unchanged.

By default, DocsSync stores synchronized Markdown under `/home/murat/Media/5-Documentation` and persistent crawler state under `/home/murat/Media/8-Document/docsync`. The start URL is converted into the same filesystem-safe site directory for both roots by joining its hostname and path segments with hyphens. Query strings and fragments are not part of the directory name. Markdown files are written directly inside the site directory; no additional hostname subdirectory is created.

For example:

```text
https://github.com/niri-wm/niri/wiki
        ↓

Markdown output:
/home/murat/Media/5-Documentation/
└── github.com-niri-wm-niri-wiki/
    ├── niri-Getting-Started-<url-hash>.md
    ├── niri-Configuration-<url-hash>.md
    └── ...

DocsSync state:
/home/murat/Media/8-Document/docsync/
└── github.com-niri-wm-niri-wiki/
    ├── github.com.json
    └── crawl/
```

This means the normal command can stay short:

```bash
uv run docsync sync https://github.com/niri-wm/niri/wiki
```

For `https://example.com/docs`, the defaults are:

```text
/home/murat/Media/5-Documentation/example.com-docs
/home/murat/Media/8-Document/docsync/example.com-docs
```

`--output-dir` and `--state-dir` remain available when a caller needs to override either generated path. The documentation tree is intentionally kept free of checkpoint, request-queue, and manifest files; those belong under the separate DocsSync state root.

The scoped state directory contains the shared content manifest plus engine-specific operational crawl state:

```text
STATE_DIR/
├── developers.openai.com.json
└── crawl/
    ├── python/
    │   ├── checkpoint.json
    │   └── storage/
    └── typescript/
        ├── checkpoint.json
        └── storage/
```

The hostname JSON file is shared by both engines. Each manifest entry contains only the content hash and filename:

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

Crawlee owns crawling, queues, retries, throttling, robots.txt handling, concurrency, discovery, browser lifecycle, and native statistics. DocsSync does not add a second progress framework or custom crawler lifecycle. DocsSync disables repeated blocked-session rotation so HTTP 403 responses such as Cloudflare challenges fail fast instead of cycling through multiple sessions.

At the end of a successful run, DocsSync prints one compact summary:

```text
done processed=N saved=N unchanged=N output=/absolute/output/path state=/absolute/state/path
```

If a process is interrupted while a crawl is active, its checkpoint remains `running` and the next matching run resumes the persisted request queue. When the queue finishes successfully, the checkpoint becomes `complete`; a later normal sync starts a fresh crawl while reusing the shared content manifest to avoid rewriting unchanged Markdown. `--restart` forces that fresh-crawl behavior even when a `running` checkpoint exists.

## Verification

Run the local quality checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
cd typescript && npm run check
```

The pytest suite includes a local HTTP integration test that runs both crawler engines against the same redirecting documentation fixture and verifies identical Markdown output and shared manifest state.

Run the same checks through Docker:

```bash
docker compose run --rm docsync --help
docker compose run --rm --entrypoint bash docsync -lc "cd /app && /app/.venv/bin/pytest && cd typescript && npm run check"
```

The included devcontainer uses the same Dockerfile for reproducible local development.

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
│       ├── crawler.py
│       └── policy.py
├── tests/
│   ├── test_parity.py
│   └── test_policy.py
├── Dockerfile
├── compose.yaml
└── typescript/
    ├── package.json
    ├── tsconfig.json
    └── src/
        └── index.ts
```

Dependency lockfiles are generated from the current manifests by `uv lock` and `npm install --package-lock-only`. Runtime installs use `uv sync --locked` and `npm ci`.

## Design boundary

DocsSync intentionally contains no custom browser controller, request frontier, retry engine, rate limiter, robots.txt parser, Markdown parser, site-specific selector set, TUI, or Rich interface.

The project is a small policy layer over Crawlee, Playwright, the browser DOM, and html-to-markdown.

Hata, `pyproject.toml` dosyasının paket açıklaması için `README.md` beklemesinden kaynaklanıyor. Aşağıdaki komut eksik dosyayı oluşturur, bağımlılıkları senkronize eder ve projeyi yeniden çalıştırır.


# docsync

A safe, incremental documentation crawler built with Crawlee for Python.

## Run

```bash
uv run python main.py https://example.com/docs
````

README.md dosyasını proje mimarisi, dosya sayıları, kod satırları, modül ilişkileri, çalışma akışı ve tüm çalıştırma komutlarıyla tamamen yeniliyorum. Aşağıdaki tek komut README.md dosyasını oluşturur ve sonunda `cat README.md` ile tamamını terminalde gösterir.

````bash
cd /mnt/local/areas/docsync && cat > README.md <<'README'
# docsync

`docsync` is a Crawlee for Python project that crawls documentation websites, extracts meaningful page content, converts it to normalized Markdown, avoids duplicate work, supports incremental synchronization, optionally renders JavaScript pages with Playwright, and writes crawl metrics and persistent state.

---

# 1. Project Summary

| Item | Value |
|---|---:|
| Project name | `docsync` |
| Version | `0.1.0` |
| Required Python | `>=3.13` |
| Canonical CLI command | `uv run docsync` |
| Canonical entry point | `docsync.cli:main` |
| Production package | `src/docsync/` |
| Production Python modules | `16` |
| Test and verification files | `32` |
| Total Python files analyzed | `56` |
| Total analyzed repository files | `398` |
| Full pytest result | `316 passed` |
| Ruff result | `All checks passed` |
| Mypy result | `Success: no issues found` |
| README size after architecture generation | `486 lines` |
| Browser rendering | Playwright |
| HTTP crawling | Crawlee BeautifulSoup crawler |
| Persistent state | JSON and Crawlee storage |
| Output format | Markdown and JSON reports |

---

# 2. Main Features

| Feature | Implementation |
|---|---|
| HTTP crawling | Crawlee `BeautifulSoupCrawler` |
| JavaScript rendering | Crawlee Playwright crawler |
| Sitemap discovery | XML sitemap and `robots.txt` discovery |
| URL security | HTTP/HTTPS validation, same-origin checks, redirect protection |
| Request limiting | Requests-per-minute configuration |
| Crawl delay | Shared asynchronous delay throttle |
| Incremental synchronization | URL timestamp state and content hashes |
| Duplicate detection | Persistent duplicate-content registry |
| Markdown generation | HTML cleanup and normalized Markdown export |
| Language filtering | English-page detection |
| Atomic state writes | Temporary file plus atomic replacement |
| Metrics | Crawl counters, duration, saved/skipped/failed counts |
| Crawl report | JSON crawl report |
| Browser resource blocking | Images, media, fonts, and selected resources |
| Retry support | Crawlee retry and backoff configuration |
| CLI overrides | Command-line settings override environment configuration |

---

# 3. Installation

## 3.1 Enter the project

```bash
cd /mnt/local/areas/docsync
````

## 3.2 Synchronize dependencies

```bash
uv sync --all-extras
```

## 3.3 Install the Playwright browser

Required only for JavaScript or Playwright mode:

```bash
uv run playwright install chromium
```

Optional browser engines:

```bash
uv run playwright install firefox
uv run playwright install webkit
```

## 3.4 Create local environment configuration

```bash
cp -n .env.example .env
```

---

# 4. Running the Project

## 4.1 Canonical command

```bash
uv run docsync
```

The default start URL is loaded from project configuration when no positional URL is provided.

## 4.2 Crawl a specific URL

```bash
uv run docsync https://platform.openai.com/docs
```

## 4.3 Compatibility commands

These commands start the same application:

```bash
uv run python -m docsync
```

```bash
uv run python main.py
```

## 4.4 Show all CLI options

```bash
uv run docsync --help
```

---

# 5. CLI Options

| Option                    | Purpose                                    |
| ------------------------- | ------------------------------------------ |
| `start_url`               | Initial page to crawl                      |
| `--output-dir`            | Directory for generated Markdown           |
| `--output-folder`         | Alias for `--output-dir`                   |
| `--state-dir`             | Directory for persistent incremental state |
| `--max-concurrency`       | Maximum simultaneous crawler tasks         |
| `--max-requests`          | Maximum requests in one crawl              |
| `--language`              | Preferred document language                |
| `--refresh-hours`         | Skip recently synchronized URLs            |
| `--force-refresh`         | Ignore incremental URL state               |
| `--mode http`             | Use the HTTP crawler                       |
| `--mode playwright`       | Use browser rendering                      |
| `--javascript`            | Enable Playwright mode                     |
| `--browser`               | Alias for Playwright mode                  |
| `--playwright`            | Alias for Playwright mode                  |
| `--show-browser`          | Run Playwright in visible mode             |
| `--browser-type chromium` | Use Chromium                               |
| `--browser-type firefox`  | Use Firefox                                |
| `--browser-type webkit`   | Use WebKit                                 |
| `--requests-per-minute`   | Override request-rate configuration        |

---

# 6. Common Run Commands

## 6.1 Small safe HTTP crawl

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --mode http \
    --max-requests 10 \
    --max-concurrency 2
```

## 6.2 JavaScript crawl

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --mode playwright \
    --max-requests 10 \
    --max-concurrency 2
```

## 6.3 JavaScript crawl with visible browser

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --javascript \
    --show-browser \
    --max-requests 5
```

## 6.4 Select another browser

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --mode playwright \
    --browser-type firefox \
    --max-requests 5
```

## 6.5 Force all pages to refresh

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --force-refresh
```

## 6.6 Disable the incremental refresh window

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --refresh-hours 0
```

## 6.7 Use a 24-hour refresh window

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --refresh-hours 24
```

## 6.8 Limit requests per minute

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --requests-per-minute 20
```

## 6.9 Select output and state directories

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --output-dir data/markdown \
    --state-dir data/state
```

## 6.10 Full explicit example

```bash
uv run docsync \
    https://platform.openai.com/docs \
    --output-dir data/markdown \
    --state-dir data/state \
    --max-concurrency 2 \
    --max-requests 100 \
    --language en \
    --refresh-hours 24 \
    --mode playwright \
    --browser-type chromium \
    --requests-per-minute 20
```

---

# 7. End-to-End Runtime Flow

```text
Terminal command
    |
    v
docsync.cli:main
    |
    v
Parse command-line arguments
    |
    v
Apply environment overrides
    |
    v
Create Settings
    |
    v
Validate start URL
    |
    v
Select HTTP or Playwright crawler
    |
    v
Read robots.txt and sitemap candidates
    |
    v
Discover initial URLs
    |
    v
Normalize and validate URLs
    |
    v
Load incremental URL state
    |
    v
Skip recently synchronized URLs
    |
    v
Create Crawlee crawler
    |
    v
Apply concurrency and request-rate limits
    |
    v
Process each request
    |
    +-----------------------------+
    |                             |
    v                             v
HTTP response                 Playwright page
    |                             |
    |                      Block unwanted resources
    |                             |
    |                      Wait for DOM content
    |                             |
    |                      Wait for network idle
    |                             |
    |                      Read rendered HTML
    |                             |
    +-------------+---------------+
                  |
                  v
          BeautifulSoup parsing
                  |
                  v
          Language detection
                  |
                  v
          Main-content extraction
                  |
                  v
          Markdown preparation
                  |
                  v
          Content hash calculation
                  |
                  v
          Duplicate-content decision
                  |
          +-------+--------+
          |                |
          v                v
       Duplicate        Unique
          |                |
          v                v
       Skip/write      Atomic Markdown write
                           |
                           v
                   Record successful state
                           |
                           v
                 Save hashes and URL state
                           |
                           v
                  Write crawl report JSON
                           |
                           v
                   Print finished summary
```

---

# 8. Application Entry Points

| Command                    | File or target            | Role                        |
| -------------------------- | ------------------------- | --------------------------- |
| `uv run docsync`           | `docsync.cli:main`        | Canonical console command   |
| `uv run python -m docsync` | `src/docsync/__main__.py` | Python module command       |
| `uv run python main.py`    | `main.py`                 | Root compatibility launcher |
| Internal compatibility     | `src/docsync/main.py`     | Package-level launcher      |

Recommended command:

```bash
uv run docsync
```

---

# 9. Production Module Architecture

## 9.1 Module summary

| File                                  |    Lines | Main responsibility                     |
| ------------------------------------- | -------: | --------------------------------------- |
| `src/docsync/__init__.py`             |        1 | Package boundary                        |
| `src/docsync/__main__.py`             |        6 | `python -m docsync` launcher            |
| `src/docsync/cli.py`                  |      248 | CLI parsing and application startup     |
| `src/docsync/config.py`               |      277 | Environment and runtime settings        |
| `src/docsync/crawl_delay.py`          |      103 | Asynchronous crawl-delay throttle       |
| `src/docsync/crawler.py`              |      433 | Main crawl orchestration                |
| `src/docsync/duplicates.py`           |      180 | Duplicate-content persistence           |
| `src/docsync/incremental.py`          |      344 | Incremental URL and hash state          |
| `src/docsync/language.py`             |      340 | Language detection                      |
| `src/docsync/logging_config.py`       |       36 | Logging setup                           |
| `src/docsync/main.py`                 |       50 | Compatibility runtime entry point       |
| `src/docsync/markdown.py`             |      370 | Content extraction and Markdown export  |
| `src/docsync/metrics.py`              |      187 | Crawl statistics and JSON reporting     |
| `src/docsync/playwright_rendering.py` |      277 | Browser rendering and resource blocking |
| `src/docsync/sitemap.py`              |      308 | Sitemap and robots discovery            |
| `src/docsync/url_security.py`         |      358 | URL validation and redirect security    |
| **Production total**                  | **3718** | **Application source code**             |

The line total is based on the latest analyzed repository output.

---

# 10. Production Module Details

## 10.1 `src/docsync/cli.py`

Purpose:

* Defines the user-facing CLI.
* Parses positional and optional arguments.
* Applies command-line values to environment configuration.
* Starts the crawler.
* Handles synchronous and asynchronous crawler results.
* Prints the final crawl summary.
* Returns process exit codes.

Important functions:

| Function                       | Responsibility                           |
| ------------------------------ | ---------------------------------------- |
| `positive_integer`             | Validates positive CLI integer values    |
| `build_parser`                 | Creates the argument parser              |
| `_apply_environment_overrides` | Maps CLI arguments to environment values |
| `_resolve_crawler_result`      | Resolves sync or async crawler results   |
| `_invoke_run_crawler`          | Invokes the canonical crawler            |
| `_await_crawler_result`        | Awaits asynchronous crawl results        |
| `main`                         | Canonical console entry point            |

Used by:

* `uv run docsync`
* `src/docsync/__main__.py`
* root `main.py`

---

## 10.2 `src/docsync/config.py`

Purpose:

* Reads environment variables.
* Applies safe defaults.
* Validates integer ranges.
* Validates booleans.
* Normalizes crawler mode.
* Normalizes browser engine.
* Provides the central `Settings` object.

Important items:

| Item                      | Responsibility                          |
| ------------------------- | --------------------------------------- |
| `Settings`                | Complete runtime configuration          |
| `_read_positive_int`      | Reads positive integers                 |
| `_read_bounded_int`       | Reads integers with bounds              |
| `_read_bool`              | Reads boolean environment values        |
| `_normalize_crawler_mode` | Normalizes HTTP or Playwright mode      |
| `_normalize_browser_type` | Normalizes Chromium, Firefox, or WebKit |

Used by:

* CLI
* crawler
* compatibility runtime
* tests

---

## 10.3 `src/docsync/crawler.py`

Purpose:

* Coordinates the complete crawling lifecycle.
* Selects the HTTP or Playwright crawler.
* Creates Crawlee crawler configuration.
* Discovers sitemap URLs.
* Loads persistent state.
* Filters recently synchronized URLs.
* Applies crawl delays.
* Processes responses.
* Generates Markdown.
* Records metrics.
* Persists state at shutdown.

Important items:

| Item                        | Responsibility                        |
| --------------------------- | ------------------------------------- |
| `_IncrementalRuntimeConfig` | Runtime adapter for incremental logic |
| `normalize_start_url`       | Normalizes initial crawl URL          |
| `build_scope_pattern`       | Defines allowed crawl scope           |
| `run_crawler`               | Main asynchronous crawler function    |

Main dependencies:

```text
config
crawl_delay
incremental
markdown
metrics
playwright_rendering
sitemap
url_security
```

This is the central production module.

---

## 10.4 `src/docsync/url_security.py`

Purpose:

* Accepts only HTTP and HTTPS URLs.
* Rejects unsafe or malformed URLs.
* Normalizes URLs.
* Removes unwanted tracking parameters.
* Restricts crawl scope.
* Prevents unsafe redirects.
* Enforces same-origin redirect behavior.
* Provides secure URL opening.

Important items:

| Item                        | Responsibility                       |
| --------------------------- | ------------------------------------ |
| `SameOriginRedirectHandler` | Rejects unsafe redirect targets      |
| `validated_http_url`        | Validates HTTP/HTTPS URLs            |
| `normalized_http_origin`    | Produces normalized origins          |
| `secure_urlopen`            | Opens URLs through security controls |
| `normalize_url`             | Produces stable normalized URLs      |
| `is_safe_in_scope_url`      | Checks crawl scope and safety        |

Used by:

* configuration
* crawler
* sitemap discovery
* incremental state

---

## 10.5 `src/docsync/sitemap.py`

Purpose:

* Reads `robots.txt`.
* Extracts sitemap declarations.
* Tries common sitemap locations.
* Downloads sitemap XML safely.
* Supports gzip sitemap payloads.
* Parses sitemap indexes.
* Parses URL sets.
* Recursively discovers crawl URLs.

Important items:

| Item                         | Responsibility                         |
| ---------------------------- | -------------------------------------- |
| `SitemapDiscoveryResult`     | Sitemap discovery result model         |
| `decode_sitemap_payload`     | Decodes plain or compressed XML        |
| `extract_robots_sitemaps`    | Reads sitemap entries from robots text |
| `fetch_text_url`             | Downloads text with safety controls    |
| `sitemap_candidate_urls`     | Builds common sitemap candidates       |
| `sitemap_xml_locations`      | Parses locations from sitemap XML      |
| `discover_sitemap_urls_sync` | Synchronous discovery implementation   |
| `discover_sitemap_urls`      | Async-compatible discovery entry point |

---

## 10.6 `src/docsync/crawl_delay.py`

Purpose:

* Implements deterministic request spacing.
* Uses a monotonic clock.
* Serializes concurrent waiters.
* Prevents requests from starting too close together.
* Reads delay configuration from environment values.

Important items:

| Item                                   | Responsibility                       |
| -------------------------------------- | ------------------------------------ |
| `MonotonicClock`                       | Clock protocol                       |
| `CrawlDelayThrottle`                   | Shared asynchronous request throttle |
| `crawl_delay_seconds_from_environment` | Loads configured delay               |

---

## 10.7 `src/docsync/incremental.py`

Purpose:

* Calculates stable content hashes.
* Loads and saves content-hash state.
* Loads and saves URL timestamps.
* Determines whether a URL is recent.
* Filters URLs before crawling.
* Detects unchanged content.
* Records successful exports.
* Uses atomic state-file replacement.
* Tracks incremental skip counts.

Important items:

| Item                      | Responsibility                             |
| ------------------------- | ------------------------------------------ |
| `IncrementalConfig`       | Incremental settings contract              |
| `IncrementalStats`        | Incremental counters                       |
| `content_hash`            | Stable normalized hash                     |
| `load_content_hashes`     | Loads hash state                           |
| `save_content_hashes`     | Atomically saves hash state                |
| `load_url_state`          | Loads URL synchronization state            |
| `save_url_state`          | Atomically saves URL state                 |
| `is_recently_saved`       | Applies refresh-window logic               |
| `record_incremental_skip` | Records skipped URLs                       |
| `filter_incremental_urls` | Normalizes, deduplicates, and filters URLs |

Persistent files:

```text
data/state/content_hashes.json
data/state/url_state.json
```

or the configured state directory.

---

## 10.8 `src/docsync/duplicates.py`

Purpose:

* Detects identical content across different URLs.
* Stores duplicate decisions persistently.
* Normalizes hashes.
* Uses SQLite transactions.
* Maps duplicate URLs to canonical content.

Important items:

| Item                | Responsibility              |
| ------------------- | --------------------------- |
| `DuplicateDecision` | Duplicate evaluation result |
| `DuplicateRegistry` | Persistent duplicate store  |

---

## 10.9 `src/docsync/language.py`

Purpose:

* Detects page language.
* Combines language-detection strategies.
* Decides whether a page matches the configured language.
* Prevents unwanted-language pages from being exported.

Important items:

| Item                  | Responsibility             |
| --------------------- | -------------------------- |
| `LanguageDecision`    | Language evaluation result |
| `EnglishPageDetector` | English-page detector      |

---

## 10.10 `src/docsync/markdown.py`

Purpose:

* Reads BeautifulSoup HTML.
* Selects meaningful document content.
* Removes navigation and unwanted elements.
* Determines the page title.
* Converts HTML to Markdown.
* Creates stable output paths.
* Quotes YAML front matter safely.
* Avoids unnecessary rewrites.
* Writes files atomically.

Important items:

| Item               | Responsibility                 |
| ------------------ | ------------------------------ |
| `MarkdownDocument` | Prepared Markdown output model |
| `MarkdownExporter` | HTML-to-Markdown pipeline      |

Typical output:

```text
data/markdown/<hostname>/<path>-<hash>.md
```

---

## 10.11 `src/docsync/playwright_rendering.py`

Purpose:

* Defines canonical Playwright configuration.
* Blocks unnecessary browser resources.
* Preserves required document resources.
* Installs request-routing handlers.
* Waits for DOM content.
* Waits for network idle.
* Reads final rendered HTML.
* Supports Chromium, Firefox, and WebKit.

Important items:

| Item                                | Responsibility               |
| ----------------------------------- | ---------------------------- |
| `PlaywrightRenderingConfig`         | Browser-rendering settings   |
| `should_block_resource`             | Resource-blocking decision   |
| `merge_playwright_options`          | Combines browser options     |
| `normalized_blocked_resource_types` | Normalizes blocking rules    |
| `handle_route`                      | Aborts or continues requests |
| `install_resource_blocking`         | Installs page routing        |
| `render_page_html`                  | Returns rendered page HTML   |

Typical blocked resources:

```text
image
media
font
```

Required HTML, scripts, styles, and document resources remain available according to configuration.

---

## 10.12 `src/docsync/metrics.py`

Purpose:

* Stores crawl counters.
* Records start and finish timestamps.
* Tracks processed, saved, skipped, duplicate, and failed pages.
* Builds the crawl report.
* Writes the report atomically.
* Produces JSON-compatible values.
* Preserves the canonical finished-summary contract.

Important items:

| Item                 | Responsibility                         |
| -------------------- | -------------------------------------- |
| `CrawlStats`         | Runtime counters and timing            |
| `build_crawl_report` | Creates report data                    |
| `write_crawl_report` | Atomically writes JSON report          |
| `_json_compatible`   | Converts values for JSON serialization |

Typical report:

```text
output/crawl-report.json
```

---

## 10.13 `src/docsync/logging_config.py`

Purpose:

* Configures application logging.
* Sets formatting and log levels.
* Creates consistent runtime diagnostics.

Important function:

```text
configure_logging
```

---

## 10.14 Entry-point modules

### `src/docsync/__main__.py`

Runs:

```bash
uv run python -m docsync
```

Delegates to:

```text
docsync.cli:main
```

### `src/docsync/main.py`

Provides package-level compatibility functions:

```text
run
main
```

### Root `main.py`

Runs:

```bash
uv run python main.py
```

Delegates to the canonical CLI.

---

# 11. Internal Module Dependency Flow

```text
main.py
    |
    v
docsync.cli
    |
    +--------------------+
    |                    |
    v                    v
docsync.crawler      docsync.metrics
    |
    +--------------------+
    |                    |
    v                    v
docsync.config       docsync.crawl_delay
    |
    +--------------------+
    |                    |
    v                    v
docsync.url_security docsync.sitemap
    |
    +--------------------+
    |                    |
    v                    v
docsync.incremental  docsync.playwright_rendering
    |
    +--------------------+
    |                    |
    v                    v
docsync.markdown     docsync.metrics
```

Additional production services:

```text
docsync.duplicates
docsync.language
docsync.logging_config
```

---

# 12. Repository Directory Structure

```text
docsync/
├── .env.example
├── .gitignore
├── .python-version
├── README.md
├── TODO.md
├── main.py
├── pyproject.toml
├── uv.lock
│
├── src/
│   └── docsync/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── crawl_delay.py
│       ├── crawler.py
│       ├── duplicates.py
│       ├── incremental.py
│       ├── language.py
│       ├── logging_config.py
│       ├── main.py
│       ├── markdown.py
│       ├── metrics.py
│       ├── playwright_rendering.py
│       ├── sitemap.py
│       └── url_security.py
│
├── tests/
│   ├── test_atomic_write_repeated_execution.py
│   ├── test_behavioral_core.py
│   ├── test_behavioral_duplicates.py
│   ├── test_behavioral_markdown.py
│   ├── test_browser_mode_configuration.py
│   ├── test_cli_requests_per_minute.py
│   ├── test_crawl_delay.py
│   ├── test_crawl_delay_inventory.py
│   ├── test_crawl_delay_runtime_wiring.py
│   ├── test_crawler_browser_dispatch.py
│   ├── test_crawler_metrics_wiring.py
│   ├── test_duplicate_lifecycle_runtime_wiring.py
│   ├── test_incremental.py
│   ├── test_incremental_configuration.py
│   ├── test_incremental_crawler_wiring.py
│   ├── test_incremental_export_state_wiring.py
│   ├── test_incremental_sync_runtime_wiring.py
│   ├── test_main_entrypoint.py
│   ├── test_metrics_reporting.py
│   ├── test_playwright_rendering.py
│   ├── test_project_smoke.py
│   ├── test_request_rate_limit.py
│   ├── test_retry_backoff_runtime_wiring.py
│   ├── test_robots_runtime.py
│   ├── test_sitemap.py
│   ├── test_sqlite_resource_lifecycle.py
│   ├── test_unchanged_markdown_wiring.py
│   ├── test_url_security.py
│   ├── verify_duplicate_detection.py
│   ├── verify_incremental_sync.py
│   └── verify_javascript_rendering.py
│
├── tools/
│   ├── inspect_bandit_context.py
│   ├── inspect_behavioral_test_targets.py
│   ├── inspect_project.py
│   ├── project_audit.py
│   ├── run_full_validation.py
│   ├── safe_crawl_test.py
│   └── update_readme_architecture.py
│
├── data/
│   ├── markdown/
│   └── state/
│
├── output/
├── logs/
└── storage/
    ├── datasets/
    ├── key_value_stores/
    ├── request_queues/
    ├── docsync/
    └── state-backups/
```

---

# 13. Directory Responsibilities

| Directory        | Responsibility                                                      |
| ---------------- | ------------------------------------------------------------------- |
| `src/docsync/`   | Production application code                                         |
| `tests/`         | Unit, behavioral, wiring, integration, and live verification tests  |
| `tools/`         | Inspection, validation, auditing, and safe crawl tools              |
| `data/markdown/` | Generated Markdown documentation                                    |
| `data/state/`    | Incremental URL and content-hash state                              |
| `output/`        | Crawl reports and alternate generated output                        |
| `logs/`          | Runtime logs                                                        |
| `storage/`       | Crawlee request queues, datasets, key-value stores, and checkpoints |
| `.venv/`         | Local Python environment managed by `uv`                            |

---

# 14. Test Architecture

## 14.1 Test totals

| Item                         | Value |
| ---------------------------- | ----: |
| Collected tests              | `316` |
| Passed tests                 | `316` |
| Failed tests                 |   `0` |
| Test Python modules          |  `32` |
| Source files checked by Mypy |  `48` |

## 14.2 Test categories

| Test group                  | Purpose                                                |
| --------------------------- | ------------------------------------------------------ |
| Atomic-write tests          | Verify safe repeated state and Markdown replacement    |
| Behavioral core tests       | Verify URLs, sitemaps, Markdown, metrics, and hashes   |
| Duplicate tests             | Verify persistent duplicate handling                   |
| Browser configuration tests | Verify Playwright settings and CLI flags               |
| Crawl-delay tests           | Verify deterministic throttling                        |
| Runtime wiring tests        | Verify modules are connected to the real crawler       |
| Incremental tests           | Verify refresh windows, hashes, state, and skips       |
| Metrics tests               | Verify crawl reports and finished summaries            |
| Playwright tests            | Verify resource blocking and rendering                 |
| Retry tests                 | Verify retry configuration and handler backoff         |
| Robots tests                | Verify robots configuration                            |
| Sitemap tests               | Verify sitemap security, decoding, and parsing         |
| URL security tests          | Verify URL validation and redirect restrictions        |
| Smoke tests                 | Verify entry points and source compilation             |
| Live verification scripts   | Verify duplicate, incremental, and JavaScript behavior |

---

# 15. Verification Scripts

## 15.1 Duplicate detection verification

```bash
uv run python tests/verify_duplicate_detection.py
```

Verifies:

* duplicate content hashes;
* canonical and duplicate URL relationships;
* persistent duplicate state;
* expected crawl metrics.

## 15.2 Incremental synchronization verification

```bash
uv run python tests/verify_incremental_sync.py
```

Verifies:

* first-run downloads;
* second-run skips;
* refresh-window behavior;
* force refresh;
* changed content;
* persistent URL and hash state;
* stable output files.

## 15.3 JavaScript rendering verification

```bash
uv run python tests/verify_javascript_rendering.py
```

Verifies:

* Playwright invocation;
* JavaScript-only content;
* rendered headings;
* removal of initial loading content;
* DOM-content wait;
* network-idle wait;
* final `page.content()` retrieval.

---

# 16. Development Tools

| Tool                                       | Purpose                                                          |
| ------------------------------------------ | ---------------------------------------------------------------- |
| `tools/update_readme_architecture.py`      | Inspects the repository and generates architecture documentation |
| `tools/run_full_validation.py`             | Runs the complete validation workflow                            |
| `tools/safe_crawl_test.py`                 | Runs a controlled crawl against safe fixtures                    |
| `tools/project_audit.py`                   | Audits repository structure and generated artifacts              |
| `tools/inspect_project.py`                 | Performs detailed static repository inspection                   |
| `tools/inspect_bandit_context.py`          | Reviews Bandit findings with source context                      |
| `tools/inspect_behavioral_test_targets.py` | Inspects production targets for behavioral testing               |

Run the README architecture generator:

```bash
uv run python tools/update_readme_architecture.py
```

Run the complete validation tool:

```bash
uv run python tools/run_full_validation.py
```

Run the safe crawler test:

```bash
uv run python tools/safe_crawl_test.py
```

Run the project audit:

```bash
uv run python tools/project_audit.py
```

---

# 17. Configuration Sources

Settings are resolved from:

```text
CLI arguments
    override
environment variables
    override
application defaults
```

Primary configuration file template:

```text
.env.example
```

Local configuration file:

```text
.env
```

Do not store real secrets in `.env.example`.

---

# 18. Important Runtime State

## 18.1 Incremental state

```text
data/state/content_hashes.json
data/state/url_state.json
```

These files store:

* URL synchronization timestamps;
* normalized content hashes;
* incremental refresh decisions.

## 18.2 Crawlee storage

```text
storage/datasets/
storage/key_value_stores/
storage/request_queues/
```

These directories are controlled by Crawlee and may contain:

* crawler statistics;
* request queue state;
* dataset records;
* key-value metadata;
* restart checkpoints.

## 18.3 Project checkpoint state

```text
storage/docsync/checkpoint.json
storage/docsync/content_hashes.json
storage/docsync/url_state.json
```

## 18.4 State backups

```text
storage/state-backups/
```

Used for preserved state snapshots.

---

# 19. Output Files

## 19.1 Markdown output

Default or configured output:

```text
data/markdown/
```

Example structure:

```text
data/markdown/
└── platform.openai.com/
    └── docs/
        └── page-name-<hash>.md
```

## 19.2 Crawl report

```text
output/crawl-report.json
```

Typical fields include:

```text
started_at
finished_at
duration
processed
saved
skipped
failed
duplicates
incremental_skips
configuration
```

---

# 20. Validation Commands

## 20.1 Ruff format check

```bash
uv run ruff format --check .
```

## 20.2 Ruff lint

```bash
uv run ruff check .
```

## 20.3 Mypy

```bash
uv run mypy src tests
```

## 20.4 Full pytest

```bash
uv run pytest
```

## 20.5 Python compilation

```bash
uv run python -m compileall -q src tests tools main.py
```

## 20.6 CLI validation

```bash
uv run docsync --help
```

## 20.7 Run all main validations

```bash
cd /mnt/local/areas/docsync

uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python -m compileall -q src tests tools main.py
uv run docsync --help
```

---

# 21. Last Verified Project Status

| Validation              | Result       |
| ----------------------- | ------------ |
| Architecture generation | Passed       |
| Source contract         | Passed       |
| Ruff format check       | Passed       |
| Ruff lint               | Passed       |
| Mypy                    | Passed       |
| Targeted pytest         | `19 passed`  |
| Full pytest             | `316 passed` |
| Python compilation      | Passed       |
| Canonical CLI           | Passed       |
| README contract         | Passed       |

Last observed validation summary:

```text
Repair patch:                  0
Ruff auto-fix:                 0
Ruff format write:             0
Architecture generation:       0
Source repair contract:        0
Ruff format check:             0
Ruff lint:                     0
Mypy:                          0
Targeted pytest:               0
Full pytest:                   0
Python compilation:            0
Canonical CLI:                 0
README contract:               0
Git diff check:                0
```

---

# 22. Recommended Daily Workflow

```bash
cd /mnt/local/areas/docsync

uv sync --all-extras

uv run ruff format .
uv run ruff check .
uv run mypy src tests
uv run pytest

uv run docsync \
    https://platform.openai.com/docs \
    --output-dir data/markdown \
    --state-dir data/state \
    --refresh-hours 24 \
    --requests-per-minute 20
```

---

# 23. Troubleshooting

## CLI does not start

```bash
uv sync --all-extras
uv run docsync --help
```

## Playwright browser is missing

```bash
uv run playwright install chromium
```

## A page requires JavaScript

```bash
uv run docsync \
    https://example.com \
    --mode playwright
```

## Recently crawled URLs are skipped

Use:

```bash
uv run docsync \
    https://example.com \
    --force-refresh
```

or:

```bash
uv run docsync \
    https://example.com \
    --refresh-hours 0
```

## Output directory is incorrect

```bash
uv run docsync \
    https://example.com \
    --output-dir data/markdown
```

## State directory is incorrect

```bash
uv run docsync \
    https://example.com \
    --state-dir data/state
```

## Crawl is too fast

```bash
uv run docsync \
    https://example.com \
    --requests-per-minute 10
```

## Crawl is too large

```bash
uv run docsync \
    https://example.com \
    --max-requests 20
```

## Browser debugging is required

```bash
uv run docsync \
    https://example.com \
    --mode playwright \
    --show-browser \
    --max-requests 5
```

---

# 24. Quick Reference

Install:

```bash
uv sync --all-extras
```

Run:

```bash
uv run docsync https://platform.openai.com/docs
```

Run JavaScript mode:

```bash
uv run docsync https://platform.openai.com/docs --mode playwright
```

Force refresh:

```bash
uv run docsync https://platform.openai.com/docs --force-refresh
```

Test:

```bash
uv run pytest
```

Validate everything:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python -m compileall -q src tests tools main.py
```

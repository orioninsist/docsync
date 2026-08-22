# docsync

A documentation crawling and synchronization engine built with Python, Crawlee, Playwright, and uv.

docsync crawls documentation websites, extracts clean Markdown content, validates language requirements, and maintains incremental synchronization state.

It is designed for:

- Documentation backups
- Offline documentation archives
- AI dataset preparation
- Knowledge base generation
- Internal documentation mirrors
- Automated documentation synchronization


---

# 1. Overview

docsync is a modular documentation crawler and synchronization engine.

The project discovers documentation pages from websites, processes HTML content, converts pages into Markdown, and stores synchronization metadata for future incremental updates.

docsync is built for modern documentation platforms that may contain:

- Static HTML pages
- JavaScript-rendered pages
- Large documentation trees
- Multiple language versions
- Frequently changing content


Main objectives:

- Reliable documentation crawling
- Language-aware page selection
- Incremental synchronization
- Clean Markdown generation
- Scalable crawling architecture


Core workflow:

```

Website

|

v

URL Discovery

|

v

Language Validation

|

v

Crawlee Processing

|

v

Markdown Export

|

v

Synchronization Storage

````


---

# 2. Features

| Feature | Support |
|---|---|
| Python | 3.13+ |
| Crawlee Python | 1.9.1 |
| HTTP crawling | Yes |
| Playwright crawling | Yes |
| BeautifulSoup extraction | Yes |
| Chromium support | Yes |
| Firefox support | Yes |
| WebKit support | Yes |
| Sitemap discovery | Yes |
| HTML link discovery | Yes |
| Incremental synchronization | Yes |
| Request rate limiting | Yes |
| Concurrency control | Yes |
| Request retry handling | Yes |
| Markdown conversion | Yes |
| Language-aware crawling | Yes |
| CLI application | Yes |
| Persistent crawl state | Yes |
| Inventory generation | Yes |


---

# 3. Architecture

docsync follows a modular crawler architecture based on separation of responsibilities.

## High Level Architecture

```mermaid
flowchart TD

A[CLI Entry Point]

A --> B[Configuration Loader]

B --> C[Crawler Runtime]

C --> D[HTTP Crawler]

C --> E[Playwright Crawler]

D --> F[HTML Extraction]

E --> F

F --> G[Language Detection]

G --> H[Language Strategy]

H --> I[Markdown Converter]

I --> J[Output Storage]

C --> K[Request Queue]

C --> L[Synchronization State]
````

---

## Crawling Pipeline

```
START

 |

 v

Target URL

 |

 v

Configuration

 |

 v

Crawler Runtime

 |

 +--------------------+
 |                    |
 v                    v

HTTP Mode       Playwright Mode


 |                    |

 +---------+----------+

           |

           v

     HTML Extraction

           |

           v

    Language Strategy

           |

           v

      Request Queue

           |

           v

     Crawlee Worker

           |

           v

   HTML Verification

           |

      +----+----+

      |         |

      v         v

    Save      Skip

      |

      v

 Markdown Export
```

---

# 4. Installation

## Requirements

Before installation:

* Git
* Python 3.13+
* uv package manager

---

## Install uv

### Linux / macOS

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Windows PowerShell

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Verify:

```bash
uv --version
```

---

## Install docsync from GitHub

Clone repository:

```bash
git clone https://github.com/orioninsist/docsync.git

cd docsync
```

Install project:

```bash
uv sync
```

This installs:

* docsync dependencies
* Crawlee Python
* BeautifulSoup crawler support
* Playwright crawler support
* curl impersonation support
* Required Python packages

---

## Crawlee Installation

docsync uses Crawlee Python as the crawling engine.

No separate Crawlee installation is required.

Crawlee is installed automatically with:

```bash
uv sync
```

Verify:

```bash
uv run python -c "import crawlee; print(crawlee.__version__)"
```

Expected:

```text
1.9.1
```

---

## Playwright Browser Installation

Install browser binaries:

```bash
uv run playwright install chromium
```

Supported browsers:

* Chromium
* Firefox
* WebKit

---

## Verify Installation

Run:

```bash
uv run docsync --help
```

If CLI help appears, installation is complete.

---

# 5. Quick Start

## Basic HTTP Crawl

For static documentation websites:

```bash
uv run docsync https://example.com/docs
```

HTTP mode provides fast crawling without browser rendering.

---

## JavaScript Documentation Crawl

For JavaScript-rendered websites:

```bash
uv run docsync \
  https://example.com/docs \
  --mode playwright \
  --browser-type chromium
```

Playwright mode is recommended for:

* React documentation
* Vue documentation
* Angular documentation
* Dynamic documentation portals

---

## Language Specific Crawl

English documentation:

```bash
uv run docsync \
  https://example.com/docs \
  --language en
```

Turkish documentation:

```bash
uv run docsync \
  https://example.com/docs \
  --language tr
```

---

## Large Documentation Crawl

Example:

```bash
uv run docsync \
  https://example.com/docs \
  --max-requests 5000 \
  --max-concurrency 10 \
  --requests-per-minute 60
```

This configuration is suitable for large documentation websites.

---

# 6. CLI Usage

## Command Format

```bash
uv run docsync URL [OPTIONS]
```

Example:

```bash
uv run docsync \
  https://example.com/docs \
  --language en \
  --mode playwright
```

CLI controls:

* Crawl target
* Output location
* Synchronization state
* Language selection
* Browser engine
* Request limits
* Concurrency

# 7. Configuration Parameters

docsync provides CLI parameters to control crawling behavior, synchronization, language selection, storage location, and browser execution.


## CLI Options

| Option | Description |
|---|---|
| `URL` | Starting documentation website URL |
| `--output-dir` | Markdown output directory |
| `--state-dir` | Synchronization state directory |
| `--max-concurrency` | Maximum parallel requests |
| `--max-requests` | Maximum crawl request limit |
| `--requests-per-minute` | Request rate limit |
| `--language` | Target language (`en` or `tr`) |
| `--refresh-hours` | Refresh interval for synchronization |
| `--mode` | Crawling mode (`http` or `playwright`) |
| `--browser-type` | Browser engine (`chromium`, `firefox`, `webkit`) |


---

## Parameter Details


### URL

Starting point of the crawl.

Example:

```bash
uv run docsync https://example.com/docs
````

---

### --output-dir

Defines where generated Markdown files are stored.

Example:

```bash
--output-dir ./output
```

Result:

```text
output/

└── pages/

    ├── index.md

    ├── getting-started.md

    └── api-reference.md
```

---

### --state-dir

Defines synchronization state storage.

The state directory stores:

* Crawl progress
* Request history
* Synchronization metadata

Example:

```bash
--state-dir ./storage
```

---

### --max-concurrency

Controls the number of parallel crawling tasks.

Example:

```bash
--max-concurrency 10
```

Higher values increase speed but require more resources.

---

### --max-requests

Limits the maximum number of processed requests.

Example:

```bash
--max-requests 5000
```

Useful for:

* Testing
* Large website control
* Resource management

---

### --requests-per-minute

Controls request rate.

Example:

```bash
--requests-per-minute 60
```

This helps avoid aggressive crawling behavior.

---

### --language

Defines the target documentation language.

Supported:

| Language | Code |
| -------- | ---- |
| English  | `en` |
| Turkish  | `tr` |

Example:

```bash
--language en
```

or:

```bash
--language tr
```

---

### --refresh-hours

Defines synchronization refresh interval.

Example:

```bash
--refresh-hours 24
```

Used for repeated documentation synchronization.

---

### --mode

Selects crawler engine.

Available modes:

| Mode         | Usage                |
| ------------ | -------------------- |
| `http`       | Static HTML websites |
| `playwright` | JavaScript websites  |

Example:

```bash
--mode playwright
```

---

### --browser-type

Defines Playwright browser engine.

Supported:

| Browser  | Value      |
| -------- | ---------- |
| Chromium | `chromium` |
| Firefox  | `firefox`  |
| WebKit   | `webkit`   |

Example:

```bash
--browser-type chromium
```

---

## Full CLI Example

```bash
uv run docsync \
  https://example.com/docs \
  --output-dir ./output \
  --state-dir ./storage \
  --max-concurrency 4 \
  --max-requests 5000 \
  --requests-per-minute 60 \
  --language en \
  --mode playwright \
  --browser-type chromium
```

---

# 8. Crawl Modes

docsync supports two crawling modes.

---

## HTTP Mode

HTTP mode is optimized for static documentation websites.

Flow:

```text
URL

 |

 v

HTTP Request

 |

 v

HTML Response

 |

 v

BeautifulSoup Extraction

 |

 v

Markdown Export
```

Usage:

```bash
uv run docsync \
  https://example.com/docs \
  --mode http
```

Recommended for:

* Static HTML documentation
* Simple websites
* Fast crawling

---

## Playwright Mode

Playwright mode uses browser automation.

Flow:

```text
URL

 |

 v

Browser Launch

 |

 v

JavaScript Execution

 |

 v

Rendered HTML

 |

 v

Content Extraction

 |

 v

Markdown Export
```

Usage:

```bash
uv run docsync \
  https://example.com/docs \
  --mode playwright \
  --browser-type chromium
```

Recommended for:

* React applications
* Vue applications
* Angular applications
* Dynamic documentation portals

---

# 9. Language System

docsync uses a centralized language decision architecture.

The system is based on:

```text
Language Detection

        |

        v

LanguageDecision

        |

        v

LanguageStrategy

        |

        v

Accept / Skip
```

Supported languages:

| Language | Code |
| -------- | ---- |
| English  | `en` |
| Turkish  | `tr` |

---

## Language Processing Pipeline

```text
Target URL

      |

      v

Requested Language

      |

      v

LanguageStrategy

      |

      v

URL Discovery

      |

      v

Language Pre Filter

      |

      v

Request Queue

      |

      v

HTML Download

      |

      v

Language Detection

      |

      v

Final Language Decision
```

---

## URL Language Filtering

Before entering the Crawlee queue:

```text
URL

 |

 v

LanguageStrategy.should_skip_url()

 |

 +-------------+
 |             |
 v             v

Accept       Reject
```

Example:

Requested:

```text
en
```

URL:

```text
/example/en/docs
```

Result:

```text
Accepted
```

URL:

```text
/example/tr/docs
```

Result:

```text
Skipped
```

---

## HTML Language Verification

URL patterns are not always enough.

docsync validates the downloaded page content.

Flow:

```text
HTML Content

      |

      v

Language Detector

      |

      v

LanguageStrategy.accepts()

      |

 +----+----+

 |         |

 v         v

Save      Skip
```

This prevents incorrect language pages from being exported.

---

# 10. Sitemap and Link Discovery

docsync separates URL discovery from language validation.

## Sitemap Discovery

Supported:

* sitemap.xml
* sitemap index files
* multiple sitemap locations

Flow:

```text
robots.txt

      |

      v

sitemap.xml

      |

      v

URL Extraction

      |

      v

Language Strategy

      |

      v

Request Queue
```

---

## HTML Link Discovery

Documentation pages can discover additional pages.

Flow:

```text
Documentation Page

        |

        v

HTML Link Extraction

        |

        v

Scope Validation

        |

        v

Language Filtering

        |

        v

Crawlee Queue
```

Both HTTP and Playwright modes use the same discovery and language rules.


# 11. Project Structure


docsync follows a modular Python project architecture.

Each module has a single responsibility.


Project tree:

```text
docsync/

├── src/

│   └── docsync/

│       ├── cli.py
│       │   Command line interface

│       ├── crawler.py
│       │   Main crawler workflow

│       ├── crawler_runtime.py
│       │   Crawlee runtime configuration

│       ├── config.py
│       │   Application configuration

│       ├── inventory.py
│       │   Website inventory generation

│       ├── language.py
│       │   Language detection engine

│       ├── language_strategy.py
│       │   Language decision rules

│       ├── sitemap.py
│       │   Sitemap discovery

│       ├── markdown.py
│       │   Markdown conversion

│       └── models.py
│           Pydantic data models


├── tests/

│   Automated test suite


├── output/

│   Generated Markdown files


├── storage/

│   Crawl state and synchronization metadata


├── pyproject.toml

│   Python project configuration


└── uv.lock

    Locked dependency versions
````

---

## Module Responsibilities

| Module                 | Responsibility                                     |
| ---------------------- | -------------------------------------------------- |
| `cli.py`               | Command line interface and application entry point |
| `crawler.py`           | Main Crawlee crawling workflow                     |
| `crawler_runtime.py`   | Crawlee runtime, queue, and crawler settings       |
| `config.py`            | Configuration loading and validation               |
| `inventory.py`         | Website inventory generation                       |
| `language.py`          | Language detection and language decisions          |
| `language_strategy.py` | Requested language policy                          |
| `sitemap.py`           | Sitemap URL discovery                              |
| `markdown.py`          | Markdown generation                                |
| `models.py`            | Typed data models                                  |

---

# 12. Output Structure

docsync generates Markdown documentation and keeps synchronization data separately.

## Markdown Output

Example:

```text
output/

└── pages/

    ├── index.md

    ├── getting-started.md

    ├── configuration.md

    └── api-reference.md
```

Each Markdown file contains cleaned documentation content extracted from the original website.

---

## Synchronization Storage

Example:

```text
storage/

├── request_queues/

├── datasets/

└── metadata/
```

The state directory stores:

* Crawl progress
* Request history
* Synchronization metadata
* Incremental crawl information

---

## Inventory Output

Inventory mode generates:

```text
site-inventory.json
```

Example:

```json
{
  "english_urls": 450,
  "non_english_urls": 120,
  "duplicate_urls": 20,
  "discovery_complete": true
}
```

Inventory is useful for:

* Website analysis
* Documentation auditing
* Language coverage checking

---

# 13. Synchronization System

docsync supports incremental synchronization.

Instead of downloading everything on every run, it keeps crawl state and processes only required updates.

---

## Synchronization Flow

```text
First Crawl

    |

    v

Discover Pages

    |

    v

Download Content

    |

    v

Generate Markdown

    |

    v

Store State



Next Crawl

    |

    v

Compare Existing State

    |

    v

Update Changed Pages Only
```

---

## Benefits

| Feature             | Benefit                         |
| ------------------- | ------------------------------- |
| Persistent state    | Resume previous crawls          |
| Incremental updates | Faster repeated synchronization |
| Metadata tracking   | Better crawl control            |
| Request history     | Avoid unnecessary requests      |

---

# 14. Development

## Install Development Environment

```bash
uv sync
```

---

## Code Formatting

Run:

```bash
uv run ruff format .
```

---

## Linting

Run:

```bash
uv run ruff check .
```

---

## Type Checking

Run:

```bash
uv run mypy .
```

---

## Local Development Workflow

Typical workflow:

```text
Edit Code

   |

   v

Run Formatter

   |

   v

Run Type Checker

   |

   v

Run Tests

   |

   v

Build Package
```

---

# 15. Testing

docsync uses automated tests to validate crawler behavior.

Run full test suite:

```bash
uv run pytest -q
```

Expected result:

```text
438 passed
```

---

## Tested Components

| Component              | Coverage |
| ---------------------- | -------- |
| Crawler workflow       | Yes      |
| Request queue behavior | Yes      |
| Sitemap discovery      | Yes      |
| Link discovery         | Yes      |
| Language strategy      | Yes      |
| Inventory generation   | Yes      |
| Synchronization logic  | Yes      |
| Configuration handling | Yes      |

---

## Test Philosophy

Tests verify:

* Discovery happens before filtering
* Queue behavior remains correct
* Language decisions are consistent
* HTTP and Playwright flows behave equally
* Incremental synchronization remains stable

---

# 16. Technology Stack

| Technology    | Purpose                     |
| ------------- | --------------------------- |
| Python        | Application runtime         |
| Crawlee       | Web crawling engine         |
| Playwright    | Browser automation          |
| BeautifulSoup | HTML parsing                |
| Pydantic      | Data validation             |
| uv            | Dependency management       |
| Ruff          | Code formatting and linting |
| MyPy          | Static type checking        |
| Pytest        | Automated testing           |

---

# 17. License

MIT License

Copyright (c) 2026 orioninsist

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
OR OTHER DEALINGS IN THE SOFTWARE.

MIT License

Copyright (c) 2026 orioninsist

This project is open source and available under the MIT License.
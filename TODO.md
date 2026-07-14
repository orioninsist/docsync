# DOCSYNC TODO

## Current Status

- Current Step: 8/8 — Commit Ready
- Remaining Steps: 0
- Quality Score: 100/100
- Release Validation: PASSED
- Working Tree Classification: VERIFIED
- Architecture Status: VERIFIED

## Completed

- [x] Verify crawler and pipeline remain fully independent.
- [x] Verify crawler writes raw data only under `sources/<project>/output/`.
- [x] Verify pipeline discovers source directories dynamically.
- [x] Verify pipeline reads crawler output from `sources/<project>/output/`.
- [x] Remove static repository-level output assumptions.
- [x] Move global URL registry ownership from pipeline to crawler.
- [x] Remove the legacy crawler backup file.
- [x] Verify forbidden legacy pipeline paths are absent.
- [x] Verify required project files exist.
- [x] Verify crawler-generated Markdown files are read-only.
- [x] Run Ruff validation across the project.
- [x] Compile all Python modules.
- [x] Run final release validation.
- [x] Run Git whitespace validation.
- [x] Ignore local coverage and audit artifacts.
- [x] Classify all remaining Git changes as intentional source changes.

## Architecture Invariants

1. Crawler and Pipeline remain fully independent.
2. Crawler owns discovery, fetching, deduplication, persistence, and raw output.
3. Crawler writes raw data only under:

   `sources/<project>/output/`

4. Pipeline discovers project directories dynamically under:

   `sources/`

5. Pipeline reads crawler output from:

   `sources/<project>/output/`

6. Pipeline must not depend on a static repository-level `/output` directory.
7. Pipeline outputs are derived, flattened, and read-only.
8. All project commands run through `uv`.
9. Automated file writes must always contain complete, untruncated content.
10. Release validation must pass before commit or deployment.

## Intentional Git Changes

### Modified

- `.gitignore`
- `README.md`
- `TODO.md`
- `crawler/config.py`
- `crawler/crawler_discovery.py`
- `crawler/crawler_engine.py`
- `crawler/database.py`
- `crawler/markdown_writer.py`
- `crawler/observability.py`
- `crawler/official_graph.py`
- `crawler_cli.py`
- `pipeline/paths.py`
- `pipeline/release_validate.py`
- `pipeline/run_pipeline.py`

### Added

- `crawler/global_url_registry.py`
- `crawler/time_utils.py`

### Deleted

- `crawler/discovery_engine.py.before-queue-fix`
- `pipeline/global_url_registry.py`

## Ignored Local Artifacts

- `coverage.json`
- `crawler_discovery_full.txt`
- `step11a-full-audit.txt`
- `step5-discovery.txt`

## Final Validation

The following commands passed:

- `uv run ruff check .`
- Python bytecode compilation
- `uv run python -m pipeline.release_validate`
- `git diff --check`
- `git check-ignore`

Final result:

`RELEASE VALIDATION PASSED`

The repository is ready for final diff review and commit.

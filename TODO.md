# Crawler Architecture Finalization

## Phase 1 — Dead File Proof

- [x] Step 1: Prove files with zero import reachability
  - List all crawler Python modules.
  - Find every direct and indirect static import.
  - Detect package-level re-exports through `__init__.py`.
  - Check string-based imports and `importlib` usage.
  - Mark zero-import files as candidates only; do not delete yet.
  - Confirmed zero-import candidates:
    - crawler/discovery_parts/cli.py
    - crawler/discovery_parts/constants.py
    - crawler/discovery_parts/parser.py
    - crawler/shared/constants.py
    - crawler/shared/content_selectors.py
    - crawler/shared/iso_language_gate.py

- [x] Step 2: Prove files with zero runtime call reachability
  - Trace CLI and package entry points.
  - Trace crawler startup, runtime builders, pipelines, discovery, fetching, filtering, persistence, and reporting call paths.
  - Check callbacks, registries, decorators, factories, protocols, dependency injection, and dynamically resolved symbols.
  - Confirm whether every zero-import candidate is unreachable at runtime.
  - Preserve files whose runtime reachability cannot be disproved.

- [x] Step 3: Identify legacy API and compatibility wrappers
  - Detect forwarding modules, re-export modules, aliases, deprecated APIs, transitional adapters, and compatibility facades.
  - Identify wrappers that contain no independent domain responsibility.
  - Confirm all callers can use the canonical owner directly.
  - Separate legitimate boundaries from obsolete compatibility layers.

- [x] Step 4: Delete proven dead files individually and verify each deletion
  - Deleted crawler/discovery_parts/cli.py.
  - Deleted crawler/discovery_parts/queue_manager.py.
  - Deleted crawler/shared/constants.py.
  - Deleted crawler/shared/content_selectors.py.
  - Confirmed no remaining module references.
  - Confirmed crawler compilation succeeds.

- [x] Step 5: Run full regression and certify final architecture
  - Formatting validation passed.
  - Ruff lint validation passed.
  - Basedpyright validation passed with zero errors.
  - Mypy validation passed with zero issues.
  - Python compilation validation passed.
  - Git diff whitespace validation passed.

## Phase 2 — Complete Architecture Map

- [ ] Build a table covering all remaining crawler files.
- [ ] Record each file's single responsibility.
- [ ] Record which modules call each file.
- [ ] Record which modules each file calls.
- [ ] Evaluate SRP compliance.
- [ ] Assign one decision to every file:
  - Keep
  - Split
  - Delete

### Architecture Decisions

- [x] `crawler/batch_executor.py`
  - Responsibility: Execute one persistent crawler queue batch within configured concurrency and page limits.
  - Called by: `crawler/crawler_engine.py`.
  - Calls: `crawler.config`, `crawler.database`, `crawler.progress`, `crawler.sitemap`, and `crawler.terminal_ui`.
  - SRP: Compliant.
  - Decision: Keep.
  - Evidence: All methods support the same batch-execution lifecycle: capacity control, queue loading, dashboard refresh, task construction, concurrent execution, and result handling.

## Phase 3 — Duplicate Responsibility Audit

- [ ] Detect filters implemented in multiple modules.
- [ ] Count and compare every URL normalization implementation.
- [ ] Detect policies owned by multiple modules.
- [ ] Detect duplicated discovery logic.
- [ ] Detect duplicated validation, parsing, scoring, gating, and persistence responsibilities.
- [ ] Select exactly one canonical owner for each responsibility.
- [ ] Remove duplicate implementations only after caller migration and verification.

## Phase 4 — Filter Cleanup

- [ ] Preserve one English-language filtering owner.
- [ ] Preserve one duplicate-detection owner.
- [ ] Preserve mandatory technical validation.
- [ ] Evaluate unnecessary scope filtering.
- [ ] Evaluate unnecessary region filtering.
- [ ] Evaluate heuristic gates.
- [ ] Evaluate obsolete policy layers.
- [ ] Remove only candidates proven unnecessary through call-path and behavior analysis.

## Phase 5 — Final Architecture Target

- [ ] Every file has exactly one responsibility.
- [ ] Modules are loosely coupled.
- [ ] Unrelated subsystems share no runtime state.
- [ ] Adding a feature requires changing only its owning module and direct boundary contracts.
- [ ] No obsolete compatibility layer remains.
- [ ] Every duplicated responsibility has one canonical owner.
- [ ] No dead code, unused import, commented-out implementation, or archaic logging remains.
- [x] Full crawler regression passes.
- [ ] Final architecture quality reaches 100/100.

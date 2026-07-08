# docsync TODO

## Dynamic Checklist
- [x] Step 428: Final hygiene validation attempted
- [x] Step 429: Diagnose Bandit scan scope with eza/tree
- [x] Step 430: Run Bandit only on project-owned Python modules
- [x] Step 431: Harden queue_file editor subprocess
- [x] Step 432: Normalize queue_file Bandit annotations
- [x] Step 433: Inspect pipeline subprocess runners
- [x] Step 434: Create safe subprocess helper
- [x] Step 435: Remove tracked pycache artifact from index
- [x] Step 436: Start full project audit
- [x] Step 437: Interpret first audit output
- [/] Step 438: Harden gitignore baseline
- [ ] Step 439: Rebuild clean git history from sanitized working tree
- [ ] Step 440: Run final release validation
- [ ] Step 441: Decide release freeze or further refactor

## Quality / Completion Score
Current Score: 91/100

- Modularity: 22/25
- Runtime path ownership: 23/25
- Regression safety: 22/25
- Fedora verification readiness: 24/25

## Change Log
- Preparing a hardened `.gitignore` to permanently exclude generated Python caches, runtime databases, logs, reports, coverage files, local virtualenvs, and generated build artifacts.
- Keeping source code, tests, project config, and architectural files trackable.

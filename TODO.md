# TODO.md

## Dynamic Checklist
- [x] Step 1-37: Discovery runtime bug fixed and crawl reaches Phase 2
- [x] Step 38: Make pipeline output root configurable
- [x] Step 39: Preserve project import path for pipeline subprocesses
- [/] Step 40: Restore run_python_script keyword compatibility

## Quality / Completion Score
- Architecture: 34/35
- Type Safety: 34/35
- Runtime CLI Health: 19/20
- Verification: 9/10
- Total: 96/100

## Change Log
- Pipeline subprocess import path is fixed.
- Runtime exposed `run_python_script(script=...)` compatibility issue.
- This step keeps existing callers stable without editing run_pipeline.py.

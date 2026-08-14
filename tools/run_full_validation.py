#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - subprocess module is required for controlled local tooling
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOGS_ROOT = PROJECT_ROOT / "logs" / "full_validation"


@dataclass
class Step:
    name: str
    command: list[str]
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    status: str = "pending"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the docsync project without terminating "
            "the interactive terminal on validation failures."
        )
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Return a non-zero process exit code when any "
            "validation step fails. Intended for CI only."
        ),
    )

    return parser.parse_args()


def print_header() -> None:
    print()
    print("DOCSYNC FULL VALIDATION")
    print("=======================")
    print(
        "Interactive-safe mode: validation failures will be "
        "reported without closing the terminal."
    )
    print()


def run_step(step: Step) -> None:
    try:
        completed = subprocess.run(  # nosec B603 - argument list is constructed internally without shell execution
            step.command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        step.return_code = 255
        step.status = "crashed"
        step.stderr = traceback.format_exc()
        return

    step.return_code = completed.returncode
    step.stdout = completed.stdout
    step.stderr = completed.stderr
    step.status = "passed" if completed.returncode == 0 else "failed"


def print_step_result(
    step: Step,
    *,
    index: int,
    total: int,
) -> None:
    print(f"[{index}/{total}] {step.name}")
    print("-" * 72)

    if step.stdout:
        print(step.stdout.rstrip())

    if step.stderr:
        if step.stdout:
            print()

        print("STDERR")
        print("------")
        print(step.stderr.rstrip())

    print()

    if step.return_code == 0:
        print("RESULT: PASSED")
    else:
        print(f"RESULT: FAILED (exit code {step.return_code})")

    print("=" * 72)
    print()


def write_report(
    *,
    steps: list[Step],
    successful: bool,
    strict_mode: bool,
    started_at: str,
    finished_at: str,
) -> Path:
    LOGS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")

    report_path = LOGS_ROOT / (f"validation_{timestamp}.json")

    payload = {
        "started_at": started_at,
        "finished_at": finished_at,
        "status": ("passed" if successful else "failed"),
        "interactive_safe_mode": not strict_mode,
        "strict_mode": strict_mode,
        "steps": [asdict(step) for step in steps],
    }

    temporary_path = report_path.with_suffix(".json.tmp")

    temporary_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_path.replace(report_path)

    latest_path = LOGS_ROOT / "LATEST"

    latest_path.write_text(
        str(report_path.resolve()) + "\n",
        encoding="utf-8",
    )

    return report_path


def main() -> int:
    args = parse_arguments()
    started_at = utc_now()

    print_header()

    steps = [
        Step(
            name="Project audit and safe cleanup",
            command=[
                sys.executable,
                "tools/project_audit.py",
            ],
        ),
        Step(
            name="Python compilation",
            command=[
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "-f",
                "main.py",
                "src/docsync/crawler.py",
                "src",
                "tests",
                "tools",
            ],
        ),
        Step(
            name="Safe local crawl test",
            command=[
                sys.executable,
                "tools/safe_crawl_test.py",
            ],
        ),
    ]

    for index, step in enumerate(
        steps,
        start=1,
    ):
        run_step(step)

        print_step_result(
            step,
            index=index,
            total=len(steps),
        )

    successful = all(step.return_code == 0 for step in steps)

    finished_at = utc_now()

    report_path = write_report(
        steps=steps,
        successful=successful,
        strict_mode=args.strict,
        started_at=started_at,
        finished_at=finished_at,
    )

    print()
    print("DOCSYNC VALIDATION RESULT")
    print("=========================")

    if successful:
        print("Status: SUCCESS")
        print("All validation stages passed.")
    else:
        failed_steps = [step for step in steps if step.return_code != 0]

        print("Status: FAILED")
        print(f"Failed stages: {len(failed_steps)}")

        for step in failed_steps:
            print(f"- {step.name}: exit code {step.return_code}")

        print()
        print(
            "The terminal will remain open. "
            "The failure details are shown above "
            "and stored in the report."
        )

    print(f"Report: {report_path}")
    print(f"Latest report pointer: {LOGS_ROOT / 'LATEST'}")
    print()
    print("Normal crawler command:")
    print("uv run python main.py https://github.com/tmux/tmux/wiki")
    print()

    if args.strict:
        return 0 if successful else 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        print("Validation cancelled by the user. The terminal will remain open.")
        raise SystemExit(0) from None
    except Exception as error:
        print()
        print("UNEXPECTED VALIDATOR ERROR")
        print("==========================")
        traceback.print_exc()
        print()
        print("The validator failed, but the terminal will remain open.")
        raise SystemExit(0) from error

IGNORED_MIGRATION_DIRECTORY = ".docsync-migration"

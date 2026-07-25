from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
REPORT_PATH: Final = PROJECT_ROOT / "PREFLIGHT.md"
REPORT_WIDTH: Final = 88
DEFAULT_TIMEOUT_SECONDS: Final = 300


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    category: str
    command: tuple[str, ...]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    required: bool = True


@dataclass(frozen=True, slots=True)
class PreflightResult:
    name: str
    category: str
    command: tuple[str, ...]
    return_code: int
    duration_seconds: float
    output: str
    required: bool

    @property
    def passed(self) -> bool:
        return self.return_code == 0


class PreflightFailure(RuntimeError):
    pass


def discover_python_files() -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "ls-files", "*.py"),
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip()
        message = "Unable to discover tracked Python files."

        if error:
            message = f"{message}\n{error}"

        raise PreflightFailure(message)

    files = tuple(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )

    if not files:
        raise PreflightFailure("No tracked Python files were found.")

    return files


def build_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "CI": "1",
            "NO_COLOR": "1",
            "PYTHONASYNCIODEBUG": "1",
            "PYTHONDEVMODE": "1",
            "PYTHONFAULTHANDLER": "1",
            "PYTHONUNBUFFERED": "1",
            "TERM": "dumb",
        }
    )
    return environment


def build_checks(python_files: Sequence[str]) -> tuple[PreflightCheck, ...]:
    return (
        PreflightCheck(
            name="Python compilation",
            category="Syntax",
            command=(
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "-f",
                *python_files,
            ),
            timeout_seconds=180,
        ),
        PreflightCheck(
            name="Ruff lint",
            category="Lint",
            command=("ruff", "check", *python_files),
            timeout_seconds=180,
        ),
        PreflightCheck(
            name="Ruff format",
            category="Formatting",
            command=("ruff", "format", "--check", *python_files),
            timeout_seconds=180,
        ),
        PreflightCheck(
            name="BasedPyright",
            category="Typing",
            command=("basedpyright",),
        ),
        PreflightCheck(
            name="Mypy strict",
            category="Typing",
            command=("mypy", *python_files),
        ),
        PreflightCheck(
            name="Pylint",
            category="Lint",
            command=(
                "pylint",
                "--jobs=1",
                "--score=yes",
                *python_files,
            ),
            required=False,
        ),
        PreflightCheck(
            name="Bandit security",
            category="Security",
            command=(
                "bandit",
                "-q",
                "-r",
                "crawler",
                "pipeline",
                "crawler_cli.py",
            ),
            required=False,
        ),
        PreflightCheck(
            name="Vulture dead code",
            category="Dead code",
            command=(
                "vulture",
                *python_files,
                "--min-confidence",
                "80",
            ),
            required=False,
        ),
        PreflightCheck(
            name="Radon complexity",
            category="Complexity",
            command=(
                "radon",
                "cc",
                "-s",
                "-a",
                "-n",
                "C",
                *python_files,
            ),
            timeout_seconds=180,
            required=False,
        ),
        PreflightCheck(
            name="Xenon thresholds",
            category="Complexity",
            command=(
                "xenon",
                "--max-absolute",
                "C",
                "--max-modules",
                "B",
                "--max-average",
                "B",
                *python_files,
            ),
            timeout_seconds=180,
            required=False,
        ),
        PreflightCheck(
            name="Interrogate documentation",
            category="Documentation",
            command=(
                "interrogate",
                "-v",
                "--fail-under",
                "80",
                *python_files,
            ),
            timeout_seconds=180,
            required=False,
        ),
        PreflightCheck(
            name="Deptry dependencies",
            category="Dependencies",
            command=("deptry", "."),
            required=False,
        ),
        PreflightCheck(
            name="Import Linter",
            category="Architecture",
            command=("lint-imports",),
            required=False,
        ),
    )


def command_text(command: Sequence[str]) -> str:
    return " ".join(command)


def normalize_output(output: str | bytes | None) -> str:
    if output is None:
        return ""

    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace").strip()

    return output.strip()


def executable_error_message(error: FileNotFoundError) -> str:
    if error.strerror:
        return error.strerror

    return "Executable could not be started."


def run_check(check: PreflightCheck) -> PreflightResult:
    print()
    print("=" * REPORT_WIDTH)
    print(f"PREFLIGHT: {check.name}")
    print(f"CATEGORY: {check.category}")
    print(f"COMMAND: {command_text(check.command)}")
    print("-" * REPORT_WIDTH)

    started_at = time.monotonic()

    try:
        completed = subprocess.run(
            check.command,
            cwd=PROJECT_ROOT,
            env=build_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=check.timeout_seconds,
            check=False,
        )
        return_code = completed.returncode
        output = normalize_output(completed.stdout)
    except FileNotFoundError as error:
        return_code = 127
        output = executable_error_message(error)
    except subprocess.TimeoutExpired as error:
        return_code = 124
        captured = normalize_output(error.stdout)
        output = f"Timed out after {check.timeout_seconds} seconds."

        if captured:
            output = f"{output}\n{captured}"

    duration_seconds = time.monotonic() - started_at

    if output:
        print(output)

    status = "PASS" if return_code == 0 else "FAIL"
    result_line = (
        f"RESULT: {status} | EXIT: {return_code} | DURATION: {duration_seconds:.2f}s"
    )

    print("-" * REPORT_WIDTH)
    print(result_line)

    return PreflightResult(
        name=check.name,
        category=check.category,
        command=check.command,
        return_code=return_code,
        duration_seconds=duration_seconds,
        output=output,
        required=check.required,
    )


def write_report(
    checks: Sequence[PreflightCheck],
    results: Sequence[PreflightResult],
) -> None:
    results_by_name = {result.name: result for result in results}
    lines = [
        "# Permanent Development Preflight",
        "",
        "This file is generated automatically before crawler execution.",
        "",
        "## Validation Progress",
        "",
    ]

    for check in checks:
        result = results_by_name.get(check.name)

        if result is None:
            marker = " "
            detail = "Not executed"
        elif result.passed:
            marker = "x"
            detail = f"PASS ({result.duration_seconds:.2f}s)"
        else:
            marker = " "
            detail = f"FAIL, exit {result.return_code} ({result.duration_seconds:.2f}s)"

        lines.append(f"- [{marker}] **{check.category} — {check.name}**: {detail}")

    failed = next(
        (result for result in results if result.required and not result.passed),
        None,
    )

    lines.extend(
        [
            "",
            "## Result",
            "",
        ]
    )

    if failed is None and len(results) == len(checks):
        lines.append("`PASS`: The crawler may start.")
    elif failed is not None:
        lines.extend(
            [
                "`FAIL`: The crawler was stopped before execution.",
                "",
                f"Failed check: `{failed.name}`",
                "",
                f"Command: `{command_text(failed.command)}`",
            ]
        )
    else:
        lines.append("`INCOMPLETE`: Validation did not finish.")

    if failed is not None and failed.output:
        lines.extend(
            [
                "",
                "## Failure Output",
                "",
                "```text",
                failed.output,
                "```",
            ]
        )

    _ = REPORT_PATH.write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def run_project_preflight() -> None:
    python_files = discover_python_files()
    checks = build_checks(python_files)
    results: list[PreflightResult] = []

    write_report(checks, results)

    print()
    print("PERMANENT DEVELOPMENT PREFLIGHT")
    print("=" * REPORT_WIDTH)
    print(f"Python files: {len(python_files)}")
    print(f"Checks: {len(checks)}")
    print(f"Progress report: {REPORT_PATH.relative_to(PROJECT_ROOT)}")

    for check in checks:
        result = run_check(check)
        results.append(result)
        write_report(checks, results)

        if result.required and not result.passed:
            report_name = REPORT_PATH.relative_to(PROJECT_ROOT)
            raise PreflightFailure(
                f"Preflight failed at '{result.name}'. See {report_name}."
            )

    print()
    print("=" * REPORT_WIDTH)
    print("PREFLIGHT PASS: crawler execution is allowed.")
    print("=" * REPORT_WIDTH)

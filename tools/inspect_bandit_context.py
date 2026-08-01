from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BANDIT_REPORT = PROJECT_ROOT / "logs" / "security" / "bandit.json"
PYPROJECT_FILE = PROJECT_ROOT / "pyproject.toml"

CONTEXT_BEFORE = 10
CONTEXT_AFTER = 16

PRODUCTION_REVIEW_IDS = {
    "B101",
    "B104",
    "B310",
    "B314",
    "B405",
    "B603",
}

TEST_TOOL_REVIEW_IDS = {
    "B108",
    "B603",
    "B607",
}


def load_json(path: Path) -> dict[str, Any]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected a JSON object in {path}, received {type(payload).__name__}."
        )

    return {str(key): value for key, value in payload.items()}


def normalize_report_path(filename: str) -> Path:
    relative = filename.removeprefix("./")
    return PROJECT_ROOT / relative


def print_source_context(
    *,
    source_path: Path,
    line_number: int,
    issue_id: str,
    issue_text: str,
) -> None:
    print()
    print("=" * 100)
    print(f"{issue_id}: {source_path.relative_to(PROJECT_ROOT)}:{line_number}")
    print(issue_text)
    print("-" * 100)

    if not source_path.is_file():
        print("SOURCE FILE MISSING")
        return

    lines = source_path.read_text(encoding="utf-8").splitlines()
    start = max(1, line_number - CONTEXT_BEFORE)
    end = min(len(lines), line_number + CONTEXT_AFTER)

    for current_line in range(start, end + 1):
        marker = ">>" if current_line == line_number else "  "
        content = lines[current_line - 1]
        print(f"{marker} {current_line:5}: {content}")


def classify_finding(result: dict[str, Any]) -> str:
    issue_id = str(result.get("test_id", "UNKNOWN"))
    filename = str(result.get("filename", "")).removeprefix("./")

    if issue_id in {"B314", "B405"}:
        return "REMEDIATE: replace unsafe XML parser"

    if issue_id == "B310":
        return "REVIEW_AND_REMEDIATE: prove HTTP/HTTPS-only URL opening"

    if issue_id == "B101" and not filename.startswith("tests/"):
        return "REMEDIATE: replace production assert with explicit validation"

    if issue_id == "B104":
        return "LIKELY_FALSE_POSITIVE: blocked-hostname constant"

    if issue_id == "B108":
        return "REMEDIATE: remove hardcoded /tmp directory"

    if issue_id == "B607":
        return "REMEDIATE: resolve executable to an absolute path"

    if issue_id == "B101" and filename.startswith("tests/"):
        return "CONFIGURE: pytest assertions are expected"

    if issue_id in {"B404", "B603"}:
        return "REVIEW: intentional subprocess use; verify fixed argument lists"

    return "REVIEW"


def main() -> int:
    if not BANDIT_REPORT.is_file():
        print(f"Bandit report not found: {BANDIT_REPORT}")
        return 1

    payload = load_json(BANDIT_REPORT)
    results: list[dict[str, Any]] = payload.get("results", [])

    print("DOCSYNC BANDIT REMEDIATION CONTEXT")
    print("=" * 100)
    print(f"Report: {BANDIT_REPORT}")
    print(f"Findings: {len(results)}")

    classifications = Counter(classify_finding(result) for result in results)

    print()
    print("CLASSIFICATION")
    print("-" * 100)

    for classification, count in sorted(classifications.items()):
        print(f"{count:3}  {classification}")

    print()
    print("PYPROJECT SECURITY CONFIGURATION")
    print("-" * 100)

    if PYPROJECT_FILE.is_file():
        pyproject = tomllib.loads(PYPROJECT_FILE.read_text(encoding="utf-8"))
        print("dependencies:")
        for dependency in pyproject.get("project", {}).get(
            "dependencies",
            [],
        ):
            print(f"  - {dependency}")

        print()
        print("dependency-groups.dev:")
        for dependency in pyproject.get("dependency-groups", {}).get("dev", []):
            print(f"  - {dependency}")

        print()
        print("tool.bandit:")
        bandit_config = pyproject.get("tool", {}).get("bandit", {})
        print(json.dumps(bandit_config, indent=2, sort_keys=True))
    else:
        print("pyproject.toml is missing.")

    selected_results: list[dict[str, Any]] = []

    for result in results:
        issue_id = str(result.get("test_id", "UNKNOWN"))
        filename = str(result.get("filename", "")).removeprefix("./")

        is_production = filename in {
            "main.py",
            "src/docsync/crawler.py",
        }

        if is_production and issue_id in PRODUCTION_REVIEW_IDS:
            selected_results.append(result)
            continue

        if (
            filename.startswith(("tests/", "tools/"))
            and issue_id in TEST_TOOL_REVIEW_IDS
        ):
            selected_results.append(result)

    selected_results.sort(
        key=lambda result: (
            str(result.get("filename", "")),
            int(result.get("line_number", 0)),
            str(result.get("test_id", "")),
        )
    )

    print()
    print("SELECTED SOURCE CONTEXT")
    print("=" * 100)

    for result in selected_results:
        filename = str(result.get("filename", ""))
        source_path = normalize_report_path(filename)
        line_number = int(result.get("line_number", 1))
        issue_id = str(result.get("test_id", "UNKNOWN"))
        issue_text = str(result.get("issue_text", ""))

        print_source_context(
            source_path=source_path,
            line_number=line_number,
            issue_id=issue_id,
            issue_text=issue_text,
        )

    print()
    print("=" * 100)
    print("RESULT: BANDIT REMEDIATION CONTEXT CAPTURED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

IGNORED_MIGRATION_DIRECTORY = ".docsync-migration"

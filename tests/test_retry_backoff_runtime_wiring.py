"""Deterministic retry/backoff and failed-request lifecycle contracts."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PACKAGE_CRAWLER_PATH: Final[Path] = ROOT / "src" / "docsync" / "crawler.py"
EXPECTED_PACKAGE_MAX_REQUEST_RETRIES: Final[int] = 2
EXPECTED_LEGACY_MAX_SESSION_ROTATIONS: Final[int] = 0


def _parse(path: Path) -> ast.Module:
    assert path.is_file(), f"Required source file does not exist: {path}"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr

    return ""


def _integer_constant(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value

    return None


def _assignment_integer(
    tree: ast.Module,
    variable_name: str,
) -> int:
    for node in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None

        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue

        if value is None:
            continue

        for target in targets:
            if not isinstance(target, ast.Name):
                continue

            if target.id != variable_name:
                continue

            integer_value = _integer_constant(value)
            assert integer_value is not None, (
                f"{variable_name} must be assigned an integer literal."
            )
            return integer_value

    raise AssertionError(f"{variable_name} assignment was not found.")


def _async_function(
    tree: ast.Module,
    function_name: str,
) -> ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name:
            return node

    raise AssertionError(f"async function {function_name}() was not found.")


def _crawler_constructor_calls(
    node: ast.AST,
) -> list[ast.Call]:
    supported_crawlers = {
        "BasicCrawler",
        "BeautifulSoupCrawler",
        "HttpCrawler",
        "PlaywrightCrawler",
        "ParselCrawler",
    }

    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and _qualified_name(child.func).split(".")[-1] in supported_crawlers
    ]


def _keyword_argument(
    call: ast.Call,
    keyword_name: str,
) -> ast.expr:
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value

    raise AssertionError(
        f"{_qualified_name(call.func)}() does not configure {keyword_name}."
    )


def _decorator_names(function: ast.AsyncFunctionDef) -> set[str]:
    return {_qualified_name(decorator) for decorator in function.decorator_list}


def _nested_async_functions(
    function: ast.AsyncFunctionDef,
) -> list[ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.AsyncFunctionDef) and node is not function
    ]


def _find_failed_request_handler(
    function: ast.AsyncFunctionDef,
) -> ast.AsyncFunctionDef:
    for nested_function in _nested_async_functions(function):
        if any(
            decorator.endswith(".failed_request_handler")
            for decorator in _decorator_names(nested_function)
        ):
            return nested_function

    raise AssertionError(
        f"{function.name}() does not register a failed_request_handler."
    )


def _contains_increment(
    function: ast.AsyncFunctionDef,
    object_name: str,
    attribute_name: str,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.AugAssign):
            continue

        if not isinstance(node.op, ast.Add):
            continue

        if not isinstance(node.target, ast.Attribute):
            continue

        if node.target.attr != attribute_name:
            continue

        if _qualified_name(node.target.value) != object_name:
            continue

        if _integer_constant(node.value) == 1:
            return True

    return False


def _contains_log_call(
    function: ast.AsyncFunctionDef,
    method_name: str,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue

        if not isinstance(node.func, ast.Attribute):
            continue

        if node.func.attr != method_name:
            continue

        qualified = _qualified_name(node.func)
        if qualified.endswith(f".log.{method_name}"):
            return True

    return False


def _contains_crawler_run(
    function: ast.AsyncFunctionDef,
) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Await):
            continue

        call = node.value
        if not isinstance(call, ast.Call):
            continue

        if _qualified_name(call.func) == "crawler.run":
            return True

    return False


def test_package_retry_constant_is_deterministic() -> None:
    tree = _parse(PACKAGE_CRAWLER_PATH)

    configured_retries = _assignment_integer(
        tree,
        "DEFAULT_MAX_REQUEST_RETRIES",
    )

    assert configured_retries == EXPECTED_PACKAGE_MAX_REQUEST_RETRIES


def test_package_crawler_uses_retry_constant_at_runtime_construction() -> None:
    crawler_path = Path("src/docsync/crawler.py")
    tree = ast.parse(
        crawler_path.read_text(encoding="utf-8"),
        filename=str(crawler_path),
    )

    run_crawler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name in {"run_crawler", "_run_crawler"}
    )

    def call_name(call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    crawler_calls = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.Call)
        and call_name(node) in {"BeautifulSoupCrawler", "PlaywrightCrawler"}
    ]

    calls_by_constructor = {call_name(call): call for call in crawler_calls}

    assert set(calls_by_constructor) == {
        "BeautifulSoupCrawler",
        "PlaywrightCrawler",
    }, "run_crawler() must preserve HTTP and browser crawler construction."

    retry_values: dict[str, ast.expr] = {}

    for constructor_name, constructor_call in calls_by_constructor.items():
        retry_keywords = [
            keyword
            for keyword in constructor_call.keywords
            if keyword.arg == "max_request_retries"
        ]

        assert len(retry_keywords) == 1, (
            f"{constructor_name} must configure max_request_retries exactly once."
        )

        if constructor_name is None:
            continue

        retry_values[constructor_name] = retry_keywords[0].value

    assert all(isinstance(value, ast.Name) for value in retry_values.values()), (
        "Every crawler must reference a retry constant."
    )

    retry_constant_names = {
        value.id for value in retry_values.values() if isinstance(value, ast.Name)
    }

    assert len(retry_constant_names) == 1, (
        "HTTP and browser crawlers must use the same retry constant."
    )

    retry_constant_name = next(iter(retry_constant_names))

    module_constants = {
        target.id
        for statement in tree.body
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        if isinstance(target, ast.Name)
    }

    assert retry_constant_name in module_constants, (
        "The shared retry configuration must reference a module-level constant."
    )


def test_package_retry_budget_represents_initial_attempt_plus_two_retries() -> None:
    tree = _parse(PACKAGE_CRAWLER_PATH)
    retry_count = _assignment_integer(tree, "DEFAULT_MAX_REQUEST_RETRIES")

    total_attempt_budget = 1 + retry_count

    assert total_attempt_budget == 3


def test_package_crawler_does_not_disable_retry_per_request() -> None:
    tree = _parse(PACKAGE_CRAWLER_PATH)
    run_crawler = _async_function(tree, "run_crawler")

    no_retry_assignments = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Attribute) and target.attr == "no_retry"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
    ]

    no_retry_keywords = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.keyword)
        and node.arg in {"no_retry", "noRetry"}
        and isinstance(node.value, ast.Constant)
        and node.value.value is True
    ]

    assert not no_retry_assignments
    assert not no_retry_keywords


def test_package_crawler_executes_crawlee_run_lifecycle() -> None:
    tree = _parse(PACKAGE_CRAWLER_PATH)
    run_crawler = _async_function(tree, "run_crawler")

    assert _contains_crawler_run(run_crawler)


def _canonical_retry_tree() -> ast.Module:
    crawler_path = Path("src/docsync/crawler.py")
    return ast.parse(
        crawler_path.read_text(encoding="utf-8"),
        filename=str(crawler_path),
    )


def _canonical_run_crawler(
    tree: ast.Module,
) -> ast.AsyncFunctionDef | ast.FunctionDef:
    function = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name in {"run_crawler", "_run_crawler"}
        ),
        None,
    )

    assert function is not None, "Canonical run_crawler() was not found."
    return function


def _canonical_call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id

    if isinstance(call.func, ast.Attribute):
        return call.func.attr

    return None


def _canonical_crawler_calls(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
) -> dict[str, ast.Call]:
    calls = {
        name: node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        if (name := _canonical_call_name(node))
        in {"BeautifulSoupCrawler", "PlaywrightCrawler"}
    }

    assert set(calls) == {
        "BeautifulSoupCrawler",
        "PlaywrightCrawler",
    }, "Canonical crawler must preserve HTTP and Playwright dispatch."

    return calls


def _canonical_failed_handler(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
) -> ast.AsyncFunctionDef | ast.FunctionDef:
    handlers = [
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and node.name == "failed_handler"
    ]

    assert len(handlers) == 1, (
        "Canonical run_crawler() must define exactly one failed_handler()."
    )
    return handlers[0]


def _canonical_decorator_names(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
) -> set[str]:
    names: set[str] = set()

    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call):
            decorator = decorator.func

        if isinstance(decorator, ast.Attribute):
            names.add(decorator.attr)
        elif isinstance(decorator, ast.Name):
            names.add(decorator.id)

    return names


def _canonical_augmented_metric_names(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
) -> set[str]:
    names: set[str] = set()

    for node in ast.walk(function):
        if not isinstance(node, ast.AugAssign):
            continue

        target = node.target
        if not isinstance(target, ast.Attribute):
            continue

        names.add(target.attr)

    return names


def _canonical_log_levels(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
) -> set[str]:
    levels: set[str] = set()

    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue

        if not isinstance(node.func, ast.Attribute):
            continue

        if node.func.attr in {
            "critical",
            "error",
            "exception",
            "warning",
            "info",
            "debug",
        }:
            levels.add(node.func.attr)

    return levels


def test_canonical_failed_request_handler_is_registered() -> None:
    tree = _canonical_retry_tree()
    run_crawler = _canonical_run_crawler(tree)
    failed_handler = _canonical_failed_handler(run_crawler)

    assert "failed_request_handler" in _canonical_decorator_names(failed_handler)


def test_canonical_failed_request_handler_accepts_context_and_error() -> None:
    tree = _canonical_retry_tree()
    run_crawler = _canonical_run_crawler(tree)
    failed_handler = _canonical_failed_handler(run_crawler)

    positional_arguments = [
        argument.arg
        for argument in (
            list(failed_handler.args.posonlyargs) + list(failed_handler.args.args)
        )
    ]

    assert positional_arguments[:2] == ["context", "error"]


def test_canonical_failed_request_handler_updates_failure_lifecycle() -> None:
    tree = _canonical_retry_tree()
    run_crawler = _canonical_run_crawler(tree)
    failed_handler = _canonical_failed_handler(run_crawler)

    assert "failed" in _canonical_augmented_metric_names(failed_handler)
    assert _canonical_log_levels(failed_handler) & {
        "error",
        "exception",
        "critical",
    }


def test_canonical_http_and_browser_crawlers_share_retry_budget() -> None:
    tree = _canonical_retry_tree()
    run_crawler = _canonical_run_crawler(tree)
    crawler_calls = _canonical_crawler_calls(run_crawler)

    retry_values: dict[str, ast.expr] = {}

    for constructor_name, constructor_call in crawler_calls.items():
        retry_keywords = [
            keyword
            for keyword in constructor_call.keywords
            if keyword.arg == "max_request_retries"
        ]

        assert len(retry_keywords) == 1, (
            f"{constructor_name} must configure max_request_retries exactly once."
        )
        retry_values[constructor_name] = retry_keywords[0].value

    assert all(isinstance(value, ast.Name) for value in retry_values.values()), (
        "Both crawler constructors must reference a retry constant."
    )

    constant_names = {
        value.id for value in retry_values.values() if isinstance(value, ast.Name)
    }

    assert constant_names == {"DEFAULT_MAX_REQUEST_RETRIES"}


def test_canonical_retry_budget_allows_initial_attempt_plus_retries() -> None:
    tree = _canonical_retry_tree()

    retry_assignment = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name)
                and target.id == "DEFAULT_MAX_REQUEST_RETRIES"
                for target in (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
            )
        ),
        None,
    )

    assert retry_assignment is not None

    retry_value = retry_assignment.value
    assert isinstance(retry_value, ast.Constant)
    assert isinstance(retry_value.value, int)
    assert retry_value.value >= 0
    assert 1 + retry_value.value >= 1


def test_canonical_crawler_does_not_disable_request_retries() -> None:
    tree = _canonical_retry_tree()
    run_crawler = _canonical_run_crawler(tree)

    disabled_assignments = [
        node
        for node in ast.walk(run_crawler)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute) and target.attr in {"no_retry", "noRetry"}
    ]

    disabled_keywords = [
        keyword
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg in {"no_retry", "noRetry"}
    ]

    assert disabled_assignments == []
    assert disabled_keywords == []

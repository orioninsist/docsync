"""Contracts for robots.txt configuration and crawler wiring."""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
from typing import Any

from docsync.config import Settings

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "docsync"
CONFIG_FILE = PACKAGE_ROOT / "config.py"

ROBOTS_SETTING_NAMES = {
    "respect_robots_txt",
    "respect_robots",
    "robots_txt",
    "robots",
}


def _python_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _read_source(path: Path) -> str:
    assert path.is_file(), f"Missing source file: {path}"

    return path.read_text(encoding="utf-8")


def _read_ast(path: Path) -> ast.Module:
    return ast.parse(
        _read_source(path),
        filename=str(path),
    )


def _settings_field_names() -> set[str]:
    names: set[str] = set()

    if dataclasses.is_dataclass(Settings):
        names.update(field.name for field in dataclasses.fields(Settings))

    annotations = getattr(
        Settings,
        "__annotations__",
        {},
    )

    if isinstance(annotations, dict):
        names.update(str(name) for name in annotations)

    model_fields = getattr(
        Settings,
        "model_fields",
        None,
    )

    if isinstance(model_fields, dict):
        names.update(str(name) for name in model_fields)

    legacy_fields = getattr(
        Settings,
        "__fields__",
        None,
    )

    if isinstance(legacy_fields, dict):
        names.update(str(name) for name in legacy_fields)

    try:
        signature = inspect.signature(Settings)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        names.update(name for name in signature.parameters if name != "self")

    return names


def _robots_setting_name() -> str:
    matches = sorted(_settings_field_names() & ROBOTS_SETTING_NAMES)

    assert matches, (
        "Settings must expose a robots.txt control field. "
        f"Available fields: {sorted(_settings_field_names())}"
    )

    return matches[0]


def _dataclass_default(
    setting_name: str,
) -> Any:
    if not dataclasses.is_dataclass(Settings):
        return dataclasses.MISSING

    for field in dataclasses.fields(Settings):
        if field.name != setting_name:
            continue

        if field.default is not dataclasses.MISSING:
            return field.default

        if field.default_factory is not dataclasses.MISSING:
            return field.default_factory()

    return dataclasses.MISSING


def _signature_default(
    setting_name: str,
) -> Any:
    try:
        signature = inspect.signature(Settings)
    except (TypeError, ValueError):
        return inspect.Parameter.empty

    parameter = signature.parameters.get(setting_name)

    if parameter is None:
        return inspect.Parameter.empty

    return parameter.default


def _pydantic_default(
    setting_name: str,
) -> Any:
    model_fields = getattr(
        Settings,
        "model_fields",
        None,
    )

    if isinstance(model_fields, dict) and setting_name in model_fields:
        field = model_fields[setting_name]

        get_default = getattr(
            field,
            "get_default",
            None,
        )

        if callable(get_default):
            try:
                return get_default(call_default_factory=True)
            except TypeError:
                return get_default()

        return getattr(field, "default", None)

    legacy_fields = getattr(
        Settings,
        "__fields__",
        None,
    )

    if isinstance(legacy_fields, dict) and setting_name in legacy_fields:
        return getattr(
            legacy_fields[setting_name],
            "default",
            None,
        )

    return None


def _ast_default(
    setting_name: str,
) -> Any:
    tree = _read_ast(CONFIG_FILE)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == setting_name
            and node.value is not None
        ):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue

        if isinstance(node, ast.Assign):
            matching_target = any(
                isinstance(target, ast.Name) and target.id == setting_name
                for target in node.targets
            )

            if matching_target:
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue

    return None


def _resolved_default(
    setting_name: str,
) -> Any:
    dataclass_default = _dataclass_default(setting_name)

    if dataclass_default is not dataclasses.MISSING:
        return dataclass_default

    signature_default = _signature_default(setting_name)

    if signature_default is not inspect.Parameter.empty:
        return signature_default

    pydantic_default = _pydantic_default(setting_name)

    if pydantic_default is not None:
        return pydantic_default

    return _ast_default(setting_name)


def _attribute_chain(
    node: ast.AST,
) -> tuple[str, ...]:
    parts: list[str] = []
    current = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        parts.append(current.id)

    return tuple(reversed(parts))


def _references_setting(
    node: ast.AST,
    setting_name: str,
) -> bool:
    for descendant in ast.walk(node):
        if isinstance(descendant, ast.Name) and descendant.id == setting_name:
            return True

        if isinstance(descendant, ast.Attribute):
            chain = _attribute_chain(descendant)

            if chain and chain[-1] == setting_name:
                return True

    return False


def _keyword_wiring_locations(
    setting_name: str,
) -> list[str]:
    locations: list[str] = []

    for path in _python_files():
        tree = _read_ast(path)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            for keyword in node.keywords:
                if keyword.arg != setting_name:
                    continue

                if (
                    isinstance(
                        keyword.value,
                        ast.Constant,
                    )
                    and keyword.value.value is True
                ) or _references_setting(
                    keyword.value,
                    setting_name,
                ):
                    relative = path.relative_to(ROOT)
                    locations.append(f"{relative}:{node.lineno}")

    return locations


def _attribute_usage_locations(
    setting_name: str,
) -> list[str]:
    locations: list[str] = []

    for path in _python_files():
        tree = _read_ast(path)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue

            chain = _attribute_chain(node)

            if len(chain) >= 2 and chain[-1] == setting_name:
                relative = path.relative_to(ROOT)
                locations.append(f"{relative}:{node.lineno}")

    return locations


def _configuration_mapping_locations(
    setting_name: str,
) -> list[str]:
    locations: list[str] = []

    for path in _python_files():
        tree = _read_ast(path)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue

            for key, value in zip(
                node.keys,
                node.values,
                strict=True,
            ):
                if not (isinstance(key, ast.Constant) and key.value == setting_name):
                    continue

                if (
                    isinstance(value, ast.Constant) and value.value is True
                ) or _references_setting(
                    value,
                    setting_name,
                ):
                    relative = path.relative_to(ROOT)
                    locations.append(f"{relative}:{node.lineno}")

    return locations


def test_settings_exposes_robots_control() -> None:
    setting_name = _robots_setting_name()

    assert setting_name in ROBOTS_SETTING_NAMES


def test_robots_control_has_boolean_contract() -> None:
    setting_name = _robots_setting_name()

    annotations = getattr(
        Settings,
        "__annotations__",
        {},
    )
    annotation = annotations.get(setting_name)

    if annotation is None:
        config_tree = _read_ast(CONFIG_FILE)

        annotation_nodes = [
            node.annotation
            for node in ast.walk(config_tree)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == setting_name
        ]

        assert annotation_nodes, (
            f"Settings.{setting_name} must declare an explicit boolean type."
        )

        annotation_texts = {ast.unparse(node) for node in annotation_nodes}

        assert any(
            text in {"bool", "builtins.bool"}
            or text.endswith("| None")
            or text.startswith("Optional[bool]")
            for text in annotation_texts
        ), (
            f"Settings.{setting_name} must use a "
            "boolean-compatible type; received "
            f"{sorted(annotation_texts)}."
        )

        return

    if annotation is bool:
        return

    annotation_text = str(annotation)

    assert "bool" in annotation_text.lower(), (
        f"Settings.{setting_name} must use a "
        "boolean-compatible type; received "
        f"{annotation!r}."
    )


def test_robots_setting_is_used_by_runtime_configuration() -> None:
    setting_name = _robots_setting_name()

    keyword_locations = _keyword_wiring_locations(setting_name)
    attribute_locations = _attribute_usage_locations(setting_name)
    mapping_locations = _configuration_mapping_locations(setting_name)

    all_locations = sorted(
        set(keyword_locations + attribute_locations + mapping_locations)
    )

    assert all_locations, (
        f"{setting_name} is declared but never used "
        "by the docsync runtime configuration."
    )


def test_config_declares_robots_setting() -> None:
    setting_name = _robots_setting_name()
    tree = _read_ast(CONFIG_FILE)

    declarations = {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assignments = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert setting_name in (declarations | assignments), (
        f"{CONFIG_FILE.relative_to(ROOT)} must declare {setting_name}."
    )

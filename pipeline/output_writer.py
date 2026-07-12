"""Atomically write pipeline outputs and persist deterministic output state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final, TypeAlias, cast

from pipeline.domain import OutputWriteError, StatePersistenceError
from pipeline.merge_engine import MergePlan, MergeTargetPlan

STATE_SCHEMA_VERSION: Final[int] = 1
DEFAULT_STATE_FILE_NAME: Final[str] = "output-state.json"
UTF8: Final[str] = "utf-8"
JSON_INDENT: Final[int] = 2
FILE_MODE: Final[int] = 0o644
DIRECTORY_MODE: Final[int] = 0o755
HASH_CHUNK_SIZE: Final[int] = 1024 * 1024
SHA256_HEX_LENGTH: Final[int] = 64

PersistenceErrorType: TypeAlias = type[OutputWriteError] | type[StatePersistenceError]


@dataclass(frozen=True, slots=True)
class OutputDocument:
    """Describe one planned output document and its complete content."""

    target_name: str
    content: str
    source_signature: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized_target = _normalize_target_name(self.target_name)

        if not isinstance(self.content, str):
            raise TypeError("content must be a string")

        normalized_signature = _normalize_signature(
            self.source_signature,
            OutputWriteError,
        )

        object.__setattr__(self, "target_name", normalized_target)
        object.__setattr__(self, "source_signature", normalized_signature)


@dataclass(frozen=True, slots=True)
class PersistedOutput:
    """Represent one output entry stored in persistent state."""

    target_name: str
    content_hash: str
    size_bytes: int
    source_signature: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized_target = _normalize_target_name_for_state(self.target_name)
        normalized_hash = _normalize_hash(self.content_hash)

        if self.size_bytes < 0:
            raise StatePersistenceError(
                "persisted output size must not be negative",
            )

        normalized_signature = _normalize_signature(
            self.source_signature,
            StatePersistenceError,
        )

        object.__setattr__(self, "target_name", normalized_target)
        object.__setattr__(self, "content_hash", normalized_hash)
        object.__setattr__(self, "source_signature", normalized_signature)


@dataclass(frozen=True, slots=True)
class OutputState:
    """Contain immutable persisted state for one project output set."""

    project_name: str
    outputs: tuple[PersistedOutput, ...]
    schema_version: int = STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalized_project = _normalize_project_name_for_state(
            self.project_name,
        )

        if self.schema_version != STATE_SCHEMA_VERSION:
            raise StatePersistenceError(
                f"unsupported output state schema: {self.schema_version}",
            )

        ordered_outputs = _order_persisted_outputs(self.outputs)
        _reject_duplicate_persisted_outputs(ordered_outputs)

        object.__setattr__(self, "project_name", normalized_project)
        object.__setattr__(self, "outputs", ordered_outputs)


@dataclass(frozen=True, slots=True)
class OutputWriteResult:
    """Summarize one atomic output synchronization operation."""

    written: tuple[Path, ...]
    unchanged: tuple[Path, ...]
    removed: tuple[Path, ...]
    state_path: Path

    @property
    def changed(self) -> bool:
        """Return whether any output file changed."""
        return bool(self.written or self.removed)


@dataclass(frozen=True, slots=True)
class _SynchronizationPaths:
    output_root: Path
    state_root: Path
    state_path: Path


@dataclass(slots=True)
class _SynchronizationResultBuilder:
    written: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    outputs: list[PersistedOutput] = field(default_factory=list)

    def build(self, state_path: Path) -> OutputWriteResult:
        """Return the immutable synchronization result."""
        return OutputWriteResult(
            written=tuple(self.written),
            unchanged=tuple(self.unchanged),
            removed=tuple(self.removed),
            state_path=state_path,
        )


@dataclass(frozen=True, slots=True)
class AtomicOutputWriter:
    """Synchronize planned outputs and persistent state atomically per file."""

    output_root: Path
    state_root: Path
    state_file_name: str = DEFAULT_STATE_FILE_NAME

    def __post_init__(self) -> None:
        normalized_output_root = _normalize_root(
            self.output_root,
            "output_root",
        )
        normalized_state_root = _normalize_root(
            self.state_root,
            "state_root",
        )
        normalized_state_name = _normalize_state_file_name(
            self.state_file_name,
        )

        object.__setattr__(self, "output_root", normalized_output_root)
        object.__setattr__(self, "state_root", normalized_state_root)
        object.__setattr__(self, "state_file_name", normalized_state_name)

    def synchronize(
        self,
        plan: MergePlan,
        documents: Sequence[OutputDocument],
    ) -> OutputWriteResult:
        """Write changed outputs, remove stale outputs, and persist state."""
        ordered_documents = _validate_documents_against_plan(
            plan,
            documents,
        )
        paths = self._build_synchronization_paths(plan.project_name)
        previous_state = self.load_state(
            project_name=plan.project_name,
            state_path=paths.state_path,
        )
        result = _SynchronizationResultBuilder()

        self._synchronize_documents(
            documents=ordered_documents,
            output_root=paths.output_root,
            previous_state=previous_state,
            result=result,
        )
        self._remove_stale_documents(
            documents=ordered_documents,
            output_root=paths.output_root,
            previous_state=previous_state,
            result=result,
        )
        self._persist_next_state(
            project_name=plan.project_name,
            state_path=paths.state_path,
            previous_state=previous_state,
            result=result,
        )

        _sync_directory(paths.output_root)
        _sync_directory(paths.state_root)

        return result.build(paths.state_path)

    def load_state(
        self,
        *,
        project_name: str,
        state_path: Path | None = None,
    ) -> OutputState:
        """Load validated state or return an empty state when absent."""
        normalized_project = _normalize_project_name_for_state(project_name)
        resolved_state_path = state_path or self._default_state_path(
            normalized_project,
        )

        if not resolved_state_path.exists():
            return OutputState(
                project_name=normalized_project,
                outputs=(),
            )

        _validate_existing_state_path(resolved_state_path)
        raw_state = _read_json_state(resolved_state_path)

        return _decode_state(
            raw_state,
            expected_project_name=normalized_project,
        )

    def save_state(
        self,
        state: OutputState,
        *,
        state_path: Path | None = None,
    ) -> Path:
        """Persist immutable output state using atomic replacement."""
        resolved_state_path = state_path or self._default_state_path(
            state.project_name,
        )
        encoded_state = _encode_state(state).encode(UTF8)

        _prepare_directory(
            resolved_state_path.parent,
            StatePersistenceError,
        )
        _atomic_write_bytes(
            resolved_state_path,
            encoded_state,
            StatePersistenceError,
        )

        return resolved_state_path

    def _build_synchronization_paths(
        self,
        project_name: str,
    ) -> _SynchronizationPaths:
        project_directory = _project_directory_name(project_name)
        output_root = self.output_root / project_directory
        state_root = self.state_root / project_directory

        _prepare_directory(output_root, OutputWriteError)
        _prepare_directory(state_root, StatePersistenceError)

        return _SynchronizationPaths(
            output_root=output_root,
            state_root=state_root,
            state_path=state_root / self.state_file_name,
        )

    def _default_state_path(self, project_name: str) -> Path:
        return (
            self.state_root
            / _project_directory_name(project_name)
            / self.state_file_name
        )

    def _synchronize_documents(
        self,
        *,
        documents: Sequence[OutputDocument],
        output_root: Path,
        previous_state: OutputState,
        result: _SynchronizationResultBuilder,
    ) -> None:
        previous_by_target = {
            output.target_name: output for output in previous_state.outputs
        }

        for document in documents:
            persisted_output = _build_persisted_output(document)
            target_path = _safe_child_path(
                output_root,
                document.target_name,
            )
            previous_output = previous_by_target.get(
                document.target_name,
            )

            _synchronize_single_document(
                document=document,
                target_path=target_path,
                expected=persisted_output,
                previous=previous_output,
                result=result,
            )

    @staticmethod
    def _remove_stale_documents(
        *,
        documents: Sequence[OutputDocument],
        output_root: Path,
        previous_state: OutputState,
        result: _SynchronizationResultBuilder,
    ) -> None:
        expected_names = {document.target_name for document in documents}

        for persisted_output in previous_state.outputs:
            if persisted_output.target_name in expected_names:
                continue

            target_path = _safe_child_path(
                output_root,
                persisted_output.target_name,
            )

            if _remove_stale_output(target_path):
                result.removed.append(target_path)

    def _persist_next_state(
        self,
        *,
        project_name: str,
        state_path: Path,
        previous_state: OutputState,
        result: _SynchronizationResultBuilder,
    ) -> None:
        next_state = OutputState(
            project_name=project_name,
            outputs=tuple(result.outputs),
        )

        if next_state == previous_state and state_path.is_file():
            return

        self.save_state(
            next_state,
            state_path=state_path,
        )


def synchronize_outputs(
    *,
    plan: MergePlan,
    documents: Sequence[OutputDocument],
    output_root: Path,
    state_root: Path,
    state_file_name: str = DEFAULT_STATE_FILE_NAME,
) -> OutputWriteResult:
    """Synchronize outputs through the default functional boundary."""
    writer = AtomicOutputWriter(
        output_root=output_root,
        state_root=state_root,
        state_file_name=state_file_name,
    )

    return writer.synchronize(
        plan=plan,
        documents=documents,
    )


def _validate_documents_against_plan(
    plan: MergePlan,
    documents: Sequence[OutputDocument],
) -> tuple[OutputDocument, ...]:
    documents_by_target = _index_documents(documents)
    _validate_target_membership(plan, documents_by_target)

    return tuple(
        _document_for_target(target, documents_by_target) for target in plan.targets
    )


def _index_documents(
    documents: Sequence[OutputDocument],
) -> dict[str, OutputDocument]:
    indexed: dict[str, OutputDocument] = {}

    for document in documents:
        canonical_name = document.target_name.casefold()

        if canonical_name in indexed:
            raise OutputWriteError(
                f"duplicate output document: {document.target_name}",
            )

        indexed[canonical_name] = document

    return indexed


def _validate_target_membership(
    plan: MergePlan,
    documents_by_target: Mapping[str, OutputDocument],
) -> None:
    planned_names = {target.target_name.casefold() for target in plan.targets}
    supplied_names = set(documents_by_target)

    if planned_names != supplied_names:
        raise OutputWriteError(
            "output documents must exactly match merge plan targets",
        )


def _document_for_target(
    target: MergeTargetPlan,
    documents_by_target: Mapping[str, OutputDocument],
) -> OutputDocument:
    document = documents_by_target[target.target_name.casefold()]

    if document.target_name != target.target_name:
        raise OutputWriteError(
            "output target case must exactly match merge plan",
        )

    if document.source_signature != target.source_signature:
        raise OutputWriteError(
            f"source signature mismatch for {target.target_name}",
        )

    return document


def _build_persisted_output(
    document: OutputDocument,
) -> PersistedOutput:
    encoded_content = document.content.encode(UTF8)

    return PersistedOutput(
        target_name=document.target_name,
        content_hash=_hash_bytes(encoded_content),
        size_bytes=len(encoded_content),
        source_signature=document.source_signature,
    )


def _synchronize_single_document(
    *,
    document: OutputDocument,
    target_path: Path,
    expected: PersistedOutput,
    previous: PersistedOutput | None,
    result: _SynchronizationResultBuilder,
) -> None:
    if _output_is_current(
        target_path=target_path,
        expected=expected,
        previous=previous,
    ):
        result.unchanged.append(target_path)
    else:
        _atomic_write_bytes(
            target_path,
            document.content.encode(UTF8),
            OutputWriteError,
        )
        result.written.append(target_path)

    result.outputs.append(expected)


def _output_is_current(
    *,
    target_path: Path,
    expected: PersistedOutput,
    previous: PersistedOutput | None,
) -> bool:
    if previous != expected:
        return False

    if target_path.is_symlink() or not target_path.is_file():
        return False

    if not _file_size_matches(target_path, expected.size_bytes):
        return False

    return _file_hash_matches(target_path, expected.content_hash)


def _file_size_matches(path: Path, expected_size: int) -> bool:
    try:
        return path.stat().st_size == expected_size
    except OSError:
        return False


def _file_hash_matches(path: Path, expected_hash: str) -> bool:
    try:
        return _hash_file(path) == expected_hash
    except OSError:
        return False


def _remove_stale_output(target_path: Path) -> bool:
    if not target_path.exists() and not target_path.is_symlink():
        return False

    if target_path.is_symlink():
        raise OutputWriteError(
            f"refusing to remove symbolic-link output: {target_path}",
        )

    if not target_path.is_file():
        raise OutputWriteError(
            f"stale output is not a regular file: {target_path}",
        )

    try:
        target_path.unlink()
    except OSError as error:
        raise OutputWriteError(
            f"failed to remove stale output: {target_path}",
        ) from error

    return True


def _atomic_write_bytes(
    target_path: Path,
    content: bytes,
    error_type: PersistenceErrorType,
) -> None:
    _prepare_directory(target_path.parent, error_type)
    _reject_symlink_target(target_path, error_type)

    temporary_path = _create_temporary_file(
        target_path,
        content,
        error_type,
    )

    try:
        os.replace(temporary_path, target_path)
        target_path.chmod(FILE_MODE)
        _sync_directory(target_path.parent)
    except OSError as error:
        _remove_temporary_file(temporary_path)
        raise error_type(
            f"failed atomic replacement: {target_path}",
        ) from error


def _create_temporary_file(
    target_path: Path,
    content: bytes,
    error_type: PersistenceErrorType,
) -> Path:
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=target_path.parent,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        return temporary_path
    except OSError as error:
        if temporary_path is not None:
            _remove_temporary_file(temporary_path)

        raise error_type(
            f"failed to create temporary output: {target_path}",
        ) from error


def _remove_temporary_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _reject_symlink_target(
    target_path: Path,
    error_type: PersistenceErrorType,
) -> None:
    if target_path.is_symlink():
        raise error_type(
            f"refusing to replace symbolic link: {target_path}",
        )


def _prepare_directory(
    path: Path,
    error_type: PersistenceErrorType,
) -> None:
    if path.is_symlink():
        raise error_type(
            f"directory must not be a symbolic link: {path}",
        )

    try:
        path.mkdir(
            mode=DIRECTORY_MODE,
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        raise error_type(
            f"failed to create directory: {path}",
        ) from error

    if not path.is_dir():
        raise error_type(
            f"path is not a directory: {path}",
        )


def _safe_child_path(root: Path, relative_name: str) -> Path:
    normalized_name = _normalize_target_name(relative_name)
    candidate = root / normalized_name
    resolved_root = root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)

    if resolved_candidate.parent != resolved_root:
        raise OutputWriteError(
            f"target escapes output root: {relative_name}",
        )

    return candidate


def _normalize_target_name(value: str) -> str:
    normalized = value.strip()

    if not normalized:
        raise OutputWriteError("target_name must not be empty")

    pure_path = PurePosixPath(normalized.replace("\\", "/"))

    if pure_path.is_absolute():
        raise OutputWriteError("target_name must be relative")

    if len(pure_path.parts) != 1:
        raise OutputWriteError(
            "target_name must be a single filename",
        )

    if pure_path.name in {"", ".", ".."}:
        raise OutputWriteError("target_name is invalid")

    return pure_path.name


def _normalize_target_name_for_state(value: str) -> str:
    try:
        return _normalize_target_name(value)
    except OutputWriteError as error:
        raise StatePersistenceError(
            "persisted target_name is invalid",
        ) from error


def _normalize_state_file_name(value: str) -> str:
    try:
        normalized = _normalize_target_name(value)
    except OutputWriteError as error:
        raise StatePersistenceError(
            "state_file_name must be a single safe filename",
        ) from error

    if not normalized.endswith(".json"):
        raise StatePersistenceError(
            "state_file_name must use the .json suffix",
        )

    return normalized


def _normalize_root(value: Path, field_name: str) -> Path:
    if not isinstance(value, Path):
        raise TypeError(f"{field_name} must be a pathlib.Path")

    expanded = value.expanduser()

    if expanded.exists() and expanded.is_symlink():
        raise OutputWriteError(
            f"{field_name} must not be a symbolic link",
        )

    return expanded.resolve(strict=False)


def _project_directory_name(project_name: str) -> str:
    normalized = project_name.strip()

    if not normalized:
        raise OutputWriteError("project_name must not be empty")

    if normalized in {".", ".."}:
        raise OutputWriteError("project_name is invalid")

    if any(character in normalized for character in ("/", "\\", "\x00")):
        raise OutputWriteError(
            "project_name must not contain path separators",
        )

    return normalized


def _normalize_project_name_for_state(project_name: str) -> str:
    try:
        return _project_directory_name(project_name)
    except OutputWriteError as error:
        raise StatePersistenceError(
            "state project_name is invalid",
        ) from error


def _normalize_signature(
    signature: Sequence[str],
    error_type: PersistenceErrorType,
) -> tuple[str, ...]:
    normalized = tuple(item.strip() for item in signature)

    if any(not item for item in normalized):
        raise error_type(
            "source_signature entries must not be empty",
        )

    return normalized


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as source_file:
        for chunk in iter(
            lambda: source_file.read(HASH_CHUNK_SIZE),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _normalize_hash(value: str) -> str:
    normalized = value.strip().lower()

    if len(normalized) != SHA256_HEX_LENGTH:
        raise StatePersistenceError(
            "content_hash must be a SHA-256 hexadecimal digest",
        )

    if any(character not in "0123456789abcdef" for character in normalized):
        raise StatePersistenceError(
            "content_hash must contain hexadecimal characters",
        )

    return normalized


def _order_persisted_outputs(
    outputs: Sequence[PersistedOutput],
) -> tuple[PersistedOutput, ...]:
    return tuple(
        sorted(
            outputs,
            key=lambda output: (
                output.target_name.casefold(),
                output.target_name,
            ),
        )
    )


def _reject_duplicate_persisted_outputs(
    outputs: Sequence[PersistedOutput],
) -> None:
    canonical_names = tuple(output.target_name.casefold() for output in outputs)

    if len(canonical_names) != len(set(canonical_names)):
        raise StatePersistenceError(
            "output state contains duplicate target names",
        )


def _encode_state(state: OutputState) -> str:
    payload = {
        "schema_version": state.schema_version,
        "project_name": state.project_name,
        "outputs": [_encode_persisted_output(output) for output in state.outputs],
    }

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=JSON_INDENT,
            sort_keys=True,
        )
        + "\n"
    )


def _encode_persisted_output(
    output: PersistedOutput,
) -> dict[str, object]:
    return {
        "target_name": output.target_name,
        "content_hash": output.content_hash,
        "size_bytes": output.size_bytes,
        "source_signature": list(output.source_signature),
    }


def _read_json_state(state_path: Path) -> object:
    try:
        raw_text = state_path.read_text(encoding=UTF8)
        return json.loads(raw_text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StatePersistenceError(
            f"failed to read output state: {state_path}",
        ) from error


def _validate_existing_state_path(state_path: Path) -> None:
    if state_path.is_symlink():
        raise StatePersistenceError(
            f"state file must not be a symbolic link: {state_path}",
        )

    if not state_path.is_file():
        raise StatePersistenceError(
            f"state path is not a regular file: {state_path}",
        )


def _decode_state(
    raw_state: object,
    *,
    expected_project_name: str,
) -> OutputState:
    state_mapping = _require_mapping(
        raw_state,
        "output state root must be an object",
    )
    schema_version = _require_int(
        state_mapping.get("schema_version"),
        "output state schema_version must be an integer",
    )
    project_name = _require_string(
        state_mapping.get("project_name"),
        "output state project_name must be a string",
    )
    raw_outputs = _require_list(
        state_mapping.get("outputs"),
        "output state outputs must be a list",
    )

    if project_name != expected_project_name:
        raise StatePersistenceError(
            "output state project does not match requested project",
        )

    return OutputState(
        schema_version=schema_version,
        project_name=project_name,
        outputs=tuple(_decode_persisted_output(item) for item in raw_outputs),
    )


def _decode_persisted_output(raw_output: object) -> PersistedOutput:
    output_mapping = _require_mapping(
        raw_output,
        "persisted output entry must be an object",
    )
    target_name = _require_string(
        output_mapping.get("target_name"),
        "persisted target_name must be a string",
    )
    content_hash = _require_string(
        output_mapping.get("content_hash"),
        "persisted content_hash must be a string",
    )
    size_bytes = _require_int(
        output_mapping.get("size_bytes"),
        "persisted size_bytes must be an integer",
    )
    source_signature = _decode_signature(
        output_mapping.get("source_signature"),
    )

    return PersistedOutput(
        target_name=target_name,
        content_hash=content_hash,
        size_bytes=size_bytes,
        source_signature=source_signature,
    )


def _decode_signature(raw_signature: object) -> tuple[str, ...]:
    signature_items = _require_list(
        raw_signature,
        "persisted source_signature must be a list",
    )

    if not all(isinstance(item, str) for item in signature_items):
        raise StatePersistenceError(
            "persisted source_signature must contain strings",
        )

    return tuple(cast(list[str], signature_items))


def _require_mapping(
    value: object,
    message: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StatePersistenceError(message)

    return value


def _require_list(
    value: object,
    message: str,
) -> list[object]:
    if not isinstance(value, list):
        raise StatePersistenceError(message)

    return value


def _require_string(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise StatePersistenceError(message)

    return value


def _require_int(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StatePersistenceError(message)

    return value


def _sync_directory(path: Path) -> None:
    directory_flags = os.O_RDONLY

    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY

    try:
        directory_descriptor = os.open(path, directory_flags)
    except OSError:
        return

    try:
        os.fsync(directory_descriptor)
    except OSError:
        return
    finally:
        os.close(directory_descriptor)

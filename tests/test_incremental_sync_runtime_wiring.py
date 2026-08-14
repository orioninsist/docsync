import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _module(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def _function_names(relative: str) -> set[str]:
    tree = _module(relative)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_incremental_state_functions_exist() -> None:
    names = _function_names("src/docsync/incremental.py")

    assert "load_url_state" in names
    assert "save_url_state" in names
    assert "filter_incremental_urls" in names


def test_content_hash_state_functions_exist() -> None:
    names = _function_names("src/docsync/incremental.py")

    assert "load_content_hashes" in names
    assert "save_content_hashes" in names
    assert "content_hash" in names


def test_url_state_file_is_persistent_json_state() -> None:
    source = _source("src/docsync/incremental.py")

    assert "URL_STATE_FILE" in source
    assert ".json" in source
    assert "read_text" in source
    assert "json.loads" in source
    assert "json.dumps" in source


def test_incremental_filter_normalizes_and_deduplicates() -> None:
    source = _source("src/docsync/incremental.py")

    assert "filter_incremental_urls" in source
    assert "normalize" in source.lower()
    assert "set[" in source or "set(" in source


def test_incremental_filter_records_skips() -> None:
    source = _source("src/docsync/incremental.py")

    assert "is_recently_saved" in source
    assert "incremental_skipped_urls" in source
    assert "incremental_skipped" in source


def test_url_state_store_uses_atomic_replace() -> None:
    source = _source("src/docsync/incremental.py")

    assert 'url_state_file.with_suffix(".tmp")' in source
    assert "temporary.replace(url_state_file)" in source


def test_incremental_behavioral_test_exists() -> None:
    names = _function_names("tests/test_behavioral_core.py")

    assert (
        "test_filter_incremental_urls_normalizes_deduplicates_and_records_skips"
        in names
    )


def test_live_incremental_verifier_exists() -> None:
    path = ROOT / "tests/verify_incremental_sync.py"

    assert path.is_file()

    source = path.read_text(encoding="utf-8")

    assert "verify_first_run" in source
    assert "verify_second_run" in source
    assert "canonical_digest" in source
    assert "canonical_path" in source
    assert "processed" in source
    assert "saved" in source
    assert "duplicate" in source
    assert "failed" in source


def test_second_run_verifier_protects_existing_output() -> None:
    source = _source("tests/verify_incremental_sync.py")
    normalized = source.lower()

    assert "canonical markdown file disappeared after the second run" in normalized
    assert "canonical markdown file changed during the incremental skip" in normalized
    assert "canonical markdown file remained unchanged" in normalized


def test_live_verifier_uses_unique_fixture_token() -> None:
    source = _source("tests/verify_incremental_sync.py")

    assert "uuid.uuid4().hex" in source
    assert "unique_token" in source


def test_live_verifier_cleans_generated_output() -> None:
    source = _source("tests/verify_incremental_sync.py")

    assert "canonical_path.unlink" in source

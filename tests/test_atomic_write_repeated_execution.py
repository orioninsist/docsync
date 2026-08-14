from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import docsync.incremental as incremental
from docsync.markdown import MarkdownExporter


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_content_hash_state_repeated_atomic_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "content_hashes.json"
    target.parent.mkdir(parents=True)
    temporary = target.with_suffix(".tmp")

    monkeypatch.setattr(incremental, "CONTENT_HASH_FILE", target)

    first = {
        "first-hash": "https://example.com/first",
        "shared-hash": "https://example.com/original",
    }
    second = {
        "second-hash": "https://example.com/second",
        "shared-hash": "https://example.com/replacement",
    }

    incremental.save_content_hashes(first)

    assert target.is_file()
    assert not temporary.exists()
    assert _read_json(target) == first

    incremental.save_content_hashes(second)

    assert target.is_file()
    assert not temporary.exists()
    assert _read_json(target) == second


def test_url_state_repeated_atomic_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "url_state.json"
    target.parent.mkdir(parents=True)
    temporary = target.with_suffix(".tmp")

    monkeypatch.setattr(incremental, "URL_STATE_FILE", target)

    first = {
        "https://example.com/first": {
            "content_hash": "first-hash",
            "saved_at": "2026-07-31T10:00:00+00:00",
        }
    }
    second = {
        "https://example.com/second": {
            "content_hash": "second-hash",
            "saved_at": "2026-07-31T11:00:00+00:00",
        }
    }

    incremental.save_url_state(first)

    assert target.is_file()
    assert not temporary.exists()
    assert _read_json(target) == first

    incremental.save_url_state(second)

    assert target.is_file()
    assert not temporary.exists()
    assert _read_json(target) == second


def test_content_hash_replace_failure_preserves_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "content_hashes.json"
    monkeypatch.setattr(incremental, "CONTENT_HASH_FILE", target)

    original = {"stable-hash": "https://example.com/stable"}
    replacement = {"new-hash": "https://example.com/new"}

    incremental.save_content_hashes(original)

    original_replace = Path.replace

    def failing_replace(
        temporary_path: Path,
        destination: Path,
    ) -> Path:
        if destination == target:
            raise OSError("simulated atomic replace failure")

        return original_replace(temporary_path, destination)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(
        OSError,
        match="simulated atomic replace failure",
    ):
        incremental.save_content_hashes(replacement)

    assert json.loads(target.read_text(encoding="utf-8")) == original

    remaining_files = list(tmp_path.iterdir())

    assert remaining_files == [target]


def test_url_state_replace_failure_preserves_existing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "state" / "url_state.json"
    target.parent.mkdir(parents=True)
    temporary = target.with_suffix(".tmp")

    monkeypatch.setattr(incremental, "URL_STATE_FILE", target)

    original = {
        "https://example.com/stable": {
            "content_hash": "stable-hash",
            "saved_at": "2026-07-31T10:00:00+00:00",
        }
    }
    replacement = {
        "https://example.com/new": {
            "content_hash": "new-hash",
            "saved_at": "2026-07-31T11:00:00+00:00",
        }
    }

    incremental.save_url_state(original)
    original_bytes = target.read_bytes()
    original_replace = Path.replace

    def failing_replace(self: Path, destination: Path) -> Path:
        if self == temporary and destination == target:
            raise OSError("simulated atomic replacement failure")
        return original_replace(self, destination)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(
        OSError,
        match="simulated atomic replacement failure",
    ):
        incremental.save_url_state(replacement)

    assert target.read_bytes() == original_bytes
    assert temporary.is_file()
    assert _read_json(temporary) == replacement


def test_markdown_atomic_write_replaces_existing_file_repeatedly(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "document.md"
    temporary = output_path.with_suffix(".md.tmp")

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="first",
    )

    assert output_path.read_text(encoding="utf-8") == "first"
    assert not temporary.exists()

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="second",
    )

    assert output_path.read_text(encoding="utf-8") == "second"
    assert not temporary.exists()

    MarkdownExporter._atomic_write(
        output_path=output_path,
        content="third",
    )

    assert output_path.read_text(encoding="utf-8") == "third"
    assert not temporary.exists()


def test_atomic_state_writes_leave_no_temporary_files_after_many_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content_hash_target = tmp_path / "state" / "content_hashes.json"
    url_state_target = tmp_path / "state" / "url_state.json"
    content_hash_target.parent.mkdir(parents=True)

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        content_hash_target,
    )
    monkeypatch.setattr(
        incremental,
        "URL_STATE_FILE",
        url_state_target,
    )

    for index in range(25):
        incremental.save_content_hashes(
            {
                f"hash-{index}": f"https://example.com/content/{index}",
            }
        )
        incremental.save_url_state(
            {
                f"https://example.com/page/{index}": {
                    "content_hash": f"hash-{index}",
                    "saved_at": f"2026-07-31T12:{index:02d}:00+00:00",
                }
            }
        )

        assert not content_hash_target.with_suffix(".tmp").exists()
        assert not url_state_target.with_suffix(".tmp").exists()

    assert _read_json(content_hash_target) == {
        "hash-24": "https://example.com/content/24",
    }
    assert _read_json(url_state_target) == {
        "https://example.com/page/24": {
            "content_hash": "hash-24",
            "saved_at": "2026-07-31T12:24:00+00:00",
        }
    }


def test_concurrent_content_hash_writes_remain_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    target = tmp_path / "content_hashes.json"
    monkeypatch.setattr(incremental, "CONTENT_HASH_FILE", target)

    workers = 8
    writes_per_worker = 16
    barrier = Barrier(workers)

    payloads = [
        {f"hash-{worker}-{index}": (f"https://example.com/concurrent/{worker}/{index}")}
        for worker in range(workers)
        for index in range(writes_per_worker)
    ]

    def write_payload(worker: int) -> None:
        barrier.wait()

        start = worker * writes_per_worker
        stop = start + writes_per_worker

        for payload in payloads[start:stop]:
            incremental.save_content_hashes(payload)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(write_payload, worker) for worker in range(workers)]

        for future in futures:
            future.result()

    stored = json.loads(target.read_text(encoding="utf-8"))

    assert stored in payloads
    assert list(tmp_path.iterdir()) == [target]


def test_concurrent_content_hash_reads_never_observe_partial_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock

    target = tmp_path / "content_hashes.json"
    monkeypatch.setattr(incremental, "CONTENT_HASH_FILE", target)

    initial = {"initial-hash": "https://example.com/initial"}
    incremental.save_content_hashes(initial)

    writer_count = 6
    reader_count = 4
    writes_per_worker = 20
    reads_per_worker = 120
    barrier = Barrier(writer_count + reader_count)
    failures: list[BaseException] = []
    failures_lock = Lock()

    payloads = [
        {f"hash-{worker}-{index}": (f"https://example.com/read-write/{worker}/{index}")}
        for worker in range(writer_count)
        for index in range(writes_per_worker)
    ]

    valid_payloads = [initial, *payloads]

    def record_failure(error: BaseException) -> None:
        with failures_lock:
            failures.append(error)

    def write_payloads(worker: int) -> None:
        try:
            barrier.wait()

            start = worker * writes_per_worker
            stop = start + writes_per_worker

            for payload in payloads[start:stop]:
                incremental.save_content_hashes(payload)
        except BaseException as error:
            record_failure(error)
            raise

    def read_payloads() -> None:
        try:
            barrier.wait()

            for _ in range(reads_per_worker):
                observed = json.loads(target.read_text(encoding="utf-8"))

                if observed not in valid_payloads:
                    raise AssertionError(f"Observed unexpected payload: {observed!r}")
        except BaseException as error:
            record_failure(error)
            raise

    with ThreadPoolExecutor(max_workers=writer_count + reader_count) as executor:
        futures = [
            executor.submit(write_payloads, worker) for worker in range(writer_count)
        ]
        futures.extend(executor.submit(read_payloads) for _ in range(reader_count))

        for future in futures:
            future.result()

    assert failures == []

    stored = json.loads(target.read_text(encoding="utf-8"))

    assert stored in payloads
    assert list(tmp_path.iterdir()) == [target]

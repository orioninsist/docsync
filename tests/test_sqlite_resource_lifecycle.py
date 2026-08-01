from __future__ import annotations

import gc
import warnings
from pathlib import Path

from docsync.duplicates import DuplicateRegistry


def test_duplicate_registry_emits_no_resource_warning(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "resource-lifecycle.sqlite3"

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", ResourceWarning)

        registry = DuplicateRegistry(database_path)

        with registry._connect() as connection:
            result = connection.execute("SELECT 1").fetchone()

        assert result == (1,)

        del registry
        gc.collect()

    resource_warnings = [
        warning for warning in captured if issubclass(warning.category, ResourceWarning)
    ]

    assert resource_warnings == []

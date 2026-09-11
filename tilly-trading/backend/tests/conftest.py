"""Pytest configuration — isolate tests on a throwaway SQLite database.

The env var is set before any `app.*` import so the engine binds to the temp
DB instead of the developer's real `tilly.db`.
"""
from __future__ import annotations

import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp.name}"
os.environ["DATABASE_URL_SYNC"] = f"sqlite:///{_tmp.name}"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    try:
        os.unlink(_tmp.name)
    except OSError:
        pass

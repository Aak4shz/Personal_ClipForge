"""SQLite connection management with WAL, foreign keys, and synchronous NORMAL.

Every connection is configured the same way so reads and writes across the
process agree on isolation and durability (RULE-22).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with the project's mandatory pragmas.

    - WAL journal mode: readers don't block writers, writers don't block readers
    - foreign_keys=ON: referential integrity enforced by the database
    - synchronous=NORMAL: durable enough for WAL, not fsync-per-commit slow
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


@contextmanager
def connect(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Context-managed SQLite connection that always closes and commits.

    Usage::

        with connect(db_path) as conn:
            conn.execute("INSERT ...")

    Commits on success, rolls back on exception. The underlying DBAPI
    isolation_level=None means autocommit; we manage explicit BEGIN/COMMIT.
    """
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[None, None, None]:
    """Nested-style transaction block on an already-open connection.

    Commits on success, rolls back on exception. Safe to use inside `connect`.
    """
    try:
        conn.execute("BEGIN")
        yield
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

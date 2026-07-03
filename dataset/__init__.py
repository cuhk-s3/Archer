"""Archer dataset package: the SQLite-backed store is the single source of
truth for PR data, per-commit versions, review runs and the bugs they find.

The database file (``archer.db``) lives inside this package directory, and the
extraction scripts live under ``dataset/scripts/``.
"""

from .store import ArcherStore, default_db_path, get_store

__all__ = ["ArcherStore", "get_store", "default_db_path"]

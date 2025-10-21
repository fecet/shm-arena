"""LMDB-based IPC backend implementation."""

import logging
import tempfile
from pathlib import Path
from typing import Any

import lmdb

from .base import IPCBackend
from .utils import deserialize, serialize


class _RankFilter(logging.Filter):
    """Ensure rank field exists in log records."""

    def filter(self, record):
        if not hasattr(record, "rank"):
            record.rank = -1
        return True


logger = logging.getLogger(__name__)
logger.addFilter(_RankFilter())


class LMDBBackend(IPCBackend):
    """IPC backend using LMDB memory-mapped database."""

    def __init__(self, db_path: str | None = None):
        self._env: lmdb.Environment | None = None
        self._name: str = ""
        self._is_writer: bool = False
        self._db_path: Path | None = None
        self._custom_path = db_path

    def initialize(self, name: str, is_writer: bool) -> None:
        self._name = name
        self._is_writer = is_writer

        # Use custom path or temp directory
        if self._custom_path:
            self._db_path = Path(self._custom_path)
        else:
            temp_dir = Path(tempfile.gettempdir())
            self._db_path = temp_dir / f"lmdb_bench_{name}"

        self._db_path.mkdir(parents=True, exist_ok=True)

        # Map size: 1GB
        map_size = 1024 * 1024 * 1024
        self._env = lmdb.open(
            str(self._db_path),
            map_size=map_size,
            max_dbs=1,
            writemap=True,
            sync=False,  # async write for better performance
        )

        logger.info("LMDB initialized at %s (writer=%s)", self._db_path, is_writer)

    def write(self, data: dict[str, Any]) -> None:
        if not self._env:
            raise RuntimeError("Backend not initialized")

        serialized = serialize(data)
        with self._env.begin(write=True) as txn:
            txn.put(b"data", serialized)

    def read(self) -> dict[str, Any] | None:
        if not self._env:
            raise RuntimeError("Backend not initialized")

        with self._env.begin() as txn:
            serialized = txn.get(b"data")
            if serialized is None:
                return None
            return deserialize(serialized)

    def cleanup(self) -> None:
        if self._env:
            self._env.close()
            self._env = None

        # Clean up database files if writer
        if self._is_writer and self._db_path and self._db_path.exists():
            import shutil

            shutil.rmtree(self._db_path)
            logger.info("LMDB cleaned up: %s", self._db_path)

    def get_name(self) -> str:
        return "LMDB"

    def supports_streaming(self) -> bool:
        """LMDB uses shared storage model, not optimized for streaming."""
        return False

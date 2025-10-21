"""Shared memory-based IPC backend implementation."""

import logging
import struct
from multiprocessing import shared_memory
from typing import Any

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


class SharedMemoryBackend(IPCBackend):
    """IPC backend using Python's multiprocessing.shared_memory."""

    # Header format: 4 bytes for data size + 4 bytes for version counter
    HEADER_SIZE = 8
    HEADER_FORMAT = "II"  # unsigned int, unsigned int
    DEFAULT_SIZE = 100 * 1024 * 1024  # 100MB

    def __init__(self, size: int = DEFAULT_SIZE):
        self._shm: shared_memory.SharedMemory | None = None
        self._name: str = ""
        self._is_writer: bool = False
        self._size = size

    def initialize(self, name: str, is_writer: bool) -> None:
        self._name = name
        self._is_writer = is_writer

        try:
            if is_writer:
                # Create new shared memory block
                self._shm = shared_memory.SharedMemory(
                    name=name, create=True, size=self._size
                )
                # Initialize header: data_size=0, version=0
                self._write_header(0, 0)
                logger.info("SharedMemory created: %s (%d bytes)", name, self._size)
            else:
                # Attach to existing shared memory
                self._shm = shared_memory.SharedMemory(name=name)
                logger.info("SharedMemory attached: %s", name)
        except FileExistsError:
            # If writer finds existing shm, try to attach instead
            if is_writer:
                logger.warning("SharedMemory already exists, attaching: %s", name)
                self._shm = shared_memory.SharedMemory(name=name)

    def _write_header(self, data_size: int, version: int) -> None:
        """Write header to shared memory."""
        if not self._shm:
            raise RuntimeError("Backend not initialized")
        header = struct.pack(self.HEADER_FORMAT, data_size, version)
        self._shm.buf[: self.HEADER_SIZE] = header

    def _read_header(self) -> tuple[int, int]:
        """Read header from shared memory.

        Returns:
            Tuple of (data_size, version)
        """
        if not self._shm:
            raise RuntimeError("Backend not initialized")
        header = bytes(self._shm.buf[: self.HEADER_SIZE])
        return struct.unpack(self.HEADER_FORMAT, header)

    def write(self, data: dict[str, Any]) -> None:
        if not self._shm:
            raise RuntimeError("Backend not initialized")

        serialized = serialize(data)
        data_size = len(serialized)

        if data_size + self.HEADER_SIZE > self._size:
            raise ValueError(
                f"Data too large: {data_size} bytes (max: {self._size - self.HEADER_SIZE})"
            )

        # Read current version
        _, current_version = self._read_header()

        # Write data
        self._shm.buf[
            self.HEADER_SIZE : self.HEADER_SIZE + data_size
        ] = serialized

        # Update header with new size and incremented version
        self._write_header(data_size, current_version + 1)

    def read(self) -> dict[str, Any] | None:
        if not self._shm:
            raise RuntimeError("Backend not initialized")

        data_size, version = self._read_header()

        if data_size == 0:
            return None

        # Read data
        serialized = bytes(
            self._shm.buf[self.HEADER_SIZE : self.HEADER_SIZE + data_size]
        )
        return deserialize(serialized)

    def cleanup(self) -> None:
        if self._shm:
            self._shm.close()

            # Only unlink if writer
            if self._is_writer:
                try:
                    self._shm.unlink()
                    logger.info("SharedMemory unlinked: %s", self._name)
                except FileNotFoundError:
                    pass

            self._shm = None

    def get_name(self) -> str:
        return "SharedMemory"

    def supports_streaming(self) -> bool:
        """SharedMemory uses shared storage model, not optimized for streaming."""
        return False

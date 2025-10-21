"""MPI native communication-based IPC backend implementation."""

import logging
from typing import Any

from mpi4py import MPI

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


class MPIBackend(IPCBackend):
    """IPC backend using MPI's native communication primitives (bcast).

    This backend uses MPI's collective communication (broadcast) to distribute
    data from writer (rank 0) to all readers. Unlike shared storage backends,
    MPI handles data transfer through the MPI runtime's optimized communication
    layer.

    Communication pattern:
    - Writer serializes data and broadcasts bytes using comm.bcast()
    - Readers participate in bcast to receive bytes and deserialize
    - Each read() triggers a new broadcast operation
    - Uses same serialize/deserialize as other backends for fair comparison
    """

    def __init__(self):
        self._comm: MPI.Comm | None = None
        self._name: str = ""
        self._is_writer: bool = False
        self._serialized_data: bytes | None = None

    def initialize(self, name: str, is_writer: bool) -> None:
        self._name = name
        self._is_writer = is_writer
        self._comm = MPI.COMM_WORLD

        logger.info(
            "MPI backend initialized (rank=%d, writer=%s)",
            self._comm.Get_rank(),
            is_writer,
        )

    def write(self, data: dict[str, Any]) -> None:
        """Serialize and store data for later broadcast.

        Unlike other backends, MPI broadcast is a collective operation.
        This method serializes the data; actual broadcast happens in read().
        """
        if not self._comm:
            raise RuntimeError("Backend not initialized")

        if not self._is_writer:
            raise RuntimeError("Only writer can call write()")

        # Serialize data using same method as other backends
        self._serialized_data = serialize(data)

    def read(self) -> dict[str, Any] | None:
        """Broadcast serialized bytes and deserialize.

        For MPI backend, both writer and readers participate in broadcast.
        Each read() call triggers a new broadcast operation.
        - Writer broadcasts serialized bytes
        - Readers receive bytes and deserialize
        """
        if not self._comm:
            raise RuntimeError("Backend not initialized")

        # Collective broadcast: all ranks participate
        if self._is_writer:
            # Writer broadcasts the serialized data
            _ = self._comm.bcast(self._serialized_data, root=0)
            # Writer returns None (doesn't read its own data)
            return None
        else:
            # Readers receive the broadcast bytes
            serialized = self._comm.bcast(None, root=0)
            if serialized is None:
                return None
            # Deserialize using same method as other backends
            return deserialize(serialized)

    def write_bytes(self, data: bytes) -> None:
        """Broadcast pre-serialized bytes immediately (writer side).

        For MPI backend, this immediately performs a broadcast operation.
        All readers must call read_bytes() to participate in the same broadcast.
        Also stores data for potential future broadcasts (shared scenario).

        Args:
            data: Pre-serialized bytes to transmit
        """
        if not self._comm:
            raise RuntimeError("Backend not initialized")

        if not self._is_writer:
            raise RuntimeError("Only writer can call write_bytes()")

        # Store data for future broadcasts (shared scenario)
        self._serialized_data = data

        # Immediately broadcast (collective operation - writer side)
        self._comm.bcast(data, root=0)

    def read_bytes(self) -> bytes | None:
        """Receive broadcast bytes (reader side) OR participate in broadcast (writer side).

        For MPI backend, this participates in a broadcast operation.
        - Writer: sends the last written data via bcast
        - Reader: receives data via bcast

        Returns:
            Raw bytes from broadcast, or None for writer
        """
        if not self._comm:
            raise RuntimeError("Backend not initialized")

        if self._is_writer:
            # Writer participates in broadcast (sends previously stored data)
            # This is used in shared scenario where same data is broadcast multiple times
            self._comm.bcast(self._serialized_data, root=0)
            return None
        else:
            # Reader participates in broadcast (receives data)
            return self._comm.bcast(None, root=0)

    def cleanup(self) -> None:
        """Clean up resources.

        MPI communicator is managed by MPI runtime, so we just clear references.
        """
        self._comm = None
        self._serialized_data = None
        logger.info("MPI backend cleaned up")

    def get_name(self) -> str:
        return "MPI-Native"

    def supports_streaming(self) -> bool:
        return True

    def prepare_stream(self, num_messages: int) -> None:
        """Prepare for streaming transmission."""
        logger.info(
            "MPI prepared for streaming %d messages (collective ops)", num_messages
        )

"""Optimized MPI backend using pickle protocol 5 for better performance."""

import logging
import pickle
from typing import Any

from mpi4py import MPI
from mpi4py.util.pkl5 import Intracomm

from .base import IPCBackend
from .utils import deserialize


class _RankFilter(logging.Filter):
    """Ensure rank field exists in log records."""

    def filter(self, record):
        if not hasattr(record, "rank"):
            record.rank = -1
        return True


logger = logging.getLogger(__name__)
logger.addFilter(_RankFilter())


class MPIPkl5Backend(IPCBackend):
    """Optimized MPI backend using pickle protocol 5 with out-of-band buffers.

    This backend uses mpi4py.util.pkl5 which implements pickle protocol 5,
    enabling out-of-band buffer handling for large data transfers. This can
    significantly reduce serialization overhead compared to standard pickle.

    Communication pattern:
    - Writer serializes data using pickle protocol 5 and broadcasts bytes
    - Readers participate in bcast to receive bytes and deserialize
    - Each read() triggers a new broadcast operation
    - Uses pickle protocol 5 for serialization (other backends use HIGHEST_PROTOCOL)
    """

    def __init__(self):
        self._comm: Intracomm | None = None
        self._name: str = ""
        self._is_writer: bool = False
        self._serialized_data: bytes | None = None

    def initialize(self, name: str, is_writer: bool) -> None:
        self._name = name
        self._is_writer = is_writer
        # Wrap COMM_WORLD with pkl5 communicator for optimized pickling
        self._comm = Intracomm(MPI.COMM_WORLD)

        logger.info(
            "MPI-Pkl5 backend initialized (rank=%d, writer=%s)",
            self._comm.Get_rank(),
            is_writer,
        )

    def write(self, data: dict[str, Any]) -> None:
        """Serialize data using pickle protocol 5 and store for later broadcast.

        Unlike other backends, MPI broadcast is a collective operation.
        This method serializes the data; actual broadcast happens in read().
        """
        if not self._comm:
            raise RuntimeError("Backend not initialized")

        if not self._is_writer:
            raise RuntimeError("Only writer can call write()")

        # Serialize using pickle protocol 5 (vs HIGHEST_PROTOCOL in other backends)
        self._serialized_data = pickle.dumps(data, protocol=5)

    def read(self) -> dict[str, Any] | None:
        """Broadcast serialized bytes and deserialize.

        For MPI backend, both writer and readers participate in broadcast.
        Each read() call triggers a new broadcast operation.
        - Writer broadcasts serialized bytes (protocol 5)
        - Readers receive bytes and deserialize (standard pickle.loads)
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
            # Deserialize using standard method (same as other backends)
            return deserialize(serialized)

    def cleanup(self) -> None:
        """Clean up resources.

        MPI communicator is managed by MPI runtime, so we just clear references.
        """
        self._comm = None
        self._serialized_data = None
        logger.info("MPI-Pkl5 backend cleaned up")

    def get_name(self) -> str:
        return "MPI-Pkl5"

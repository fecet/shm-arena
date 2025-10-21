"""Abstract base class for IPC backends."""

from abc import ABC, abstractmethod
from typing import Any


class IPCBackend(ABC):
    """Abstract interface for IPC backend implementations."""

    @abstractmethod
    def initialize(self, name: str, is_writer: bool) -> None:
        """Initialize backend resources.

        Args:
            name: Unique identifier for the shared resource
            is_writer: Whether this process will write data
        """
        pass

    @abstractmethod
    def write(self, data: dict[str, Any]) -> None:
        """Write dictionary to shared storage.

        Args:
            data: Dictionary to share with other processes
        """
        pass

    @abstractmethod
    def read(self) -> dict[str, Any] | None:
        """Read dictionary from shared storage.

        Returns:
            Dictionary from shared storage, or None if unavailable
        """
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Release all resources and clean up."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get the backend implementation name."""
        pass

    def supports_streaming(self) -> bool:
        """Whether backend natively supports streaming mode.

        Returns:
            True if backend is optimized for message-passing (ZeroMQ, MPI).
            False for shared storage backends (LMDB, SharedMemory).
        """
        return False

    def prepare_stream(self, num_messages: int) -> None:
        """Prepare for streaming transmission (optional optimization hook).

        Args:
            num_messages: Expected number of messages in stream
        """
        pass

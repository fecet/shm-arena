"""ZeroMQ-based IPC backend implementation."""

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

import zmq

from .base import IPCBackend
from .utils import deserialize, serialize

logger = logging.getLogger(__name__)


class ZMQBackend(IPCBackend):
    """IPC backend using ZeroMQ with IPC transport."""

    def __init__(self):
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._name: str = ""
        self._is_writer: bool = False
        self._ipc_path: str = ""

    def initialize(self, name: str, is_writer: bool) -> None:
        self._name = name
        self._is_writer = is_writer

        # Create IPC socket path
        temp_dir = Path(tempfile.gettempdir())
        self._ipc_path = f"ipc://{temp_dir}/zmq_bench_{name}.ipc"

        self._context = zmq.Context()

        if is_writer:
            # Writer uses PUSH socket
            self._socket = self._context.socket(zmq.PUSH)
            self._socket.bind(self._ipc_path)
            logger.info("ZMQ writer bound to %s", self._ipc_path)
            # Give readers time to connect
            time.sleep(0.1)
        else:
            # Reader uses PULL socket
            self._socket = self._context.socket(zmq.PULL)
            self._socket.connect(self._ipc_path)
            # Set receive timeout to avoid blocking indefinitely
            self._socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1 second
            logger.info("ZMQ reader connected to %s", self._ipc_path)

    def write(self, data: dict[str, Any]) -> None:
        if not self._socket:
            raise RuntimeError("Backend not initialized")

        serialized = serialize(data)
        self._socket.send(serialized)

    def read(self) -> dict[str, Any] | None:
        if not self._socket:
            raise RuntimeError("Backend not initialized")

        try:
            serialized = self._socket.recv()
            return deserialize(serialized)
        except zmq.Again:
            # Timeout - no data available
            return None

    def cleanup(self) -> None:
        if self._socket:
            self._socket.close()
            self._socket = None

        if self._context:
            self._context.term()
            self._context = None

        # Clean up IPC file if writer
        if self._is_writer and self._ipc_path:
            # Extract path from ipc:// URL
            ipc_file = self._ipc_path.replace("ipc://", "")
            path = Path(ipc_file)
            if path.exists():
                path.unlink()
                logger.info("ZMQ IPC file removed: %s", path)

    def get_name(self) -> str:
        return "ZeroMQ"

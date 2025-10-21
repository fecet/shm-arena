"""MPI benchmark for comparing IPC backends in different scenarios."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from mpi4py import MPI

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ipc_benchmark import (
    LMDBBackend,
    MPIBackend,
    SharedMemoryBackend,
    ZMQBackend,
)
from ipc_benchmark.base import IPCBackend
from ipc_benchmark.utils import deserialize, generate_test_dict, serialize


class MPIRankFilter(logging.Filter):
    """Add MPI rank to all log records."""

    def __init__(self):
        super().__init__()
        self.rank = -1

    def filter(self, record):
        record.rank = self.rank
        return True


# Global filter instance
_rank_filter = MPIRankFilter()

logging.basicConfig(
    level=logging.INFO, format="[Rank %(rank)s] %(levelname)s: %(message)s"
)
logging.getLogger().addFilter(_rank_filter)


class BenchmarkResult:
    """Container for benchmark results."""

    def __init__(
        self, backend_name: str, data_size: int, rank: int, scenario: str
    ):
        self.backend_name = backend_name
        self.data_size = data_size
        self.rank = rank
        self.scenario = scenario
        self.write_time: float = 0.0
        self.read_time: float = 0.0
        self.read_count: int = 0
        self.serialize_time: float = 0.0
        self.deserialize_time: float = 0.0

    @property
    def avg_read_time(self) -> float:
        """Average read time per operation."""
        return self.read_time / self.read_count if self.read_count > 0 else 0.0

    @property
    def throughput(self) -> float:
        """Messages per second (for readers)."""
        return self.read_count / self.read_time if self.read_time > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "data_size": self.data_size,
            "rank": self.rank,
            "scenario": self.scenario,
            "write_time": self.write_time,
            "read_time": self.read_time,
            "read_count": self.read_count,
            "avg_read_time": self.avg_read_time,
            "throughput": self.throughput,
            "serialize_time": self.serialize_time,
            "deserialize_time": self.deserialize_time,
        }


def run_scenario_shared(
    backend: IPCBackend,
    data: dict[str, Any] | None,
    rank: int,
    size: int,
    iterations: int,
) -> BenchmarkResult:
    """Scenario 1: Shared storage - write once, read N times.

    This scenario tests concurrent reads from shared data:
    - Writer writes data once
    - Multiple readers each read the same data N times
    - Optimal for LMDB/SharedMemory (shared storage model)
    - Sub-optimal for ZeroMQ/MPI (message-passing requires re-send)

    Args:
        backend: IPC backend to test
        data: Test data (only writer has actual data)
        rank: MPI rank (0 = writer)
        size: Total MPI processes
        iterations: Number of read iterations per reader

    Returns:
        Benchmark results
    """
    logger = logging.LoggerAdapter(logging.getLogger(__name__), {"rank": rank})
    comm = MPI.COMM_WORLD
    result = BenchmarkResult(backend.get_name(), len(data or {}), rank, "shared")
    is_writer = rank == 0

    # First barrier: ensure all processes are ready
    comm.Barrier()

    if is_writer:
        # Serialize once (measure separately)
        logger.info("Serializing data...")
        ser_start = time.perf_counter()
        serialized_data = serialize(data)
        result.serialize_time = time.perf_counter() - ser_start
        logger.info("Serialization completed in %.6f seconds", result.serialize_time)

        # Write (pure transport)
        logger.info("Writing data once (shared storage scenario)...")
        start = time.perf_counter()
        # For MPI: just store data, don't broadcast yet (collective ops happen later)
        if backend.get_name() == "MPI-Native":
            backend._serialized_data = serialized_data  # Store for later broadcasts
        else:
            backend.write_bytes(serialized_data)
        result.write_time = time.perf_counter() - start

        logger.info("Write completed in %.4f seconds", result.write_time)

        # Second barrier: signal data is ready
        comm.Barrier()

        # For MPI backend: participate in collective ops
        if backend.get_name() == "MPI-Native":
            logger.info(
                "Participating in %d collective ops (MPI backend)...", iterations
            )
            coll_start = time.perf_counter()
            for _ in range(iterations):
                backend.read_bytes()  # Trigger bcast
            result.write_time += time.perf_counter() - coll_start
        # For ZeroMQ: send iterations * num_readers messages
        elif backend.get_name() == "ZeroMQ":
            num_readers = size - 1
            num_messages = iterations * num_readers
            logger.info(
                "Sending %d messages (%d readers × %d iterations)...",
                num_messages,
                num_readers,
                iterations,
            )
            coll_start = time.perf_counter()
            for _ in range(num_messages - 1):  # -1 because we already sent one
                backend.write_bytes(serialized_data)
            result.write_time += time.perf_counter() - coll_start

    else:
        # Readers: wait for data ready
        comm.Barrier()

        logger.info("Reading data %d times (shared storage scenario)...", iterations)
        # Read (pure transport)
        start = time.perf_counter()
        for _ in range(iterations):
            raw_bytes = backend.read_bytes()
            if raw_bytes is not None:
                result.read_count += 1
        result.read_time = time.perf_counter() - start

        # Deserialize once (measure separately)
        if result.read_count > 0:
            deser_start = time.perf_counter()
            _ = deserialize(raw_bytes)
            result.deserialize_time = time.perf_counter() - deser_start

        logger.info(
            "Read completed: %d/%d successful (%.4f seconds total, %.6f seconds avg)",
            result.read_count,
            iterations,
            result.read_time,
            result.avg_read_time,
        )

    # Final barrier: ensure all processes finish before cleanup
    comm.Barrier()

    return result


def run_scenario_streaming(
    backend: IPCBackend,
    data: dict[str, Any] | None,
    rank: int,
    size: int,
    iterations: int,
) -> BenchmarkResult:
    """Scenario 2: Streaming - continuous write/read N messages.

    This scenario tests message-passing throughput:
    - Writer continuously sends N messages
    - Each reader consumes N messages sequentially
    - Optimal for ZeroMQ/MPI (message-passing model)
    - Sub-optimal for LMDB/SharedMemory (repeated overwrites)

    Args:
        backend: IPC backend to test
        data: Test data (only writer has actual data)
        rank: MPI rank (0 = writer)
        size: Total MPI processes
        iterations: Number of messages to stream

    Returns:
        Benchmark results
    """
    logger = logging.LoggerAdapter(logging.getLogger(__name__), {"rank": rank})
    comm = MPI.COMM_WORLD
    result = BenchmarkResult(backend.get_name(), len(data or {}), rank, "streaming")
    is_writer = rank == 0

    # Prepare streaming
    num_readers = size - 1
    backend.prepare_stream(iterations * num_readers)

    # First barrier: ensure all processes ready
    comm.Barrier()

    if is_writer:
        # Serialize once (measure separately)
        logger.info("Serializing data...")
        ser_start = time.perf_counter()
        serialized_data = serialize(data)
        result.serialize_time = time.perf_counter() - ser_start
        logger.info("Serialization completed in %.6f seconds", result.serialize_time)

        logger.info("Streaming %d messages to %d readers...", iterations, num_readers)
        start = time.perf_counter()

        # For streaming backends: send iterations * num_readers messages
        # For shared storage: just write iterations times (overwrite)
        # For MPI: broadcast is 1-to-N, so only send iterations times (not * num_readers)
        if backend.supports_streaming():
            if backend.get_name() == "MPI-Native":
                # MPI broadcast sends to ALL readers at once
                num_messages = iterations
            else:
                # ZeroMQ distributes messages round-robin to readers
                num_messages = iterations * num_readers

            for i in range(num_messages):
                backend.write_bytes(serialized_data)
        else:
            for i in range(iterations):
                backend.write_bytes(serialized_data)

        result.write_time = time.perf_counter() - start
        logger.info("Streaming completed in %.4f seconds", result.write_time)

    else:
        logger.info("Consuming %d messages (streaming scenario)...", iterations)
        # Read (pure transport)
        start = time.perf_counter()
        raw_bytes = None

        # All backends read iterations times
        # - MPI: participate in iterations broadcasts
        # - ZeroMQ: receive iterations messages (distributed among readers)
        # - Shared storage: read iterations times (same data)
        for _ in range(iterations):
            raw_bytes = backend.read_bytes()
            if raw_bytes is not None:
                result.read_count += 1

        result.read_time = time.perf_counter() - start

        # Deserialize once (measure separately)
        if result.read_count > 0 and raw_bytes is not None:
            deser_start = time.perf_counter()
            _ = deserialize(raw_bytes)
            result.deserialize_time = time.perf_counter() - deser_start

        logger.info(
            "Consumed: %d/%d messages (%.4f seconds, %.1f msg/s)",
            result.read_count,
            iterations,
            result.read_time,
            result.throughput,
        )

    # Final barrier: ensure all processes finish
    comm.Barrier()

    return result


def run_benchmark(
    backend: IPCBackend,
    data_size: int,
    rank: int,
    size: int,
    iterations: int,
    scenarios: list[str],
) -> list[BenchmarkResult]:
    """Run benchmark for a single backend across specified scenarios.

    Args:
        backend: IPC backend to test
        data_size: Number of dictionary entries
        rank: MPI rank (0 = writer)
        size: Total MPI processes
        iterations: Number of iterations/messages
        scenarios: List of scenarios to run ('shared', 'streaming')

    Returns:
        List of benchmark results (one per scenario)
    """
    logger = logging.LoggerAdapter(logging.getLogger(__name__), {"rank": rank})
    comm = MPI.COMM_WORLD
    results = []
    is_writer = rank == 0

    # Initialize backend
    if is_writer:
        backend.initialize(f"bench_{data_size}", is_writer)
        test_data = generate_test_dict(data_size)
        logger.info("Generated test data (%d entries)", data_size)
        comm.Barrier()
    else:
        comm.Barrier()
        backend.initialize(f"bench_{data_size}", is_writer)
        test_data = None

    comm.Barrier()

    # Run scenarios
    for scenario in scenarios:
        if scenario == "shared":
            result = run_scenario_shared(backend, test_data, rank, size, iterations)
            results.append(result)
        elif scenario == "streaming":
            result = run_scenario_streaming(backend, test_data, rank, size, iterations)
            results.append(result)
        else:
            raise ValueError(f"Unknown scenario: {scenario}")

        comm.Barrier()

    # Cleanup
    backend.cleanup()

    return results


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="IPC Backend Benchmark with multiple scenarios"
    )
    parser.add_argument(
        "--scenario",
        choices=["shared", "streaming", "both"],
        default="both",
        help="Test scenario (default: both)",
    )
    parser.add_argument(
        "--backend",
        choices=["lmdb", "shm", "zmq", "mpi", "all"],
        default="all",
        help="Backend to test (default: all)",
    )
    parser.add_argument(
        "--data-size",
        type=int,
        default=10000,
        help="Number of dictionary entries (default: 10000)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of read iterations/messages (default: 100)",
    )
    return parser.parse_args()


def main():
    """Main benchmark runner."""
    args = parse_args()
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    # Set rank in logging filter
    _rank_filter.rank = rank

    if size < 2:
        if rank == 0:
            print("Error: Need at least 2 MPI processes (1 writer + 1+ readers)")
            print("Run with: mpiexec -n 4 python benchmark_mpi.py")
        return

    # Create backend map
    backend_map = {
        "lmdb": LMDBBackend(),
        "shm": SharedMemoryBackend(),
        "zmq": ZMQBackend(),
        "mpi": MPIBackend(),
    }

    # Select backends
    if args.backend == "all":
        backends = list(backend_map.values())
    else:
        backends = [backend_map[args.backend]]

    # Select scenarios
    if args.scenario == "both":
        scenarios = ["shared", "streaming"]
    else:
        scenarios = [args.scenario]

    if rank == 0:
        print(f"\n{'='*60}")
        print(f"IPC Benchmark Configuration")
        print(f"{'='*60}")
        print(f"Data size: {args.data_size} entries")
        print(f"Iterations: {args.iterations}")
        print(f"MPI processes: {size} (1 writer + {size-1} readers)")
        print(f"Scenarios: {', '.join(scenarios)}")
        print(f"Backends: {', '.join(b.get_name() for b in backends)}")
        print(f"{'='*60}\n")

    all_results: list[BenchmarkResult] = []

    for backend in backends:
        if rank == 0:
            print(f"\n{'='*60}")
            print(f"Testing: {backend.get_name()}")
            print(f"{'='*60}")

        comm.Barrier()
        results = run_benchmark(
            backend, args.data_size, rank, size, args.iterations, scenarios
        )
        all_results.extend(results)
        comm.Barrier()

    # Gather all results to rank 0
    all_results_gathered = comm.gather(all_results, root=0)

    if rank == 0:
        # Flatten results
        results_flat = [r for results in all_results_gathered for r in results]

        # Save to JSON
        output_file = Path("benchmark_results.json")
        with output_file.open("w") as f:
            json.dump([r.to_dict() for r in results_flat], f, indent=2)

        print(f"\n{'='*60}")
        print(f"Results saved to {output_file}")
        print(f"{'='*60}")

        # Print summary grouped by scenario
        for scenario in scenarios:
            print(f"\n{'='*60}")
            print(f"Scenario: {scenario.upper()}")
            print(f"{'='*60}")

            scenario_results = [r for r in results_flat if r.scenario == scenario]

            for backend_name in set(r.backend_name for r in scenario_results):
                backend_results = [
                    r for r in scenario_results if r.backend_name == backend_name
                ]

                # Writer results
                writer = [r for r in backend_results if r.rank == 0]
                # Reader results
                readers = [r for r in backend_results if r.rank != 0]

                if writer:
                    w = writer[0]
                    print(f"\n{backend_name}:")
                    print(f"  Write time: {w.write_time*1000:.2f} ms")

                if readers:
                    avg_read = sum(r.avg_read_time for r in readers) / len(readers)
                    avg_throughput = sum(r.throughput for r in readers) / len(readers)
                    total_reads = sum(r.read_count for r in readers)

                    print(f"  Avg read time: {avg_read*1000:.2f} ms")
                    print(f"  Total reads: {total_reads}")
                    if scenario == "streaming":
                        print(f"  Avg throughput: {avg_throughput:.1f} msg/s")


if __name__ == "__main__":
    main()

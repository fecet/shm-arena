"""MPI benchmark for comparing IPC backends."""
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from mpi4py import MPI

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from ipc_benchmark import LMDBBackend, SharedMemoryBackend, ZMQBackend
from ipc_benchmark.base import IPCBackend
from ipc_benchmark.utils import generate_test_dict


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
# Add filter to root logger
logging.getLogger().addFilter(_rank_filter)


class BenchmarkResult:
    """Container for benchmark results."""

    def __init__(self, backend_name: str, data_size: int, rank: int):
        self.backend_name = backend_name
        self.data_size = data_size
        self.rank = rank
        self.write_time: float = 0.0
        self.read_time: float = 0.0
        self.read_count: int = 0

    @property
    def avg_read_time(self) -> float:
        """Average read time per operation."""
        return self.read_time / self.read_count if self.read_count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "data_size": self.data_size,
            "rank": self.rank,
            "write_time": self.write_time,
            "read_time": self.read_time,
            "read_count": self.read_count,
            "avg_read_time": self.avg_read_time,
        }


def benchmark_write(
    backend: IPCBackend, data: dict[str, Any], num_messages: int = 1
) -> float:
    """Benchmark write operation.

    Args:
        backend: IPC backend to test
        data: Data to write
        num_messages: Number of messages to send (for message-passing backends like ZMQ)

    Returns:
        Write time in seconds
    """
    start = time.perf_counter()
    for _ in range(num_messages):
        backend.write(data)
    return time.perf_counter() - start


def benchmark_read(backend: IPCBackend, iterations: int) -> tuple[float, int]:
    """Benchmark read operations.

    Returns:
        Tuple of (total_time, successful_reads)
    """
    successful_reads = 0
    start = time.perf_counter()

    for _ in range(iterations):
        result = backend.read()
        if result is not None:
            successful_reads += 1

    total_time = time.perf_counter() - start
    return total_time, successful_reads


def run_benchmark(
    backend: IPCBackend, data_size: int, rank: int, size: int, iterations: int = 100
) -> BenchmarkResult:
    """Run benchmark for a single backend.

    Args:
        backend: IPC backend to test
        data_size: Number of dictionary entries
        rank: MPI rank
        size: Total MPI processes
        iterations: Number of read iterations per reader

    Returns:
        Benchmark results
    """
    logger = logging.getLogger(__name__)
    logger = logging.LoggerAdapter(logger, {"rank": rank})

    result = BenchmarkResult(backend.get_name(), data_size, rank)
    is_writer = rank == 0

    comm = MPI.COMM_WORLD

    if is_writer:
        # Writer initializes first
        backend.initialize(f"bench_{data_size}", is_writer)

        # Generate test data
        logger.info("Generating test data (%d entries)...", data_size)
        test_data = generate_test_dict(data_size)

        # Signal readers that backend is ready
        comm.Barrier()
    else:
        # Readers wait for writer to initialize backend
        comm.Barrier()

        # Now readers can safely attach
        backend.initialize(f"bench_{data_size}", is_writer)

    # Additional barrier to ensure all processes are initialized
    comm.Barrier()

    if is_writer:
        # Benchmark write
        logger.info("Writing data...")

        # ZMQ is message-passing: send iterations * num_readers messages
        if backend.get_name() == "ZeroMQ":
            num_readers = size - 1
            num_messages = iterations * num_readers
            logger.info(
                "ZMQ: Sending %d messages (%d readers * %d iterations)",
                num_messages,
                num_readers,
                iterations,
            )
            result.write_time = benchmark_write(backend, test_data, num_messages)
        else:
            # Shared storage: write once
            result.write_time = benchmark_write(backend, test_data)

        logger.info("Write completed in %.4f seconds", result.write_time)

        # Signal readers that data is ready
        comm.Barrier()

    else:
        # Wait for data to be written
        comm.Barrier()

        # Benchmark read
        logger.info("Reading data (%d iterations)...", iterations)
        result.read_time, result.read_count = benchmark_read(backend, iterations)
        logger.info(
            "Read completed: %d/%d successful (%.4f seconds total, %.6f seconds avg)",
            result.read_count,
            iterations,
            result.read_time,
            result.read_time / result.read_count if result.read_count > 0 else 0,
        )

    # Cleanup
    backend.cleanup()

    return result


def main():
    """Main benchmark runner."""
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

    # Test configurations
    data_sizes = [10, 100, 1000, 10000]  # Dictionary sizes
    iterations = 100  # Read iterations per reader

    # Create backends
    backends: list[IPCBackend] = [
        LMDBBackend(),
        SharedMemoryBackend(),
        ZMQBackend(),
    ]

    all_results: list[BenchmarkResult] = []

    for data_size in data_sizes:
        if rank == 0:
            print(f"\n{'='*60}")
            print(f"Testing with data_size={data_size} ({size-1} readers)")
            print(f"{'='*60}")

        for backend in backends:
            comm.Barrier()  # Sync before each test
            result = run_benchmark(backend, data_size, rank, size, iterations)
            all_results.append(result)
            comm.Barrier()  # Sync after each test

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

        # Print summary
        print("\nSummary:")
        for backend_name in set(r.backend_name for r in results_flat):
            print(f"\n{backend_name}:")
            for data_size in data_sizes:
                write_results = [
                    r
                    for r in results_flat
                    if r.backend_name == backend_name
                    and r.data_size == data_size
                    and r.rank == 0
                ]
                read_results = [
                    r
                    for r in results_flat
                    if r.backend_name == backend_name
                    and r.data_size == data_size
                    and r.rank != 0
                ]

                if write_results:
                    write_time = write_results[0].write_time
                    print(f"  Data size {data_size:5d}: Write={write_time:.4f}s", end="")

                if read_results:
                    avg_read = sum(r.avg_read_time for r in read_results) / len(
                        read_results
                    )
                    print(f" | Avg read={avg_read:.6f}s")


if __name__ == "__main__":
    main()

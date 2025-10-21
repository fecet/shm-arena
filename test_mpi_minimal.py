"""Minimal test to debug MPI streaming deadlock."""

import sys
from pathlib import Path
from mpi4py import MPI

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ipc_benchmark import MPIBackend
from ipc_benchmark.utils import serialize, generate_test_dict

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

if size != 2:
    if rank == 0:
        print("Run with: mpiexec -n 2 python test_mpi_minimal.py")
    sys.exit(1)

backend = MPIBackend()
is_writer = rank == 0

# Initialize
comm.Barrier()
if is_writer:
    backend.initialize("test", True)
    data = generate_test_dict(100)
    print(f"[Rank {rank}] Initialized writer")
else:
    backend.initialize("test", False)
    data = None
    print(f"[Rank {rank}] Initialized reader")

comm.Barrier()

# Test streaming with 5 messages
iterations = 5

if is_writer:
    serialized = serialize(data)
    print(f"[Rank {rank}] Starting to send {iterations} messages...")
    for i in range(iterations):
        print(f"[Rank {rank}] Sending message {i+1}/{iterations}")
        backend.write_bytes(serialized)
    print(f"[Rank {rank}] Finished sending")
else:
    print(f"[Rank {rank}] Starting to receive {iterations} messages...")
    for i in range(iterations):
        print(f"[Rank {rank}] Waiting for message {i+1}/{iterations}")
        data = backend.read_bytes()
        if data:
            print(f"[Rank {rank}] Received message {i+1}/{iterations} ({len(data)} bytes)")
        else:
            print(f"[Rank {rank}] Failed to receive message {i+1}/{iterations}")
    print(f"[Rank {rank}] Finished receiving")

comm.Barrier()
backend.cleanup()
print(f"[Rank {rank}] Test complete")

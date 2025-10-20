"""Analyze and visualize benchmark results."""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def load_results(filename: str = "benchmark_results.json") -> pd.DataFrame:
    """Load benchmark results from JSON file.

    Args:
        filename: Path to results file

    Returns:
        DataFrame with benchmark results
    """
    with Path(filename).open() as f:
        data = json.load(f)

    return pd.DataFrame(data)


def plot_write_performance(df: pd.DataFrame, output_dir: Path):
    """Plot write performance comparison.

    Args:
        df: Results DataFrame
        output_dir: Directory to save plots
    """
    # Filter only writer results (rank 0)
    write_df = df[df["rank"] == 0].copy()

    if write_df.empty:
        print("No write data found")
        return

    # Pivot for plotting
    pivot = write_df.pivot(index="data_size", columns="backend", values="write_time")

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 6))
    pivot.plot(kind="bar", ax=ax)

    ax.set_xlabel("Dictionary Size (entries)")
    ax.set_ylabel("Write Time (seconds)")
    ax.set_title("Write Performance Comparison")
    ax.legend(title="Backend")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    output_file = output_dir / "write_performance.png"
    plt.savefig(output_file, dpi=150)
    print(f"Saved: {output_file}")
    plt.close()


def plot_read_performance(df: pd.DataFrame, output_dir: Path):
    """Plot read performance comparison.

    Args:
        df: Results DataFrame
        output_dir: Directory to save plots
    """
    # Filter only reader results (rank != 0)
    read_df = df[df["rank"] != 0].copy()

    if read_df.empty:
        print("No read data found")
        return

    # Calculate average read time per backend and data size
    avg_read = (
        read_df.groupby(["backend", "data_size"])["avg_read_time"]
        .mean()
        .reset_index()
    )

    # Pivot for plotting
    pivot = avg_read.pivot(index="data_size", columns="backend", values="avg_read_time")

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 6))
    pivot.plot(kind="bar", ax=ax)

    ax.set_xlabel("Dictionary Size (entries)")
    ax.set_ylabel("Average Read Time (seconds)")
    ax.set_title("Read Performance Comparison (averaged across readers)")
    ax.legend(title="Backend")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    output_file = output_dir / "read_performance.png"
    plt.savefig(output_file, dpi=150)
    print(f"Saved: {output_file}")
    plt.close()


def plot_throughput(df: pd.DataFrame, output_dir: Path):
    """Plot throughput comparison.

    Args:
        df: Results DataFrame
        output_dir: Directory to save plots
    """
    read_df = df[df["rank"] != 0].copy()

    if read_df.empty:
        print("No read data found")
        return

    # Calculate throughput (ops/sec)
    read_df["throughput"] = read_df["read_count"] / read_df["read_time"]

    # Average throughput per backend and data size
    avg_throughput = (
        read_df.groupby(["backend", "data_size"])["throughput"].mean().reset_index()
    )

    # Pivot for plotting
    pivot = avg_throughput.pivot(
        index="data_size", columns="backend", values="throughput"
    )

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 6))
    pivot.plot(kind="bar", ax=ax)

    ax.set_xlabel("Dictionary Size (entries)")
    ax.set_ylabel("Throughput (reads/second)")
    ax.set_title("Read Throughput Comparison")
    ax.legend(title="Backend")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    output_file = output_dir / "throughput.png"
    plt.savefig(output_file, dpi=150)
    print(f"Saved: {output_file}")
    plt.close()


def generate_summary_table(df: pd.DataFrame, output_dir: Path):
    """Generate summary statistics table.

    Args:
        df: Results DataFrame
        output_dir: Directory to save output
    """
    # Write performance
    write_df = df[df["rank"] == 0][["backend", "data_size", "write_time"]]

    # Read performance
    read_df = df[df["rank"] != 0].copy()
    read_summary = (
        read_df.groupby(["backend", "data_size"])
        .agg(
            {
                "avg_read_time": ["mean", "std"],
                "throughput": lambda x: (x.sum() if "throughput" in read_df.columns else 0),
            }
        )
        .reset_index()
    )

    # Save to CSV
    write_file = output_dir / "write_summary.csv"
    write_df.to_csv(write_file, index=False)
    print(f"Saved: {write_file}")

    read_file = output_dir / "read_summary.csv"
    read_summary.to_csv(read_file, index=False)
    print(f"Saved: {read_file}")

    # Print to console
    print("\n" + "=" * 60)
    print("WRITE PERFORMANCE SUMMARY")
    print("=" * 60)
    print(write_df.to_string(index=False))

    print("\n" + "=" * 60)
    print("READ PERFORMANCE SUMMARY")
    print("=" * 60)
    print(read_summary.to_string(index=False))


def main():
    """Main analysis function."""
    results_file = "benchmark_results.json"

    if not Path(results_file).exists():
        print(f"Error: {results_file} not found")
        print("Run benchmark_mpi.py first to generate results")
        return

    # Load results
    print(f"Loading results from {results_file}...")
    df = load_results(results_file)

    print(f"Loaded {len(df)} result records")
    print(f"Backends: {df['backend'].unique()}")
    print(f"Data sizes: {sorted(df['data_size'].unique())}")
    print(f"MPI ranks: {sorted(df['rank'].unique())}")

    # Create output directory
    output_dir = Path("benchmark_plots")
    output_dir.mkdir(exist_ok=True)

    # Generate plots
    print("\nGenerating plots...")
    plot_write_performance(df, output_dir)
    plot_read_performance(df, output_dir)
    plot_throughput(df, output_dir)

    # Generate summary tables
    print("\nGenerating summary tables...")
    generate_summary_table(df, output_dir)

    print(f"\nAnalysis complete! Results saved to {output_dir}/")


if __name__ == "__main__":
    main()

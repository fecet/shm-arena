"""Analyze and visualize benchmark results grouped by scenario."""

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


def plot_scenario_comparison(df: pd.DataFrame, output_dir: Path):
    """Plot performance comparison grouped by scenario.

    Args:
        df: Results DataFrame
        output_dir: Directory to save plots
    """
    scenarios = df["scenario"].unique()

    for scenario in scenarios:
        scenario_df = df[df["scenario"] == scenario]

        # Write performance
        write_df = scenario_df[scenario_df["rank"] == 0]
        if not write_df.empty:
            fig, ax = plt.subplots(figsize=(10, 6))
            backends = write_df["backend"].unique()
            write_times = [
                write_df[write_df["backend"] == b]["write_time"].iloc[0] * 1000
                for b in backends
            ]

            ax.bar(backends, write_times)
            ax.set_ylabel("Write Time (ms)")
            ax.set_title(f"Write Performance - {scenario.upper()} Scenario")
            ax.grid(axis="y", alpha=0.3)

            plt.tight_layout()
            output_file = output_dir / f"write_{scenario}.png"
            plt.savefig(output_file, dpi=150)
            print(f"Saved: {output_file}")
            plt.close()

        # Read performance
        read_df = scenario_df[scenario_df["rank"] != 0]
        if not read_df.empty:
            avg_read = (
                read_df.groupby("backend")["avg_read_time"].mean().reset_index()
            )

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.bar(avg_read["backend"], avg_read["avg_read_time"] * 1000)
            ax.set_ylabel("Avg Read Time (ms)")
            ax.set_title(f"Read Performance - {scenario.upper()} Scenario")
            ax.grid(axis="y", alpha=0.3)

            plt.tight_layout()
            output_file = output_dir / f"read_{scenario}.png"
            plt.savefig(output_file, dpi=150)
            print(f"Saved: {output_file}")
            plt.close()

        # Throughput (streaming scenario only)
        if scenario == "streaming" and not read_df.empty:
            avg_throughput = (
                read_df.groupby("backend")["throughput"].mean().reset_index()
            )

            fig, ax = plt.subplots(figsize=(10, 6))
            ax.bar(avg_throughput["backend"], avg_throughput["throughput"])
            ax.set_ylabel("Throughput (msg/s)")
            ax.set_title("Throughput - STREAMING Scenario")
            ax.grid(axis="y", alpha=0.3)

            plt.tight_layout()
            output_file = output_dir / "throughput_streaming.png"
            plt.savefig(output_file, dpi=150)
            print(f"Saved: {output_file}")
            plt.close()


def generate_scenario_summary(df: pd.DataFrame, output_dir: Path):
    """Generate summary tables grouped by scenario.

    Args:
        df: Results DataFrame
        output_dir: Directory to save output
    """
    scenarios = df["scenario"].unique()

    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 70)

    for scenario in scenarios:
        scenario_df = df[df["scenario"] == scenario]

        print(f"\n{'='*70}")
        print(f"Scenario: {scenario.upper()}")
        print(f"{'='*70}")

        # Write performance
        write_df = scenario_df[scenario_df["rank"] == 0][
            ["backend", "data_size", "write_time"]
        ]

        if not write_df.empty:
            print("\nWrite Performance:")
            print("-" * 70)
            for _, row in write_df.iterrows():
                print(
                    f"  {row['backend']:15s}: {row['write_time']*1000:8.2f} ms "
                    f"({row['data_size']} entries)"
                )

        # Read performance
        read_df = scenario_df[scenario_df["rank"] != 0]
        if not read_df.empty:
            read_summary = (
                read_df.groupby("backend")
                .agg(
                    {
                        "avg_read_time": "mean",
                        "read_count": "sum",
                        "throughput": "mean",
                    }
                )
                .reset_index()
            )

            print("\nRead Performance (averaged across readers):")
            print("-" * 70)
            for _, row in read_summary.iterrows():
                print(
                    f"  {row['backend']:15s}: {row['avg_read_time']*1000:8.2f} ms/read, "
                    f"{int(row['read_count'])} total reads"
                )
                if scenario == "streaming":
                    print(f"                      Throughput: {row['throughput']:.1f} msg/s")

        # Save CSV
        if not write_df.empty or not read_df.empty:
            summary_file = output_dir / f"summary_{scenario}.csv"
            scenario_df.to_csv(summary_file, index=False)
            print(f"\nSaved detailed results to: {summary_file}")

    # Cross-scenario comparison
    print(f"\n{'='*70}")
    print("CROSS-SCENARIO INSIGHTS")
    print(f"{'='*70}")

    backends = df["backend"].unique()
    for backend in backends:
        backend_df = df[df["backend"] == backend]
        print(f"\n{backend}:")

        for scenario in scenarios:
            scenario_backend_df = backend_df[backend_df["scenario"] == scenario]

            write_data = scenario_backend_df[scenario_backend_df["rank"] == 0]
            read_data = scenario_backend_df[scenario_backend_df["rank"] != 0]

            if not write_data.empty:
                write_time = write_data["write_time"].iloc[0] * 1000
                print(f"  {scenario:12s}: Write={write_time:8.2f}ms", end="")

            if not read_data.empty:
                avg_read = read_data["avg_read_time"].mean() * 1000
                print(f", Read={avg_read:7.2f}ms", end="")

                if scenario == "streaming":
                    avg_throughput = read_data["throughput"].mean()
                    print(f", Throughput={avg_throughput:6.1f}msg/s", end="")

            print()


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
    print(f"Backends: {', '.join(df['backend'].unique())}")
    print(f"Scenarios: {', '.join(df['scenario'].unique())}")
    print(f"Data sizes: {sorted(df['data_size'].unique())}")
    print(f"MPI ranks: {sorted(df['rank'].unique())}")

    # Create output directory
    output_dir = Path("benchmark_plots")
    output_dir.mkdir(exist_ok=True)

    # Generate plots
    print("\nGenerating plots...")
    plot_scenario_comparison(df, output_dir)

    # Generate summary tables
    print("\nGenerating summary...")
    generate_scenario_summary(df, output_dir)

    print(f"\n{'='*70}")
    print(f"Analysis complete! Results saved to {output_dir}/")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

import argparse
import csv
import hashlib
import json
import math
import os
import matplotlib
import matplotlib.pyplot as plt

from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from scipy.stats import t

matplotlib.use("Agg")

METRICS = {
    "avg_ms": "Average latency, ms",
    "p50_ms": "p50, ms",
    "p95_ms": "p95, ms",
    "p99_ms": "p99, ms",
    "hit_rate_pct": "Hit rate, %",
    "origin_requests": "Origin requests",
    "prefetch_requests": "Prefetch requests",
    "prefetch_hits": "Prefetch hits",
}

def extract_metrics(run: dict) -> dict:
    result = run["results"]
    
    latency = result["latency_ms"]
    counters = result["metrics"]
    
    return {
        "requests": int(result["sent_requests"]),
        "failures": int(result["failure_count"]),
        "rps": float(result["rps"]),
        "avg_ms": float(latency["average"]),
        "p50_ms": float(latency["p50"]),
        "p95_ms": float(latency["p95"]),
        "p99_ms": float(latency["p99"]),
        "hit_rate_pct": float(result["hit_rate"]) * 100,
        "origin_requests": int(counters["origin_requests"]),
        "prefetch_requests": int(counters["prefetch_requests"]),
        "prefetch_hits": int(counters["prefetch_hits"]),
    }

def read_manifest(path: Path, experiment: str) -> list[dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    
    if manifest.get("status") != "completed":
        raise ValueError(f"{experiment}: experiment was not completed")
    
    pairs = manifest["pairs"]
    
    if not pairs:
        raise ValueError(f"{experiment}: no pairs found")
    
    if len(pairs) != manifest.get("requested_repeats"):
        raise ValueError(f"{experiment}: incomplete experiment series")
    
    processed = []
    
    for pair in pairs:
        index = pair["pair_index"]
        
        validation = pair.get("workload_validation", {})
        
        if validation.get("matched") is not True:
            raise ValueError(f"{experiment}, pair {index}: workload mismatch")
        
        if experiment == "AA":
            labels = ("A", "B")
            
            runs = {
                run["label"]: run
                for run in pair["runs"]
            }
        else:
            labels = ("lru", "lru-ml")
            
            runs = {
                run["mode"]: run
                for run in pair["runs"]
            }
        
        if set(runs) != set(labels) or len(pair["runs"]) != 2:
            raise ValueError(f"{experiment}, pair {index}: invalid run structure")
        
        first = runs[labels[0]]
        second = runs[labels[1]]
        
        if experiment == "AA":
            first_trace = first["results"]["request_trace_json"]
            second_trace = second["results"]["request_trace_json"]
            
            normalize = lambda value: os.path.normcase(os.path.normpath(value))
            
            if normalize(first_trace) == normalize(second_trace):
                raise ValueError(
                    f"AA pair {index}: runs share one trace file. "
                    "Fix run_aa_experiment.py and repeat A/A."
                )
        
        for run in (first, second):
            if run.get("exit_code") != 0:
                raise ValueError(f"{experiment}, pair {index}: nonzero exit code")
            
        a = extract_metrics(first)
        b = extract_metrics(second)
        
        if a["failures"] or b["failures"]:
            raise ValueError(f"{experiment}, pair {index}: HTTP failures found")
        
        if a["requests"] != b["requests"]:
            raise ValueError(f"{experiment}, pair {index}: request count mismatch")
        
        processed.append({
            "pair": index,
            labels[0]: a,
            labels[1]: b,
        })
    return sorted(processed, key=lambda item: item["pair"])

def paired_statistics(a: list[float], b: list[float]) -> dict:
    if len(a) != len(b) or not a:
        raise ValueError("Invalid paired observations")
    
    differences = [
        second - first
        for first, second in zip(a, b)
    ]
    
    n = len(differences)
    average_difference = mean(differences)
    
    if n > 1:
        standard_deviation = stdev(differences)
        critical_value = float(t.ppf(0.975, df=n - 1))
        
        margin = critical_value * standard_deviation / math.sqrt(n)
        
        confidence_interval = [
            average_difference - margin,
            average_difference + margin,
        ]
    else: 
        standard_deviation = None
        confidence_interval = None
    
    effect_size = None
    
    if standard_deviation is not None and standard_deviation > 0:
        effect_size = average_difference / standard_deviation
    
    return {
        "n_pairs": n,
        "mean_a": mean(a),
        "mean_b": mean(b),
        "mean_difference_b_minus_a": average_difference,
        "standard_deviation_of_difference": standard_deviation,
        "ci95_difference": confidence_interval,
        "cohen_dz": effect_size,
        "pairs_b_greater": sum(x > 0 for x in differences),
        "pairs_equal": sum(x == 0 for x in differences),
        "pairs_b_lower": sum(x < 0 for x in differences),
    }

def summarize_experiment(pairs: list[dict], experiment: str) -> dict:
    labels = ("A", "B") if experiment == "AA" else ("lru", "lru-ml")
    
    summary = {}
    
    for metrics in METRICS:
        first_values = [
            pair[labels[0]][metrics]
            for pair in pairs
        ]
        
        second_value = [
            pair[labels[1]][metrics]
            for pair in pairs
        ]
        
        summary[metrics] = paired_statistics(first_values, second_value)
    
    if experiment != "AA":
        reductions = [
            100 
            * (pair["lru"]["p95_ms"] - pair["lru-ml"]["p95_ms"]) 
            / pair["lru"]["p95_ms"]
            for pair in pairs
        ]
        
        summary["mean_p95_reduction_pct"] = mean(reductions)
    
    return summary

def save_csv(output_path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        
        writer.writeheader()
        writer.writerows(rows)

def save_figure(figure, output_dir: Path, filename: str) -> None:
    figure.tight_layout()
    
    figure.savefig(
        output_dir / f"{filename}.png",
        dpi=200,
        bbox_inches="tight",
    )
    
    figure.savefig(
        output_dir / f"{filename}.pdf",
        bbox_inches="tight",
    )
    
    plt.close()

def plot_comparison(experiments: dict, metric: str, output_dir: Path) -> None:
    figure, axis = plt.subplots(figsize=(9, 5))
    
    positions = [1, 2, 4, 5]
    values = []
    labels = []
    
    for name in ("S1", "S3"):
        pairs = experiments[name]
        
        for mode in ("lru", "lru-ml"):
            values.append([
                pair[mode][metric]
                for pair in pairs
            ])
            
            labels.append(f"{name}\n{mode.upper()}")
    
    boxplot = axis.boxplot(
        values,
        positions=positions,
        widths=0.6,
        patch_artist=True,
        showbox=True,
    )
    
    colors = [
        "#4C78A8",
        "#F58518",
        "#4C78A8",
        "#F58518",
    ]
    
    for patch, color in zip(boxplot["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.45)
    
    for position, samples in zip(positions, values):
        offsets = [
            (i - (len(samples) - 1) / 2) * 0.025
            for i in range(len(samples))
        ]
        
        axis.scatter(
            [position + offset for offset in offsets],
            samples,
            color="black",
            s=22,
            alpha=0.65,
            zorder=3,
        )
    
    axis.set_xticks(positions)
    axis.set_xticklabels(labels)
    
    axis.set_ylabel(METRICS[metric])
    axis.set_title(f"Comparison: {METRICS[metric]}")
    
    save_figure(figure, output_dir, f"comparison_{metric}")

def plot_p95_differences(experiments: dict, output_dir: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))
    
    for axis, experiment in zip(axes, ("S1", "S3")):
        pairs = experiments[experiment]
        
        indices = [
            pair["pair"]
            for pair in pairs
        ]
        
        differences = [
            pair["lru-ml"]["p95_ms"]
            - pair["lru"]["p95_ms"]
            for pair in pairs
        ]
        
        axis.plot(indices, differences, marker="o", color="#F58518")
        
        axis.axhline(0, color="black", linestyle="--")
        
        axis.set_title(experiment)
        axis.set_xlabel("Pair")
        axis.set_ylabel("ML - LRU p95, ms")
        
        axis.set_xticks(indices)
        axis.grid(alpha=0.25)
    
    save_figure(figure, output_dir, "paired_p95_differences")

def plot_aa(pairs: list[dict], output_dir: Path) -> None:
    indices = [pair["pair"] for pair in pairs]
    
    differences = [
        pair["B"]["p95_ms"] - pair["A"]["p95_ms"]
        for pair in pairs
    ]
    
    figure, axis = plt.subplots(figsize=(8, 4))
    
    axis.plot(indices, differences, marker="o", color="#4C78A8")
    
    axis.axhline(0, color="black", linestyle="--")
    
    axis.set_title("A/A validation: p95 differences")
    axis.set_xlabel("Pair")
    axis.set_ylabel("B - A p95, ms")
    
    axis.set_xticks(indices)
    axis.grid(alpha=0.25)
    
    save_figure(figure, output_dir, "aa_p95_differences")
    
def main() -> None:
    parser = argparse.ArgumentParser()
    
    parser.add_argument("--s1", type=Path, required=True)
    parser.add_argument("--s3", type=Path, required=True)
    parser.add_argument("--aa", type=Path)
    parser.add_argument("--output", type=Path)
    
    args = parser.parse_args()
    
    sources = {
        "S1": args.s1,
        "S3": args.s3,
    }
    
    if args.aa is not None:
        sources["AA"] = args.aa
    
    experiments = {
        name: read_manifest(path, name)
        for name, path in sources.items()
    }
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    output_dir = args.output or (
        Path("results") / "analysis" / timestamp
    )
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "experiment": {},
    }
    
    run_rows = []
    paired_rows = []
    
    for name, pairs in experiments.items():
        labels = (
            ("A", "B")
            if name == "AA"
            else ("lru", "lru-ml")
        )
        
        summary["sources"][name] = {
            "path": str(sources[name].resolve()),
            "sha256": hashlib.sha256(sources[name].read_bytes()).hexdigest(),
        }
        
        summary["experiment"][name] = summarize_experiment(pairs, name)
        
        for pair in pairs:
            for label in labels: 
                run_rows.append({
                    "experiment": name,
                    "pair": pair["pair"],
                    "mode": label,
                    **pair[label]
                })
            
            paired_rows.append({
                "experiment": name,
                "pair": pair["pair"],
                **{
                    f"{metric}_difference": (
                        pair[labels[1]][metric] - pair[labels[0]][metric]
                    )
                    for metric in METRICS
                },
            })
            
        p95 = summary["experiment"][name]["p95_ms"]
        
        print(
            f"{name}: "
            f"pairs={len(pairs)}, "
            f"p95 difference={p95['mean_difference_b_minus_a']:+.3f} ms, "
            f"95% CI={p95['ci95_difference']}",
            flush=True,
        )
        
        save_csv(output_dir / "runs.csv", list(run_rows[0]), run_rows)
        
        save_csv(output_dir / "paired_effects.csv", list(paired_rows[0]), paired_rows)
        
        (output_dir / "analysis_summary.json").write_text(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        
        for metric in (
            "p95_ms",
            "avg_ms",
            "hit_rate_pct",
            "origin_requests",
        ):
            plot_comparison(experiments, metric, output_dir)
        
        plot_p95_differences(experiments, output_dir)
        
        if "AA" in experiments:
            plot_aa(experiments["AA"], output_dir)
        
        print(f"\nAnalysis saved to: {output_dir.resolve()}")

if __name__ == "__main__":
    main()
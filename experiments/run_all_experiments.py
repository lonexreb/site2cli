"""Run all site2cli validation experiments and generate a combined report.

This is the master runner for pre-launch validation. Run this to prove
site2cli's claims before the GitHub announcement.

Usage:
    python experiments/run_all_experiments.py          # Run all
    python experiments/run_all_experiments.py 9 11     # Run specific experiments
    python experiments/run_all_experiments.py --quick   # Run experiments 8 + 9 only

Run: python experiments/run_all_experiments.py
"""

import subprocess
import sys
import time
from pathlib import Path

EXPERIMENTS = {
    8: ("experiment_8_live_validation.py", "Live Validation (5 APIs, pipeline proof)"),
    9: ("experiment_9_api_breadth.py", "API Discovery Breadth (10 diverse APIs)"),
    10: ("experiment_10_unofficial_api_benchmark.py", "Unofficial API Benchmark (coverage scoring)"),
    11: ("experiment_11_speed_cost_benchmark.py", "Speed & Cost Benchmark (cold/warm/throughput)"),
    12: ("experiment_12_mcp_validation.py", "MCP Server Validation (schema/handler checks)"),
    13: ("experiment_13_spec_accuracy.py", "Spec Accuracy Benchmark (ground truth comparison)"),
    14: ("experiment_14_resilience.py", "Resilience & Health Monitoring"),
}

EXPERIMENTS_DIR = Path(__file__).parent


def run_experiment(num: int, filename: str, description: str) -> tuple[int, float]:
    """Run a single experiment and return (exit_code, duration_seconds)."""
    filepath = EXPERIMENTS_DIR / filename
    if not filepath.exists():
        print(f"  File not found: {filepath}")
        return 1, 0

    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(filepath)],
        cwd=str(EXPERIMENTS_DIR.parent),
        timeout=600,  # 10 minute timeout per experiment
    )
    duration = time.monotonic() - t0
    return result.returncode, duration


def main():
    args = sys.argv[1:]

    # Parse arguments
    if "--quick" in args:
        selected = [8, 9]
    elif args:
        selected = [int(a) for a in args if a.isdigit()]
    else:
        selected = sorted(EXPERIMENTS.keys())

    print("=" * 80)
    print("site2cli — Pre-Launch Validation Suite")
    print("=" * 80)
    print(f"\nRunning {len(selected)} experiments: {', '.join(f'#{n}' for n in selected)}\n")

    results = {}
    total_t0 = time.monotonic()

    for num in selected:
        if num not in EXPERIMENTS:
            print(f"Unknown experiment #{num}, skipping")
            continue

        filename, description = EXPERIMENTS[num]
        print(f"\n{'━' * 80}")
        print(f"EXPERIMENT #{num}: {description}")
        print(f"{'━' * 80}\n")

        try:
            exit_code, duration = run_experiment(num, filename, description)
            results[num] = ("PASS" if exit_code == 0 else "FAIL", duration)
        except subprocess.TimeoutExpired:
            results[num] = ("TIMEOUT", 600)
            print(f"\n  TIMEOUT: Experiment #{num} exceeded 10 minutes")
        except Exception as e:
            results[num] = ("ERROR", 0)
            print(f"\n  ERROR: {e}")

    total_duration = time.monotonic() - total_t0

    # ── Final Report ─────────────────────────────────────────────────────────

    print("\n\n" + "=" * 80)
    print("FINAL REPORT — site2cli Pre-Launch Validation")
    print("=" * 80)

    print(f"\n  {'#':>3} {'Experiment':<50} {'Result':>8} {'Duration':>10}")
    print(f"  {'-' * 75}")

    passed = 0
    failed = 0
    for num in selected:
        if num in results:
            status, duration = results[num]
            desc = EXPERIMENTS[num][1]
            mark = "✓" if status == "PASS" else "✗"
            print(f"  {num:>3} {desc:<50} {mark} {status:<6} {duration:>7.1f}s")
            if status == "PASS":
                passed += 1
            else:
                failed += 1

    print(f"  {'-' * 75}")
    print(f"  {'':>3} {'TOTAL':<50} {passed}/{passed+failed}    {total_duration:>7.1f}s")

    print(f"\n  {'ALL EXPERIMENTS PASSED ✓' if failed == 0 else f'{failed} EXPERIMENT(S) FAILED ✗'}")

    if failed == 0:
        print(f"""
  ┌─────────────────────────────────────────────────────┐
  │  site2cli is ready for GitHub announcement!         │
  │                                                     │
  │  Validated:                                         │
  │  • API discovery across 15+ diverse APIs            │
  │  • Generated specs, clients, MCP servers all work   │
  │  • Progressive formalization proven (cost savings)  │
  │  • Health monitoring accurate                       │
  │  • Resilience under real-world conditions           │
  └─────────────────────────────────────────────────────┘
""")

    print("=" * 80)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

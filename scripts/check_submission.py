"""Check artifact completeness and cross-file numerical consistency after a run."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def main():
    for name in ["README.md", "DATA.md", "RESULTS.md", "Recommendation.md", "requirements.txt", "config.json"]:
        assert (ROOT / name).stat().st_size > 10, name
    for stem in ["00_raw_cleaning", "01_daily_trace", "02_detected_cycles", "03_house_comparison",
                 "04_usage_patterns", "05_model_comparison", "06_predictions_and_failures"]:
        for extension in ["png", "svg"]:
            assert (ROOT / "output" / f"{stem}.{extension}").stat().st_size > 1000, stem
    directory = ROOT / "artifacts/tables"
    summary = pd.read_csv(directory / "household_summary.csv")
    assert len(summary) >= 4
    assert (summary.complete_events > 0).all(), "At least one house lacks complete event evidence"
    scores = pd.read_csv(directory / "model_metrics.csv", dtype={"house": str})
    primary = scores.loc[scores.experiment.eq("chronological")]
    assert primary.groupby("house").n_minutes.nunique().eq(1).all(), "Baselines use different test cohorts"
    for method, group in primary.groupby("model"):
        total = group.loc[group.house.eq("ALL")].iloc[0]
        homes = group.loc[group.house.ne("ALL")]
        assert total.n_minutes == homes.n_minutes.sum()
        assert abs(total.actual_kwh-homes.actual_kwh.sum()) < 1e-8
    specs = json.loads((directory / "model_specification.json").read_text())
    assert not any("Appliance" in c or "target" in c or "house" in c or "sparse" in c for c in specs["features"])
    splits = pd.read_csv(directory / "split_coverage.csv")
    assert splits.groupby("split").active_minutes.sum().gt(0).all()
    print("Submission checks passed: documents, seven figure pairs, four-house events, aligned baselines, consistent energy totals and aggregate-only features.")

if __name__ == "__main__":
    main()

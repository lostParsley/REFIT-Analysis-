"""Read the documented release in chunks and retain an auditable analysis window."""
from pathlib import Path
import json
import re
import numpy as np
import pandas as pd
from .core import minute_data

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())
TABLES = ROOT / "artifacts" / "tables"


def load_house(house, raw=False):
    directory = ROOT / "data" / ("raw" if raw else "official_clean")
    files = sorted(p for p in directory.rglob("*.csv") if re.search(rf"House_?{house}(?:_|\.)", p.name, re.I))
    if not files:
        raise FileNotFoundError(f"House {house} missing under {directory}; run extraction first")
    pieces, inventory = [], []
    start, end = pd.Timestamp(CONFIG["start"], tz="UTC"), pd.Timestamp(CONFIG["end"], tz="UTC")
    for file in files:
        n, invalid, first, last = 0, 0, None, None
        differences = {}
        for chunk in pd.read_csv(file, chunksize=250000):
            chunk.columns = chunk.columns.str.strip()
            unix = next(c for c in chunk if "unix" in c.lower())
            time = pd.to_datetime(pd.to_numeric(chunk[unix], errors="coerce"), unit="s", utc=True, errors="coerce")
            n += len(chunk)
            invalid += int(time.isna().sum())
            if time.notna().any():
                first = time.min() if first is None else min(first, time.min())
                last = time.max() if last is None else max(last, time.max())
            text_column = next((c for c in chunk if c.lower() in ("time", "datetime")), None)
            if text_column:
                printed = pd.to_datetime(chunk[text_column], errors="coerce", utc=True)
                offsets = (printed-time).dt.total_seconds().value_counts()
                for offset, count in offsets.items():
                    differences[str(offset)] = differences.get(str(offset), 0)+int(count)
            selected = time.ge(start) & time.lt(end)
            if selected.any():
                kept = chunk.loc[selected].copy()
                kept.index = pd.DatetimeIndex(time[selected])
                cols = [c for c in kept if c == "Aggregate" or c.startswith("Appliance") or c == "Issues"]
                pieces.append(kept[cols].apply(pd.to_numeric, errors="coerce"))
        inventory.append(dict(file=str(file.relative_to(ROOT)), rows=n, invalid_unix=invalid,
                              first_utc=str(first), last_utc=str(last), text_minus_unix_seconds=differences))
    frame = pd.concat(pieces)
    delta = frame.index.to_series().diff().dt.total_seconds()
    power = [c for c in frame if c != "Issues"]
    stats = dict(house=house, raw=raw, files=inventory, selected_rows=len(frame),
                 selected_first_utc=str(frame.index.min()), selected_last_utc=str(frame.index.max()),
                 duplicate_rows=int(frame.index.duplicated().sum()), backwards_steps=int(delta.lt(0).sum()),
                 median_interval_s=float(delta[delta.gt(0)].median()),
                 non_eight_second_steps=int((delta.notna() & delta.ne(8)).sum()),
                 gaps_over_60s=int(delta.gt(60).sum()), max_interval_s=float(delta.max()),
                 missing_by_channel=frame[power].isna().sum().to_dict(),
                 negative_by_channel=frame[power].lt(0).sum().to_dict(),
                 over_4000w_iam=frame.filter(like="Appliance").gt(4000).sum().to_dict(),
                 aggregate_over_20000w=int(frame.Aggregate.gt(20000).sum()),
                 aggregate_max_w=float(frame.Aggregate.max()))
    minimum = CONFIG["minimum_samples_per_minute"] if raw else CONFIG["clean_minimum_samples_per_minute"]
    minute, flags, before = minute_data(frame, minimum, raw, CONFIG["short_gap_minutes"])
    if raw:
        unmodified = frame[power].sort_index().resample("1min").mean()
        destination = ROOT / "data" / "processed"
        destination.mkdir(parents=True, exist_ok=True)
        unmodified.to_pickle(destination / "raw_house1_unmodified.pkl")
    unique_delta = pd.Series(frame.index.unique().sort_values()).diff().dt.total_seconds()
    stats["sorted_unique_median_interval_s"] = float(unique_delta.median())
    stats["sorted_unique_gaps_over_60s"] = int(unique_delta.gt(60).sum())
    stats["sorted_unique_max_gap_s"] = float(unique_delta.max())
    full_index = pd.date_range(start, end, freq="1min", inclusive="left")
    minute, before = minute.reindex(full_index), before.reindex(full_index)
    flags = flags.reindex(full_index)
    flags["issues"] = flags["issues"].fillna(True).astype(bool)
    stats["missing_minutes_before"] = before.isna().sum().to_dict()
    stats["missing_minutes_after"] = minute.isna().sum().to_dict()
    stats["imputed_cells"] = int(flags.imputed_cells.sum())
    stats["issue_minutes"] = int(flags.issues.sum())
    stats["long_gap_minutes_by_channel"] = {c: int(flags[f"{c}_long_gap"].sum()) for c in power}
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / f"{'raw' if raw else 'clean'}_house{house}_audit.json").write_text(json.dumps(stats, indent=2))
    return minute, flags, before, stats


def prepare():
    destination = ROOT / "data" / "processed"
    destination.mkdir(parents=True, exist_ok=True)
    print("Preparing raw House 1", flush=True)
    raw, flags, before, stats = load_house(1, raw=True)
    raw.to_pickle(destination / "raw_house1.pkl")
    before.to_pickle(destination / "raw_house1_before.pkl")
    flags.to_pickle(destination / "raw_house1_flags.pkl")
    homes = {}
    for house, channel in CONFIG["houses"].items():
        print(f"Preparing official cleaned House {house}, {channel}", flush=True)
        frame, flags, _, stats = load_house(int(house))
        selected = frame[["Aggregate", channel]].rename(columns={channel: "washing_machine"})
        selected["issues"] = flags.issues
        selected["low_sample_count"] = flags[["Aggregate_samples", f"{channel}_samples"]].min(axis=1).lt(5)
        # Strict primary cohort: documented issues, impossible mains and target mismatch excluded.
        selected["valid"] = (selected[["Aggregate", "washing_machine"]].notna().all(axis=1)
                             & ~selected.issues & selected.Aggregate.gt(0)
                             & selected.washing_machine.le(selected.Aggregate))
        selected.to_pickle(destination / f"house{house}.pkl")
        homes[house] = selected
    return homes


def read_prepared():
    return {h: pd.read_pickle(ROOT / "data" / "processed" / f"house{h}.pkl") for h in CONFIG["houses"]}

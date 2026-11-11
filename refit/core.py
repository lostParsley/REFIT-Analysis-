"""Small, testable data transformations. All power values are in watts."""
import numpy as np
import pandas as pd


def fill_short_gaps(series, limit=2):
    """Interpolate only entire bounded missing runs of at most `limit` minutes."""
    missing = series.isna()
    groups = missing.ne(missing.shift()).cumsum()
    lengths = missing.groupby(groups).transform("sum")
    candidate = series.interpolate(method="time", limit_area="inside")
    return series.where(~(missing & lengths.le(limit)), candidate)


def minute_data(frame, minimum_samples=5, raw=False, gap_limit=2):
    """Median duplicate resolution, mean power bins, explicit validity masks."""
    power = [c for c in frame if c == "Aggregate" or c.startswith("Appliance")]
    frame = frame.sort_index(kind="stable")
    values = frame[power].groupby(level=0).median()
    values = values.mask(values.lt(0))
    for column in power:
        # IAM rated ceiling documented by REFIT; aggregate limit is a flag only.
        if column.startswith("Appliance"):
            values[column] = values[column].mask(values[column].gt(4000))
    counts = values.resample("1min").count()
    result = values.resample("1min").mean().where(counts.ge(minimum_samples))
    before = result.copy()
    if raw:
        result = result.apply(fill_short_gaps, limit=gap_limit)
    flags = pd.DataFrame(index=result.index)
    flags["imputed_cells"] = (before.isna() & result.notna()).sum(axis=1)
    flags["low_coverage"] = counts.lt(minimum_samples).any(axis=1)
    flags["unresolved_missing"] = result.isna().any(axis=1)
    for column in power:
        flags[f"{column}_samples"] = counts[column]
        missing = before[column].isna()
        run = missing.ne(missing.shift()).cumsum()
        lengths = missing.groupby(run).transform("sum")
        flags[f"{column}_long_gap"] = missing & lengths.gt(gap_limit)
    if "Issues" in frame:
        flags["issues"] = frame["Issues"].groupby(level=0).max().resample("1min").max().reindex(result.index).fillna(1).gt(0)
    else:
        flags["issues"] = False
    return result, flags, before


def cycles(series, threshold=20, pause=10, minimum_minutes=10, minimum_kwh=0.02):
    """Bridge observed off pauses; never bridge missing data or trust edge events."""
    active = series.gt(threshold).to_numpy()
    observed = series.notna().to_numpy()
    indices = np.flatnonzero(active)
    columns = ["start", "end", "duration_min", "active_min", "energy_kwh", "peak_w", "censored"]
    if not len(indices):
        return pd.DataFrame(columns=columns)
    runs, start, previous = [], indices[0], indices[0]
    for current in indices[1:]:
        if current - previous - 1 > pause or not observed[previous:current+1].all():
            runs.append((start, previous))
            start = current
        previous = current
    runs.append((start, previous))
    events = []
    for left, right in runs:
        segment = series.iloc[left:right+1]
        duration, energy = right-left+1, segment.sum()/60000
        if duration < minimum_minutes or energy < minimum_kwh:
            continue
        # A full quiet buffer is required on both sides to call an event complete.
        censored = (left < pause or right+pause >= len(series)
                    or not observed[max(0,left-pause):min(len(series),right+pause+1)].all())
        events.append([series.index[left], series.index[right], duration,
                       int(active[left:right+1].sum()), energy, segment.max(), bool(censored)])
    return pd.DataFrame(events, columns=columns)


def features(aggregate):
    """Causal 60-minute aggregate-only context; no appliance labels or house IDs."""
    x = pd.DataFrame({"power": aggregate})
    for lag in (1, 2, 5, 10, 15, 30, 60):
        x[f"lag_{lag}"] = aggregate.shift(lag)
    for window in (5, 15, 30, 60):
        roll = aggregate.rolling(window, min_periods=window)
        for name in ("mean", "std", "min", "max"):
            x[f"{name}_{window}"] = getattr(roll, name)()
    x["delta"] = aggregate.diff()
    x["above_background"] = aggregate - aggregate.rolling(60, min_periods=60).min()
    # Reject every window containing a missing minute, including unsampled lags.
    complete = aggregate.notna().rolling(61, min_periods=61).sum().eq(61)
    return x.where(complete, np.nan)


def metrics(actual, predicted, threshold=20):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    on, detected = actual > threshold, predicted > threshold
    tp, fp, fn = (on & detected).sum(), (~on & detected).sum(), (on & ~detected).sum()
    true_energy, predicted_energy = actual.sum()/60000, predicted.sum()/60000
    return {
        "n_minutes": len(actual), "mae_w": float(np.abs(actual-predicted).mean()),
        "rmse_w": float(np.sqrt(np.mean((actual-predicted)**2))),
        "active_mae_w": float(np.abs(actual[on]-predicted[on]).mean()) if on.any() else np.nan,
        "precision": float(tp/(tp+fp)) if tp+fp else 0.0,
        "recall": float(tp/(tp+fn)) if tp+fn else 0.0,
        "f1": float(2*tp/(2*tp+fp+fn)) if 2*tp+fp+fn else 0.0,
        "actual_kwh": float(true_energy), "predicted_kwh": float(predicted_energy),
        "energy_error_pct": float(100*(predicted_energy-true_energy)/true_energy) if true_energy else np.nan,
    }

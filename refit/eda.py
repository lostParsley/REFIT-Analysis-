import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from .core import cycles
from .data import ROOT, CONFIG, TABLES
from .plots import save, times, BLUE, TEAL, ORANGE


def analyse(homes):
    summaries, events, sensitivity = [], [], []
    for house, frame in homes.items():
        # Appliance EDA retains publisher Issues flags: they concern summed sensors,
        # not proof that the washer channel itself is invalid. Report them separately.
        wm = frame.washing_machine
        detected = cycles(wm, CONFIG["activity_threshold_w"], CONFIG["cycle_pause_minutes"],
                          CONFIG["cycle_minimum_minutes"], CONFIG["cycle_minimum_kwh"])
        detected["house"] = house
        events.append(detected)
        complete = detected.loc[~detected.censored.astype(bool)]
        summaries.append(dict(house=house, channel=CONFIG["houses"][house], total_minutes=len(frame),
            missing_wm_minutes=int(frame.washing_machine.isna().sum()), issue_minutes=int(frame.issues.sum()),
            sparse_minutes=int(frame.low_sample_count.sum()),
            valid_minutes=int(wm.notna().sum()), valid_days_equivalent=wm.notna().sum()/1440,
            zero_pct=100*wm.eq(0).sum()/wm.notna().sum(), off_pct=100*wm.le(20).sum()/wm.notna().sum(),
            candidate_events=len(detected), complete_events=len(complete),
            events_per_30_observed_days=len(complete)/(wm.notna().sum()/1440)*30,
            median_duration_min=complete.duration_min.median(), median_energy_kwh=complete.energy_kwh.median(),
            observed_wm_kwh=wm.sum()/60000))
        for threshold in (10, 20, 50):
            for pause in (5, 10, 15):
                e = cycles(wm, threshold=threshold, pause=pause)
                sensitivity.append(dict(house=house, threshold_w=threshold, pause_min=pause,
                                        complete_events=int((~e.censored.astype(bool)).sum())))
    summary = pd.DataFrame(summaries)
    event = pd.concat(events, ignore_index=True)
    summary.to_csv(TABLES / "household_summary.csv", index=False)
    event.to_csv(TABLES / "events.csv", index=False)
    pd.DataFrame(sensitivity).to_csv(TABLES / "event_sensitivity.csv", index=False)
    complete = event.loc[~event.censored.astype(bool)].copy()
    complete["local_start"] = pd.to_datetime(complete.start, utc=True).dt.tz_convert("Europe/London")
    complete["hour"] = complete.local_start.dt.hour
    complete["weekday"] = complete.local_start.dt.dayofweek

    # Select a median-energy training-period event deterministically, not a dramatic example.
    training = complete.loc[complete.start < pd.Timestamp(CONFIG["train_end"], tz="UTC")]
    representative = training.loc[(training.energy_kwh-training.energy_kwh.median()).abs().idxmin()]
    frame = homes[representative.house]
    day = representative.local_start.normalize()
    view = frame.loc[(frame.index >= day) & (frame.index < day+pd.Timedelta(days=1))]
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(view.index, view.Aggregate, label="Whole-home aggregate", color=BLUE, lw=1)
    ax.plot(view.index, view.washing_machine, label="Washing machine", color=TEAL, lw=1.3)
    ax.set(title=f"House {representative.house} | a representative 24 hours", ylabel="Mean power (W)")
    ax.legend(frameon=False); times(ax); save(fig, "01_daily_trace")

    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    for ax, house in zip(axes.flat, homes):
        candidates = training.loc[training.house.eq(house)]
        selected = candidates.loc[(candidates.energy_kwh-candidates.energy_kwh.median()).abs().idxmin()]
        signal = homes[house].washing_machine
        view = signal.loc[selected.start-pd.Timedelta(minutes=20):selected.end+pd.Timedelta(minutes=20)]
        ax.plot(view.index, view, color=TEAL)
        ax.axhline(20, color=ORANGE, ls="--", lw=1)
        ax.axvspan(selected.start, selected.end, alpha=.12, color=TEAL)
        ax.set(title=f"House {house}: {selected.duration_min:.0f} min, {selected.energy_kwh:.2f} kWh", ylabel="Power (W)")
        times(ax)
    fig.suptitle("Detected events | median-energy training examples", fontweight="bold")
    fig.tight_layout(); save(fig, "02_detected_cycles")

    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, column, title, unit in zip(axes, ["duration_min", "energy_kwh", "peak_w"],
        ["Event duration", "Event energy", "Peak minute power"], ["Minutes", "kWh", "W"]):
        values = [complete.loc[complete.house.eq(h), column].to_numpy() for h in homes]
        ax.boxplot(values, tick_labels=[f"H{h}" for h in homes], showfliers=False,
                   patch_artist=True, boxprops={"facecolor": "#B4DAD4"}, medianprops={"color": TEAL})
        ax.set(title=title, ylabel=unit)
    fig.suptitle("Cross-house event characteristics | complete detected events", fontweight="bold")
    fig.tight_layout(); save(fig, "03_house_comparison")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    rates = []
    for house, frame in homes.items():
        local = frame.index.tz_convert("Europe/London")
        for kind, keys, ax, maximum in [("hour", local.hour, axes[0], 24), ("weekday", local.dayofweek, axes[1], 7)]:
            exposure = frame.washing_machine.notna().groupby(keys).sum().reindex(range(maximum), fill_value=0)/60
            counts = complete.loc[complete.house.eq(house)].groupby(kind).size().reindex(range(maximum), fill_value=0)
            rate = counts/exposure.replace(0, np.nan)*100
            ax.plot(range(maximum), rate, marker="o", ms=3, label=f"House {house}")
            rates.extend(dict(house=house, grouping=kind, bin=k, events=int(counts[k]), valid_hours=float(exposure[k]),
                              events_per_100_observed_hours=float(rate[k])) for k in range(maximum))
    axes[0].set(title="Event starts by local hour", xlabel="Hour of day", ylabel="Starts / 100 observed hours", xticks=range(0,24,3))
    axes[1].set(title="Event starts by day of week", ylabel="Starts / 100 observed hours", xticks=range(7), xticklabels=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])
    axes[1].legend(frameon=False)
    fig.tight_layout(); save(fig, "04_usage_patterns")
    pd.DataFrame(rates).to_csv(TABLES / "usage_rates.csv", index=False)

    before = pd.read_pickle(ROOT / "data/processed/raw_house1_before.pkl")
    unmodified = pd.read_pickle(ROOT / "data/processed/raw_house1_unmodified.pkl")
    after = pd.read_pickle(ROOT / "data/processed/raw_house1.pkl")
    columns = ["Aggregate", "Appliance1", "Appliance5"]
    changed = (before[columns].isna() & after[columns].notna()).sum(axis=1)
    change_by_day = changed.resample("1D").sum()
    active_by_day = after.Appliance5.gt(20).resample("1D").sum()
    candidates = change_by_day.loc[active_by_day.ge(20)]
    chosen = candidates.idxmax() if len(candidates) else change_by_day.idxmax()
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    for ax, col, label in zip(axes, columns, ["Aggregate", "Fridge", "Washing machine"]):
        b, a = before.loc[chosen:chosen+pd.Timedelta(days=1), col], after.loc[chosen:chosen+pd.Timedelta(days=1), col]
        original = unmodified.loc[chosen:chosen+pd.Timedelta(days=1), col]
        ax.plot(original.index, original, color=BLUE, lw=1, alpha=.7, label="Raw readings (1-min mean)")
        ax.plot(a.index, a, color=TEAL, lw=.8, alpha=.8, label="After cleaning")
        filled = b.isna() & a.notna()
        ax.scatter(a.index[filled], a[filled], s=12, color=ORANGE, zorder=5, label="Imputed minute")
        ax.set(title=label, ylabel="Power (W)")
    axes[0].legend(frameon=False, fontsize=8, ncol=3)
    times(axes[-1]); fig.suptitle("Raw House 1 | most repairs among days with washer activity", fontweight="bold")
    fig.tight_layout(); save(fig, "00_raw_cleaning")
    return summary, event

"""Chronological model selection, untouched test evaluation and transfer diagnostic."""
import json
import warnings
import time
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from .core import features, metrics
from .data import ROOT, CONFIG, TABLES
from .plots import save, times, BLUE, TEAL, ORANGE, RED


def split_frames(homes):
    bounds = [CONFIG["start"], CONFIG["train_end"], CONFIG["validation_end"], CONFIG["end"]]
    result, audit = {}, []
    for split, left, right in zip(["train", "validation", "test"], bounds, bounds[1:]):
        chunks = []
        for house, data in homes.items():
            selected = data.loc[(data.index >= pd.Timestamp(left, tz="UTC")) & (data.index < pd.Timestamp(right, tz="UTC"))]
            # The quality mask is cohort selection, never an input feature.
            x = features(selected.Aggregate.where(selected.Aggregate.gt(0)))
            x["target"] = selected.washing_machine.where(selected.valid)
            x["house"] = house
            x["sparse"] = selected.low_sample_count
            x["time"] = x.index
            x = x.dropna()
            audit.append(dict(split=split, house=house, start_utc=left, end_utc_exclusive=right,
                              calendar_minutes=len(selected), eligible_minutes=len(x),
                              active_minutes=int(x.target.gt(CONFIG["activity_threshold_w"]).sum())))
            chunks.append(x)
        result[split] = pd.concat(chunks, ignore_index=True)
    pd.DataFrame(audit).to_csv(TABLES / "split_coverage.csv", index=False)
    return result


def fit_candidates(train, validation, columns, experiment):
    candidates, records = {}, []
    for loss in ["squared_error", "poisson"]:
        print(f"Fitting {experiment}: {loss}", flush=True)
        started = time.perf_counter()
        model = HistGradientBoostingRegressor(loss=loss, max_iter=180, max_leaf_nodes=31,
            min_samples_leaf=40, learning_rate=.08, l2_regularization=10,
            early_stopping=False, random_state=CONFIG["seed"])
        numerical = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                model.fit(train[columns], train.target)
                unbounded = model.predict(validation[columns])
        except RuntimeWarning as error:
            numerical = [str(error)]
            unbounded = np.full(len(validation), np.nan)
        if numerical or not np.isfinite(unbounded).all():
            records.append(dict(experiment=experiment, loss=loss, macro_rmse_w=np.inf,
                                status="rejected: numerical instability", numerical_warnings="; ".join(sorted(set(numerical)))))
            print(f"Rejected {loss}: {numerical}; {time.perf_counter()-started:.1f}s", flush=True)
            continue
        prediction = np.clip(unbounded, 0, validation.power.to_numpy())
        score = metrics(validation.target, prediction)
        # Equal-house RMSE prevents the best-covered household dominating selection.
        rmses = [metrics(validation.loc[group.index, "target"], prediction[group.index.to_numpy()])["rmse_w"]
                 for _, group in validation.groupby("house")]
        score.update(experiment=experiment, loss=loss, macro_rmse_w=float(np.mean(rmses)), status="valid", numerical_warnings="")
        records.append(score)
        candidates[loss] = model
        print(f"Validated {loss}: macro RMSE {score['macro_rmse_w']:.2f} W; {time.perf_counter()-started:.1f}s", flush=True)
    chosen = min(records, key=lambda r: r["macro_rmse_w"])["loss"]
    for record in records:
        record["selected"] = record["loss"] == chosen
    return candidates[chosen], records, chosen


def evaluate(frame, name, prediction, experiment):
    frame = frame.reset_index(drop=True)
    prediction = np.asarray(prediction)
    rows = []
    for house, group in [("ALL", frame)] + list(frame.groupby("house")):
        idx = group.index.to_numpy()
        result = metrics(group.target, prediction[idx])
        daily = pd.DataFrame({"date": group.time.dt.floor("D"), "house": group.house,
                              "actual": group.target/60000, "predicted": prediction[idx]/60000})
        energy = daily.groupby(["house", "date"])[["actual", "predicted"]].sum()
        result["daily_energy_mae_kwh"] = float((energy.actual-energy.predicted).abs().mean())
        result.update(house=house, model=name, experiment=experiment)
        rows.append(result)
    return rows


def run(homes):
    splits = split_frames(homes)
    train, validation, test = (splits[k].reset_index(drop=True) for k in ["train", "validation", "test"])
    columns = [c for c in train if c not in ["target", "house", "time", "sparse"]]
    with threadpool_limits(limits=4):
        model, selection, loss = fit_candidates(train, validation, columns, "chronological")
        # Model frozen after validation: no retraining or test-driven changes.
        predictions = {"always_off": np.zeros(len(test))}
        train_hour = train.time.dt.tz_convert("Europe/London").dt.hour
        profile = train.groupby(["house", train_hour]).target.mean()
        test_hour = test.time.dt.tz_convert("Europe/London").dt.hour
        profile_keys = pd.MultiIndex.from_arrays([test.house, test_hour])
        predictions["hour_profile"] = profile.reindex(profile_keys).fillna(float(train.target.mean())).to_numpy()
        predictions["gradient_boosting"] = np.clip(model.predict(test[columns]), 0, test.power.to_numpy())
        rows = []
        for name, predicted in predictions.items():
            rows.extend(evaluate(test, name, predicted, "chronological"))
            dense_mask = ~test["sparse"]
            dense = test.loc[dense_mask].reset_index(drop=True)
            rows.extend(evaluate(dense, name, predicted[dense_mask], "dense_minutes_sensitivity"))
        output = test[["time", "house", "target", "power"]].copy()
        for name, predicted in predictions.items():
            output[name] = predicted
        output.to_csv(ROOT / "data/processed/test_predictions.csv.gz", index=False)
        model_dir = ROOT / "artifacts/models"
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(dict(model=model, features=columns), model_dir / "washing_machine.joblib")
        # Train and choose again without ANY House 5 data; this is an independent diagnostic.
        other_train = train.loc[train.house.ne("5")].reset_index(drop=True)
        other_valid = validation.loc[validation.house.ne("5")].reset_index(drop=True)
        unseen = test.loc[test.house.eq("5")].reset_index(drop=True)
        transfer, transfer_selection, transfer_loss = fit_candidates(other_train, other_valid, columns, "unseen_house5")
        transfer_prediction = np.clip(transfer.predict(unseen[columns]), 0, unseen.power.to_numpy())
        rows.extend(evaluate(unseen, "gradient_boosting", transfer_prediction, "unseen_house5"))
        rows.extend(evaluate(unseen, "always_off", np.zeros(len(unseen)), "unseen_house5"))
    pd.DataFrame(selection+transfer_selection).to_csv(TABLES / "validation_candidates.csv", index=False)
    scores = pd.DataFrame(rows)
    scores.to_csv(TABLES / "model_metrics.csv", index=False)
    (TABLES / "model_specification.json").write_text(json.dumps(dict(features=columns,
        selected_loss=loss, transfer_loss=transfer_loss, seed=CONFIG["seed"],
        max_iter=180, max_leaf_nodes=31, min_samples_leaf=40, learning_rate=.08,
        l2_regularization=10, early_stopping=False, prediction_clip="[0, aggregate]"), indent=2))

    # Paired day-block bootstrap: conditional uncertainty, not population inference.
    output["date"] = output.time.dt.floor("D")
    output["error_model"] = (output.target-output.gradient_boosting).abs()
    output["error_off"] = output.target.abs()
    daily = output.groupby(["house", "date"])[["error_model", "error_off"]].sum()
    daily["n"] = output.groupby(["house", "date"]).size()
    daily.to_csv(TABLES / "daily_error_blocks.csv")
    rng = np.random.default_rng(CONFIG["seed"])
    boot = []
    for _ in range(1000):
        sampled = pd.concat([g.iloc[rng.integers(0, len(g), len(g))] for _, g in daily.groupby(level=0)])
        boot.append((sampled.error_model.sum()-sampled.error_off.sum())/sampled.n.sum())
    interval = dict(metric="model MAE minus always-off MAE (W)",
                    estimate=float((daily.error_model.sum()-daily.error_off.sum())/daily.n.sum()),
                    lower_95=float(np.percentile(boot, 2.5)), upper_95=float(np.percentile(boot, 97.5)),
                    resamples=1000, unit="household-day", limitation="Conditional on four homes and September; adjacent days may remain correlated")
    (TABLES / "bootstrap_mae.json").write_text(json.dumps(interval, indent=2))

    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    primary = scores.loc[scores.experiment.eq("chronological") & scores.house.eq("ALL")].set_index("model")
    for ax, metric, label in zip(axes, ["mae_w", "active_mae_w", "rmse_w"], ["All-minute MAE (W)", "Active-minute MAE (W)", "RMSE (W)"]):
        ax.bar(["Always off", "Hour profile", "Model"], primary.loc[list(predictions), metric], color=["#AAB6C3", ORANGE, TEAL])
        ax.set(title=label); ax.tick_params(axis="x", rotation=15)
    fig.suptitle("September holdout | identical eligible minutes for every method", fontweight="bold")
    fig.tight_layout(); save(fig, "05_model_comparison")

    # Objective illustration selection: median-energy eligible active day and two error extremes.
    days = output.groupby(["house", "date"]).agg(energy=("target", "sum"), n=("target", "size"),
                                                  error=("error_model", "mean"))
    active_days = days.loc[(days.energy > 12000) & (days.n >= 720)]
    selected = (active_days.energy-active_days.energy.median()).abs().idxmin()
    false_energy = output.assign(over=(output.gradient_boosting-output.target).clip(lower=0)).groupby(["house", "date"]).over.sum()
    missed_energy = output.assign(under=(output.target-output.gradient_boosting).clip(lower=0)).groupby(["house", "date"]).under.sum()
    examples = [selected, false_energy.idxmax(), missed_energy.idxmax()]
    example_rows = []
    fig, axes = plt.subplots(3, 1, figsize=(13, 10))
    for ax, (house, date), label in zip(axes, examples, ["Representative active day", "Largest accumulated overprediction", "Largest accumulated underprediction"]):
        view = output.loc[output.house.eq(house) & output.date.eq(date)].set_index("time")
        full = pd.date_range(date, date+pd.Timedelta(days=1), freq="1min", inclusive="left")
        view = view.reindex(full)
        ax.plot(view.index, view.target, label="Measured washing machine", color=TEAL, lw=1.2)
        ax.plot(view.index, view.gradient_boosting, label="Model estimate", color=RED, lw=1, alpha=.85)
        ax.set(title=f"{label} | House {house}, {date.date()}", ylabel="Power (W)")
        times(ax)
        error = view.gradient_boosting-view.target
        example_rows.append(dict(label=label, house=house, date=str(date),
                                 excess_kwh=float(error.clip(lower=0).sum()/60000),
                                 missed_kwh=float((-error).clip(lower=0).sum()/60000),
                                 **metrics(view.target.dropna(), view.gradient_boosting[view.target.notna()])))
    axes[0].legend(frameon=False, ncol=2)
    fig.tight_layout(); save(fig, "06_predictions_and_failures")
    pd.DataFrame(example_rows).to_csv(TABLES / "failure_examples.csv", index=False)
    return scores

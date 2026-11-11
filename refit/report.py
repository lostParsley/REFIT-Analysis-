"""Generate the written submission from the actual run artifacts."""
import json
import math
import pandas as pd
from .data import ROOT, TABLES, CONFIG


def table(frame, decimals=3):
    formatted = frame.copy()
    for column in formatted:
        if pd.api.types.is_bool_dtype(formatted[column]):
            formatted[column] = formatted[column].map({True: "Yes", False: "No"})
        elif pd.api.types.is_integer_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda value: f"{value:,}")
        elif pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda value: f"{value:,.{decimals}f}" if math.isfinite(value) else "not scored")
    return formatted.to_markdown(index=False, disable_numparse=True)


def write_reports():
    raw = json.loads((TABLES / "raw_house1_audit.json").read_text())
    summary = pd.read_csv(TABLES / "household_summary.csv")
    scores = pd.read_csv(TABLES / "model_metrics.csv", dtype={"house": str})
    splits = pd.read_csv(TABLES / "split_coverage.csv")
    candidates = pd.read_csv(TABLES / "validation_candidates.csv")
    sensitivity = pd.read_csv(TABLES / "event_sensitivity.csv")
    failures = pd.read_csv(TABLES / "failure_examples.csv")
    rates = pd.read_csv(TABLES / "usage_rates.csv")
    timing_findings = []
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for house in summary.house:
        hourly = rates.loc[rates.house.eq(house) & rates.grouping.eq("hour")]
        weekly = rates.loc[rates.house.eq(house) & rates.grouping.eq("weekday")]
        peak_hour = hourly.loc[hourly.events_per_100_observed_hours.idxmax()]
        peak_day = weekly.loc[weekly.events_per_100_observed_hours.idxmax()]
        timing_findings.append(f"House {house}: highest observed start rate at {int(peak_hour['bin']):02d}:00–{int(peak_hour['bin'])+1:02d}:00 local time and on {weekdays[int(peak_day['bin'])]}.")
    bootstrap = json.loads((TABLES / "bootstrap_mae.json").read_text())
    primary = scores.loc[scores.experiment.eq("chronological") & scores.house.eq("ALL")]
    model = primary.loc[primary.model.eq("gradient_boosting")].iloc[0]
    baseline = primary.loc[primary.model.eq("always_off")].iloc[0]
    household_model = scores.loc[scores.experiment.eq("chronological") & scores.model.eq("gradient_boosting")].set_index("house")
    transfer = scores.loc[scores.experiment.eq("unseen_house5") & scores.house.eq("5")]
    channel_rows = []
    for channel in raw["missing_by_channel"]:
        channel_rows.append(dict(channel=channel, raw_missing=raw["missing_by_channel"][channel],
            negative=raw["negative_by_channel"][channel], above_4000w=raw["over_4000w_iam"].get(channel, "not applied"),
            missing_minutes_before=raw["missing_minutes_before"][channel],
            missing_minutes_after=raw["missing_minutes_after"][channel]))
    inventories = []
    for audit_file in [TABLES / "raw_house1_audit.json"] + sorted(TABLES.glob("clean_house*_audit.json")):
        audit = json.loads(audit_file.read_text())
        for file in audit["files"]:
            inventories.append(dict(file=file["file"].replace("\\", "/"), rows=file["rows"],
                                    first_utc=file["first_utc"], last_utc=file["last_utc"]))
    data = f"""# Data audit and cleaning decisions

## Scope and provenance

The analysis covers **{CONFIG['start']} 00:00 UTC to {CONFIG['end']} 00:00 UTC, exclusive**. Raw House 1 is used only for the cleaning exercise. EDA and model targets use the official cleaned release for Houses 1, 2, 3 and 5. Original power units are watts; the documented nominal cadence is eight seconds, but actual intervals are irregular. Dataset source: University of Strathclyde REFIT, CC BY 4.0; see the references in [README.md](README.md).

The source files actually read have the following full-file coverage. This is broader than the selected analysis window.

{table(pd.DataFrame(inventories))}

Files and SHA-256 hashes are recorded in [source_manifest.json](artifacts/tables/source_manifest.json). Detailed per-house audits are in `artifacts/tables/*_audit.json`.

## Raw House 1: measured findings

| Check in selected window | Finding |
|---|---:|
| Input rows across both raw parts | {raw['selected_rows']:,} |
| Repeated timestamp rows | {raw['duplicate_rows']:,} |
| Backwards steps in concatenated source order | {raw['backwards_steps']:,} |
| Median interval after sorting and deduplicating | {raw['sorted_unique_median_interval_s']:.1f} s |
| Gaps longer than 60 seconds, sorted unique clock | {raw['sorted_unique_gaps_over_60s']:,} |
| Largest sorted unique gap | {raw['sorted_unique_max_gap_s']/3600:.2f} hours |
| Aggregate samples over 20 kW | {raw['aggregate_over_20000w']:,} |
| Maximum raw aggregate | {raw['aggregate_max_w']:.0f} W |
| Interpolated channel-minute cells | {raw['imputed_cells']:,} |

The two raw parts overlap in time, explaining why concatenation must be followed by timestamp reconciliation. The source-order backwards step includes the transition between parts; it should not be interpreted as a meter clock failure. Missing values and extremes below are input-row counts, so overlap contributes to these counts.

{table(pd.DataFrame(channel_rows), 0)}

Unix timestamps parse without failures in the downloaded files (see the audits). Raw printed timestamps differ from their Unix-derived times by zero or one second; cleaned printed timestamps agree with their Unix values. Unix seconds are used consistently. The raw and cleaned clocks are not assumed to align sample-for-sample, and no raw-cleaned label join is performed. Local-hour analysis uses the cleaned clock converted to Europe/London.

## Cleaning algorithm

1. Parse Unix seconds as UTC; report failures. Sort all selected rows by timestamp.
2. Resolve repeated timestamps by per-channel median, skipping missing values. This avoids favouring the row order of overlapping parts; it can average conflicting duplicate values and is not an appliance-remapping correction.
3. Mark negative power and individual appliance readings above 4,000 W as missing. The latter follows the documented IAM sensor ceiling. Large aggregate readings are flagged, not removed using an invented whole-house ceiling.
4. Calculate mean power in left-labelled one-minute bins. For raw data require at least five nonmissing samples per channel. For the official cleaned analysis retain minutes with at least one valid sample and separately record minutes below five samples. This preserves irregularly sampled observations while making sparse-bin sensitivity inspectable. Means are sample-weighted, not exact time integrals; remaining within-minute irregularity is a limitation.
5. **Raw only:** linearly interpolate an entire missing run only if it has at most two minutes and an observed value on each side. Do not partially fill the beginning of a long outage. Leading/trailing gaps and longer runs remain missing. Record imputation counts. Do not interpolate official cleaned model targets.
6. Reindex to the full declared window. Retain missing intervals, quality flags and model-eligibility masks. Per-channel `*_long_gap` flags identify missing runs longer than two minutes; `unresolved_missing` identifies bins still missing after processing. Counts are included in each audit JSON.

![Raw cleaning comparison](output/00_raw_cleaning.png)

**Reading the figure:** among days with at least 20 active washer minutes, the day with the most short-gap repairs is selected deterministically. Blue is the unmodified raw data aggregated to minutes for readability; green is the cleaned signal; orange points identify imputed minutes. Overlap between the lines is expected where readings were already usable. Long missing intervals remain unconnected rather than being presented as zero consumption. The full-period counts above prevent the selected day from substituting for the audit.

## Official cleaned data: availability and limits

{table(summary[['house','channel','total_minutes','missing_wm_minutes','issue_minutes','sparse_minutes','valid_minutes']], 0)}

Here `valid_minutes` means observed washer minutes for EDA, not model eligibility. `issue_minutes` includes publisher-flagged minutes and unavailable flag bins. `sparse_minutes` counts bins with fewer than five aggregate/washer readings. Primary modelling additionally excludes missing targets/aggregate, nonpositive aggregate, publisher `Issues`, and washer power exceeding aggregate. Its coverage is reported separately in RESULTS.md.

EDA retains observed washer readings even when `Issues` is set: that flag concerns the sum of all submeters and does not by itself identify a faulty washer. Model evaluation uses the stricter cohort. This distinction avoids treating every unrelated submeter discrepancy as a washer outage, while explicitly limiting what the evaluation establishes.

The official release has already replaced some long gaps with zeros and filled short ones. Zero and standby proportions cannot distinguish all true inactivity from upstream replacement. No further processing can recover the original missingness from the cleaned file alone. Appliance identities can change; raw House 1 cleaning does not reproduce the publisher's specialised corrections. Aggregate and IAM sensors are also asynchronous, so strict equality checks can exclude genuine overlap situations. The resulting model cohort is selected, not a complete service-quality evaluation.
"""
    (ROOT / "DATA.md").write_text(data, encoding="utf-8")
    perhouse = scores.loc[scores.experiment.eq("chronological") & scores.house.ne("ALL")]
    delta = 100*(baseline.rmse_w-model.rmse_w)/baseline.rmse_w
    sens_range = sensitivity.groupby("house").complete_events.agg(["min", "max"]).reset_index()
    dense = scores.loc[scores.experiment.eq("dense_minutes_sensitivity") & scores.house.eq("ALL")]
    results = f"""# Results: usage, disaggregation and failure analysis

## What the experiment establishes

Four UK homes are observed from April through September 2014. On the eligible September minutes, the selected model has **{model.mae_w:.2f} W MAE**, **{model.rmse_w:.2f} W RMSE**, and **{model.active_mae_w:.2f} W active-minute MAE**. RMSE improves by **{delta:.1f}% relative to always-off**, but all-minute MAE is worse ({model.mae_w:.2f} versus {baseline.mae_w:.2f} W). Activity precision is only **{100*model.precision:.1f}%**, with **{100*model.recall:.1f}% recall**. These are conditional results on the filtered cohort, not accuracy claims for all households or calendar minutes.

**Decision:** retain this as a research prototype. Total energy bias of {model.energy_error_pct:+.1f}% hides cancellation between households: House 1's energy error is {household_model.loc['1','energy_error_pct']:+.1f}% and House 5's is {household_model.loc['5','energy_error_pct']:+.1f}%. The better aggregate energy total does not establish accurate individual customer feedback. No model changes were made in response to the final test scores.

## 1. Washing-machine use

House 1 uses Appliance5, House 2 Appliance2, House 3 Appliance6 and House 5 Appliance3. Units are watts; analyses use one-minute means. All period boundaries are stated in DATA.md.

{table(summary[['house','valid_days_equivalent','zero_pct','off_pct','candidate_events','complete_events','events_per_30_observed_days','median_duration_min','median_energy_kwh']])}

`zero_pct` is exactly zero; `off_pct` is at or below 20 W. Denominators use observed washer minutes. Equivalent days are observed minutes divided by 1,440, not a count of complete days. Detected-event rates remain vulnerable to outages and censored events and are not unbiased estimates of washing frequency.

**Event rule:** start with minutes above {CONFIG['activity_threshold_w']} W; join active periods separated by at most {CONFIG['cycle_pause_minutes']} observed off minutes; require at least {CONFIG['cycle_minimum_minutes']} elapsed minutes and {CONFIG['cycle_minimum_kwh']} kWh. Never join across missing minutes. An event without a full observed {CONFIG['cycle_pause_minutes']}-minute buffer on each side is labelled censored. Duration and energy comparisons use complete events only. Energy is the sum of one-minute mean watts divided by 60,000, including observed pauses within the event. This heuristic can split long soak phases or merge closely spaced uses; events are not independently verified cycles.

![Representative 24-hour trace](output/01_daily_trace.png)

**Interpretation:** the aggregate contains other household loads as well as the washer. A washer activation is not uniquely identifiable from the height of a household power peak. The example day contains a training-period event closest to the overall median event energy; it was not selected for a favourable model prediction.

![Detected events](output/02_detected_cycles.png)

**Interpretation:** shaded intervals show the event grouping, and the dashed line marks the activity threshold. Within-cycle pauses explain why a single threshold crossing should not be counted as a complete wash. Examples are nearest to each house's median training-event energy.

![Cross-house comparison](output/03_house_comparison.png)

**Interpretation:** distributions, rather than only averages, show variation between detected events and homes. Extreme points are omitted from the boxplot display for readability, not deleted from the event table. These differences cannot identify efficiency without information about programme, load size and appliance use.

House 2 has a median detected duration of {summary.loc[summary.house.eq(2), 'median_duration_min'].iloc[0]:.0f} minutes and median event energy of {summary.loc[summary.house.eq(2), 'median_energy_kwh'].iloc[0]:.2f} kWh, compared with {summary.loc[summary.house.eq(1), 'median_duration_min'].iloc[0]:.0f} minutes and {summary.loc[summary.house.eq(1), 'median_energy_kwh'].iloc[0]:.2f} kWh in House 1. That is a difference in observed programmes/events, not evidence that one household is wasteful.

![Usage timing](output/04_usage_patterns.png)

**Interpretation:** starts are expressed per 100 observed hours within each hour/day category, preventing different observation coverage from masquerading as different usage intensity. Local time is Europe/London. These are event-start patterns, not the fraction of electricity used at each time.

{' '.join(timing_findings)} These are descriptive peaks from a small household sample; no statistical significance or universal washing schedule is implied.

### Sensitivity of cycle counts

Thresholds 10, 20 and 50 W are crossed with pause allowances 5, 10 and 15 minutes. The resulting range of complete-event counts is:

{table(sens_range, 0)}

The full grid is in [event_sensitivity.csv](artifacts/tables/event_sensitivity.csv). Variation is evidence that the counts depend on the rule; it is not a confidence interval. No rule is tuned to maximise test performance.

## 2. Validation design

Train on April–July, compare two candidate losses in August, and evaluate once on September. All four homes appear in the primary chronological experiment. A separate model uses only Houses 1, 2 and 3 during both training and validation, then predicts September in unseen House 5.

{table(splits, 0)}

Features are current aggregate power; lags of 1, 2, 5, 10, 15, 30 and 60 minutes; 5/15/30/60-minute rolling mean, standard deviation, minimum and maximum; one-minute change; and current power above the past-hour minimum. All are causal. Each split builds its own history. A complete 61-minute aggregate context is required, and missing targets are never imputed. Target/quality exclusions apply at the predicted minute, not to every historical washer reading.

The feature matrix includes no appliance signals, target-derived cycles, house identity or calendar cues. The model is histogram gradient boosting with 180 iterations, 31 leaves, learning rate 0.08, minimum leaf size 40 and L2 regularisation 10. Squared-error and Poisson losses are compared using macro-averaged household RMSE on validation. A fixed seed and no internal random early-stopping split make the procedure reproducible. Predictions are clipped to zero through current aggregate power. The selected model is not refit after validation.

{table(candidates[['experiment','loss','macro_rmse_w','status','selected']])}

Candidates producing numerical runtime warnings or nonfinite validation predictions are rejected before selection; clipping is never used to conceal an unstable candidate.

Baselines are **always-off** and **house/hour mean washer power learned on training only**. The profile receives house and local-hour information explicitly as a benchmark. No target labels from validation or test enter it.

## 3. September test performance

{table(primary[['model','n_minutes','mae_w','rmse_w','active_mae_w','precision','recall','f1']])}

Energy on the same eligible minutes:

{table(primary[['model','actual_kwh','predicted_kwh','energy_error_pct','daily_energy_mae_kwh']])}

- **MAE:** typical absolute power error over all eligible minutes. Low values can conceal missed activity because off minutes dominate.
- **RMSE:** penalises large power errors; validation selection uses the equal-house average.
- **Active MAE:** error only where measured washer power exceeds 20 W, exposing always-off failure.
- **Precision/recall/F1:** minute-level activity at the same 20 W threshold, not event matching. False-positive behaviour is visible through precision.
- **Energy error:** signed relative bias over exactly the eligible minutes, not a complete-month bill estimate. Positive means overprediction.
- **Daily energy MAE:** absolute error in each observed household-day's eligible energy. This prevents cancellation between different days, but partial days remain partial.

![Baseline comparison](output/05_model_comparison.png)

**Interpretation:** compare all-minute error with active-minute error before claiming success. A model may improve large-load reconstruction while worsening typical-minute error or producing false positives. No single metric is sufficient for a utility decision.

Here that trade-off is visible: active-minute MAE falls from {baseline.active_mae_w:.1f} to {model.active_mae_w:.1f} W, but overall MAE rises by {model.mae_w-baseline.mae_w:.2f} W. Daily eligible-energy MAE falls from {baseline.daily_energy_mae_kwh:.3f} to {model.daily_energy_mae_kwh:.3f} kWh. The model is useful for studying load reconstruction, but its low activity precision would create too many unreliable customer alerts at this threshold.

### Results by household

{table(perhouse[['house','model','mae_w','rmse_w','active_mae_w','f1','energy_error_pct']])}

The paired household-day bootstrap estimates model-minus-always-off MAE at **{bootstrap['estimate']:+.2f} W**, with a 95% percentile interval **[{bootstrap['lower_95']:+.2f}, {bootstrap['upper_95']:+.2f}] W**, using 1,000 within-house day resamples. Negative favours the model. This describes uncertainty conditional on the observed four homes and September; adjacent days may remain correlated and household population uncertainty is not represented.

### Sparse-minute sensitivity

Restrict evaluation to minutes with at least five readings in both target and aggregate, leaving the fitted model unchanged:

{table(dense[['model','n_minutes','mae_w','rmse_w','active_mae_w','f1','energy_error_pct']])}

This tests the effect of sparse target bins; it does not certify the quality of every minute in the preceding feature window. The initial data audit showed that enforcing five readings throughout every 61-minute history discarded most activity, so sparse bins are retained with disclosure rather than silently interpreted as outages.

### Unseen-house diagnostic

{table(transfer[['model','n_minutes','mae_w','rmse_w','active_mae_w','f1','energy_error_pct']])}

House 5 is never used to fit or choose this transfer model. Compare with the primary House 5 result above. A single held-out house is a diagnostic, not a cross-house benchmark. Neither experiment establishes India transfer.

## 4. Predictions and concrete failure cases

![Held-out predictions and failures](output/06_predictions_and_failures.png)

{table(failures[['label','house','date','actual_kwh','predicted_kwh','excess_kwh','missed_kwh']])}

The first panel is a median-energy eligible active test day. The remaining panels deliberately show the greatest accumulated overprediction and underprediction in held-out household-days. `excess_kwh` sums positive minute errors and `missed_kwh` sums negative minute errors in magnitude, before cancellation; their difference is the net energy error. These examples are selected for diagnosis after scoring, not for tuning. Plot gaps indicate excluded minutes.

**False activation / overestimated load:** other appliances can resemble washer heating or motor operation. The largest overprediction example makes this ambiguity visible; without inspecting competing submeters, the exact appliance causing a peak cannot be asserted.

**Missed or underestimated activity:** low-power phases can be buried in aggregate variation, and learned average power can smooth short heating peaks. The largest underprediction day shows the cost in energy. Different machines and programmes can produce different patterns even for the same appliance class.

The House 5 failure also contains a long, almost constant measured target plateau. It should not automatically be interpreted as a real uninterrupted wash: a persistent appliance state or upstream data filling could contribute. Raw-channel inspection or independent event labels would be needed to distinguish these possibilities. This example exposes uncertainty in both the estimate and its reference labels.

## 5. Limits and next experiment

Labels inherit upstream filling and zero replacement. Missingness and quality exclusions can be related to appliance activity, so coverage filtering can bias evaluation. Household differences, a single season/window, heuristic cycle boundaries, and no independent cycle labels limit interpretation. Bootstrap intervals do not resolve these issues. The next priority is raw-to-clean label auditing and manually reviewed event labels across more homes, followed by leave-one-home-out evaluation and an intervention pilot. Recommendations and the 15/30-minute discussion are in [Recommendation.md](Recommendation.md).

All figures derive from REFIT measurements, credited to Murray, Stankovic and Stankovic / University of Strathclyde, CC BY 4.0. See [README.md](README.md) for sources and AI assistance disclosure.
"""
    (ROOT / "RESULTS.md").write_text(results, encoding="utf-8")
    recommendation = f"""# Recommendation to Flock Energy

**Use this prototype to investigate household washing patterns; require further validation before individual customer claims or automated control.**

The case study analyses four REFIT homes at one-minute resolution. On filtered September observations, the model reduces RMSE by {delta:.1f}% versus always-off, but worsens overall MAE and achieves only {100*model.precision:.1f}% activity precision. Aggregate energy bias of {model.energy_error_pct:+.1f}% hides large opposing errors across homes. Missing/flagged intervals are excluded, so scores do not represent complete monthly bills. Event characteristics differ across homes; load size, temperature and programme are unknown.

**Opportunity — opt-in feedback on unusually energy-intensive washing events.** Use a household's own reviewed baseline to identify repeated high-energy events and invite the customer to check whether a lower-temperature or eco programme is suitable. This is a hypothesis for reducing energy, not a demonstrated saving. Do not label a single event inefficient or compare homes as if their laundry needs were equal. Start with a small volunteer panel with washer submeters to verify event attribution; offer practical advice only where the evidence is credible.

**Measure whether it works.** Pre-register an energy outcome and minimum worthwhile effect, estimate the sample size from baseline variation, then randomise eligible volunteers to feedback or usual service. Compare change in measured weekly washer kWh between groups, reporting uncertainty, retention and missing-data rates. Also track verified event count, kWh per event, false alerts and whether washing tasks were merely deferred. Programme/load information helps interpret changes. Use intention-to-treat analysis and independent submeter measurements during the pilot. A shift to cheaper hours may reduce cost under a time-varying tariff; it is not automatically a kWh saving.

**Suitable uses and limits.** Exploratory load research and quality-controlled, uncertainty-aware household summaries are plausible uses. Current evidence does not justify appliance-level billing, guaranteed savings, fault diagnosis or autonomous switching. Other appliances overlap with washer signatures; missing and upstream zero-filled readings distort activity; and household/appliance differences limit transfer. The held-out-house diagnostic is only one home. UK results cannot be assumed to hold in India: machine types, water-heating arrangements, wash practices, supply interruptions and meter characteristics need locally representative validation before deployment.

**If only 15- or 30-minute data were available:** averaging would blend heater bursts, pauses and other appliances into a few points per wash. Event boundaries and appliance separation would become substantially less identifiable, and different appliance combinations could produce the same interval mean. The model would need retraining at the actual meter resolution and evaluation of interval energy rather than minute-level activity. Interpolating coarse values cannot restore lost signatures. Broader daily/weekly consumption feedback may remain useful, with wider uncertainty and fewer appliance-specific claims.

Source: REFIT, University of Strathclyde, CC BY 4.0. Supporting evidence: [RESULTS.md](RESULTS.md); processing and coverage: [DATA.md](DATA.md).
"""
    (ROOT / "Recommendation.md").write_text(recommendation, encoding="utf-8")

import numpy as np
import pandas as pd
from refit.core import fill_short_gaps, minute_data, cycles, features, metrics


def series(values):
    return pd.Series(values, index=pd.date_range("2014-01-01", periods=len(values), freq="1min", tz="UTC"), dtype=float)


def test_gap_policy_never_partially_fills_long_outage_or_edges():
    source = series([np.nan, 1, np.nan, np.nan, 4, np.nan, np.nan, np.nan, 8, np.nan])
    result = fill_short_gaps(source)
    np.testing.assert_allclose(result.iloc[1:5], [1, 2, 3, 4])
    assert result.iloc[[0, 5, 6, 7, 9]].isna().all()


def test_resampling_duplicate_median_and_sensor_ceiling():
    index = pd.to_datetime(["2014-01-01 00:00:00", "2014-01-01 00:00:00", "2014-01-01 00:00:08", "2014-01-01 00:01:00"], utc=True)
    frame = pd.DataFrame({"Aggregate": [100, 300, 200, 6000], "Appliance1": [20, 40, 50, 5000]}, index=index)
    output, _, _ = minute_data(frame, minimum_samples=1)
    assert output.Aggregate.iloc[0] == 200
    assert output.Appliance1.iloc[0] == 40
    assert output.Aggregate.iloc[1] == 6000
    assert pd.isna(output.Appliance1.iloc[1])


def test_insufficient_minute_is_missing_not_zero():
    index = pd.date_range("2014-01-01", periods=3, freq="8s", tz="UTC")
    result, _, _ = minute_data(pd.DataFrame({"Aggregate": 100}, index=index), minimum_samples=5)
    assert result.Aggregate.isna().all()


def test_long_outage_has_an_explicit_quality_flag():
    index = pd.to_datetime(["2014-01-01 00:00", "2014-01-01 00:05"], utc=True)
    output, flags, _ = minute_data(pd.DataFrame({"Aggregate": [100, 200]}, index=index), minimum_samples=1, raw=True)
    assert output.Aggregate.iloc[1:5].isna().all()
    assert flags.Aggregate_long_gap.iloc[1:5].all()
    assert not flags.Aggregate_long_gap.iloc[[0, 5]].any()


def test_event_bridges_observed_pause_but_not_outage():
    source = series([0]*15+[100]*12+[0]*3+[100]*12+[0]*15)
    event = cycles(source)
    assert len(event) == 1
    assert event.duration_min.iloc[0] == 27
    assert np.isclose(event.energy_kwh.iloc[0], 2400/60000)
    source.iloc[28] = np.nan
    split = cycles(source)
    assert len(split) == 2
    assert split.censored.all()


def test_edge_event_is_censored():
    event = cycles(series([100]*20+[0]*15))
    assert event.censored.iloc[0]


def test_features_are_causal_and_reject_whole_missing_context():
    source = series(np.arange(200))
    original = features(source)
    changed = source.copy()
    changed.iloc[150:] = 10000
    pd.testing.assert_frame_equal(original.iloc[:150], features(changed).iloc[:150])
    source.iloc[100] = np.nan
    transformed = features(source)
    assert transformed.iloc[100:161].isna().all().all()
    assert transformed.iloc[161].notna().all()


def test_metrics_show_always_off_failure_despite_low_overall_mae():
    result = metrics([0, 0, 0, 1000], [0, 0, 0, 0])
    assert result["mae_w"] == 250
    assert result["active_mae_w"] == 1000
    assert result["recall"] == 0
    assert result["energy_error_pct"] == -100


def test_one_minute_power_to_energy_units():
    result = metrics([1000]*60, [500]*60)
    assert result["actual_kwh"] == 1
    assert result["predicted_kwh"] == .5

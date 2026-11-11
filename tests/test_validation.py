"""Guard the train/validation boundary against accidental context leakage."""
import numpy as np
import pandas as pd
import warnings
from refit import model


def test_split_histories_reset_and_do_not_require_historical_target_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "TABLES", tmp_path)
    monkeypatch.setattr(model, "CONFIG", {**model.CONFIG, "start": "2014-01-01", "train_end": "2014-01-02",
                                        "validation_end": "2014-01-03", "end": "2014-01-04"})
    index = pd.date_range("2014-01-01", "2014-01-04", freq="1min", inclusive="left", tz="UTC")
    frame = pd.DataFrame({"Aggregate": 500., "washing_machine": 50., "valid": True,
                          "issues": False, "low_sample_count": False}, index=index)
    frame.loc[pd.Timestamp("2014-01-02 02:00", tz="UTC"), "valid"] = False
    result = model.split_frames({"1": frame})
    for name, day in [("train", 1), ("validation", 2), ("test", 3)]:
        assert result[name].time.min() == pd.Timestamp(f"2014-01-0{day} 01:00", tz="UTC")
    validation_times = set(result["validation"].time)
    assert pd.Timestamp("2014-01-02 02:00", tz="UTC") not in validation_times
    assert pd.Timestamp("2014-01-02 02:01", tz="UTC") in validation_times
    changed = frame.copy()
    changed.loc[changed.index >= pd.Timestamp("2014-01-03", tz="UTC"), "Aggregate"] = 9000
    rerun = model.split_frames({"1": changed})
    pd.testing.assert_frame_equal(result["train"], rerun["train"])
    pd.testing.assert_frame_equal(result["validation"], rerun["validation"])


def test_overflow_candidate_cannot_be_hidden_by_prediction_clipping(monkeypatch):
    class Candidate:
        def __init__(self, loss, **kwargs):
            self.loss = loss

        def fit(self, x, y):
            if self.loss == "poisson":
                warnings.warn("overflow encountered in exp", RuntimeWarning)
            return self

        def predict(self, x):
            return np.zeros(len(x))

    monkeypatch.setattr(model, "HistGradientBoostingRegressor", Candidate)
    data = pd.DataFrame({"power": [100., 200.], "target": [0., 100.], "house": ["1", "1"]})
    fitted, records, selected = model.fit_candidates(data, data, ["power"], "test")
    assert selected == "squared_error"
    assert records[1]["status"] == "rejected: numerical instability"
    assert not records[1]["selected"]


def test_evaluation_pairs_filtered_predictions_by_position_not_old_index():
    frame = pd.DataFrame({"target": [100., 200.], "house": ["1", "2"],
                          "time": pd.to_datetime(["2014-01-01", "2014-01-01"], utc=True)}, index=[10, 30])
    prediction = pd.Series([100., 200.], index=[10, 30])
    result = model.evaluate(frame, "test", prediction, "test")
    assert all(row["mae_w"] == 0 for row in result)
    assert result[0]["n_minutes"] == 2

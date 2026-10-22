"""Synthetic clocks and physiology only; no participant fixtures are included."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import experiment as ex
import workbench as wb


def file(phase, *, waves=(1300, 1400, 1500), times=None, name=None):
    times = [0, 1, 2] if times is None else times
    frame = pd.DataFrame({"sample_id": ["same"] * len(times), "Time": times,
                          **{str(w): np.arange(len(times), dtype=float) * (i + 1) + i for i, w in enumerate(waves)}})
    return {"phase": phase, "name": name or f"synthetic_{phase}.csv", "data": frame.to_csv(index=False).encode()}


def merged(times=None):
    return ex.merge_phase_files([file("Task", times=times)])[0]


def unity(times=None):
    times = np.arange(0, 4.01, 0.1) if times is None else np.asarray(times, dtype=float)
    frame = pd.DataFrame({"Time": times})
    for eye in ("Left", "Right"):
        frame[f"{eye}_Pupil_Diameter"] = 2 + times
        frame[f"{eye}_Openness"] = 1.0
        frame[f"{eye}_Gaze_Direction_x"] = 0.0
        frame[f"{eye}_Gaze_Direction_y"] = 0.0
        frame[f"{eye}_Gaze_Direction_z"] = 1.0
    return frame


def config(**kwargs):
    return {"spectraTimeMode": "column", "spectraTimeColumn": "Time", "spectraTimeUnit": "seconds",
            "windowSeconds": 1, "minCoverage": 0.5, **kwargs}


def sync(spectra=None, log=None, **kwargs):
    return ex.synchronize_experiment(merged([1, 2, 3]) if spectra is None else spectra,
                                     unity() if log is None else log, config(**kwargs))


def test_merge_keeps_spectra_and_assigns_unique_ids():
    result, summary = ex.merge_phase_files([file("Recovery"), file("Baseline"), file("Task")])
    assert len(result) == 9
    assert result["experiment_sample_id"].is_unique
    assert result["experiment_original_id"].eq("same").all()
    assert result["experiment_phase"].tolist() == ["Recovery"] * 3 + ["Baseline"] * 3 + ["Task"] * 3
    assert result["experiment_source_row"].tolist() == [2, 3, 4] * 3
    assert summary["suggestedId"] == "experiment_sample_id"
    assert summary["suggestedGroup"] == "experiment_phase"
    assert summary["experiment"]["phases"] == ["Baseline", "Task", "Recovery"]
    assert np.all(result["1400"].to_numpy() == [1, 3, 5] * 3)


def test_merge_canonicalizes_equal_wavelength_labels():
    first, second = file("Baseline"), file("Task", waves=(1500, 1400, 1300))
    d = pd.read_csv(__import__("io").BytesIO(second["data"]))
    d.rename(columns={"1300": "wl_1300", "1400": "wl_1400", "1500": "wl_1500"}, inplace=True)
    second["data"] = d.to_csv(index=False).encode()
    result, _ = ex.merge_phase_files([first, second])
    assert len([c for c in result if wb.parse_wavelength(c)]) == 3
    assert result["1300"].tolist() == [0, 1, 2, 2, 5, 8]


@pytest.mark.parametrize("items,match", [
    ([], "1〜30"), ([file("Wrong")], "フェーズ"),
    ([file("Task"), file("Recovery", waves=(1300, 1400, 1600))], "波長が一致"),
    ([file("Task", waves=(1300, 1300, 1500))], "3列以上"),
])
def test_bad_merge_is_atomic(items, match):
    with pytest.raises(ValueError, match=match):
        ex.merge_phase_files(items)


def test_reserved_metadata_does_not_get_overwritten():
    item = file("Task")
    frame = pd.read_csv(__import__("io").BytesIO(item["data"]))
    frame["experiment_phase"] = "original"
    item["data"] = frame.to_csv(index=False).encode()
    with pytest.raises(ValueError, match="予約"):
        ex.merge_phase_files([item])


def test_detect_datetime_precision_and_phase_anchor():
    frame, summary = ex.merge_phase_files([file("Baseline", times=["2026/1/1 10:00"] * 3),
                                          file("Task", times=["2026/1/1 10:02:00", "2026/1/1 10:02:01", "2026/1/1 10:02:02"])])
    time = summary["experiment"]["timeColumns"][0]
    assert time["kind"] == "datetime"
    assert time["minutePrecisionRows"] == 3
    assert summary["experiment"]["warnings"]
    assert summary["experiment"]["phaseTimeAnchors"][1]["phase"] == "Task"
    assert summary["experiment"]["phaseTimeAnchors"][1]["value"] == "2026/1/1 10:02:00"
    assert frame["Time"].nunique() == 4


def test_unity_inspection_and_no_source_mutation():
    source = unity()
    source.loc[2, "Left_Pupil_Diameter"] = -1
    original = source.copy(deep=True)
    _, summary = ex.inspect_unity_bytes(source.to_csv(index=False).encode(), "artificial_Unity.csv")
    assert summary["suggestedTimeColumn"] == "Time"
    assert summary["metricColumns"]["left"]["gazeDirection"]
    sync(log=source)
    pd.testing.assert_frame_equal(source, original)


def test_half_open_window_and_exact_frame_mean():
    result = sync()
    row = result["rows"][0]
    selected = unity().query("Time >= 0.5 and Time < 1.5")
    assert row["unitySamples"] == len(selected) == 10
    assert row["coverage"] == pytest.approx(1)
    assert row["metrics"]["pupil_mean"] == pytest.approx(selected["Left_Pupil_Diameter"].mean())
    assert row["metrics"]["gaze_dispersion_deg"] == pytest.approx(0)
    assert row["metrics"]["blink_count"] == 0
    assert result["phaseSummaries"][0]["matchedSpectra"] == 3


def test_floating_point_spacing_at_gap_threshold_remains_supported():
    result = sync(maxGapSeconds=0.1)
    assert all(row["coverage"] == pytest.approx(1) for row in result["rows"])


def test_missing_tracking_values_not_used_as_physiology():
    log = unity()
    mask = (log.Time >= 0.5) & (log.Time < 1.5)
    log.loc[mask, "Left_Pupil_Diameter"] = -1
    for axis in "xyz":
        log.loc[mask, f"Left_Gaze_Direction_{axis}"] = 0
    result = sync(log=log)
    metrics = result["rows"][0]["metrics"]
    assert metrics["pupil_left_mean"] is None
    assert metrics["pupil_mean"] == pytest.approx(log.loc[mask, "Right_Pupil_Diameter"].mean())
    assert metrics["pupil_valid_fraction"] == 0.5
    assert metrics["gaze_valid_fraction"] == 0.5
    assert metrics["gaze_left_dispersion_deg"] is None


def test_long_recording_gap_is_not_interpolated():
    log = unity([0, 0.1, 0.2, 1.8, 1.9, 2.0])
    result = sync(spectra=merged([0.1, 1, 1.9]), log=log, windowSeconds=1, minCoverage=0.5)
    assert not any(r["valid"] for r in result["rows"])
    assert result["rows"][1]["unitySamples"] == 0
    assert result["rows"][1]["coverage"] == 0


def test_no_overlap_is_visible_by_phase():
    spectra, _ = ex.merge_phase_files([file("Baseline", times=[-10, -9, -8]), file("Task", times=[1, 2, 3]), file("Recovery", times=[20, 21, 22])])
    result = sync(spectra=spectra)
    assert [p["matchedSpectra"] for p in result["phaseSummaries"]] == [0, 3, 0]
    assert all(r["metrics"]["pupil_mean"] is None for r in result["rows"] if r["phase"] != "Task")
    assert any("6/9" in warning for warning in result["warnings"])


def test_boundary_window_has_partial_coverage():
    result = sync(spectra=merged([0, 2, 4]), minCoverage=0.75)
    assert result["rows"][0]["coverage"] == pytest.approx(0.5)
    assert result["rows"][2]["coverage"] == pytest.approx(0.5)
    assert [r["valid"] for r in result["rows"]] == [False, True, False]


def test_datetime_requires_explicit_session_anchor():
    spectra = merged(["2026/1/1 10:00:01", "2026/1/1 10:00:02", "2026/1/1 10:00:03"])
    with pytest.raises(ValueError, match="開始日時"):
        sync(spectra=spectra, spectraTimeUnit="datetime")
    result = sync(spectra=spectra, spectraTimeUnit="datetime", unityStartTime="2026-01-01T10:00:00", anchorConfirmation="user-confirmed-task-first")
    assert [r["timeSeconds"] for r in result["rows"]] == [1, 2, 3]
    assert result["provenance"]["anchorConfirmation"] == "user-confirmed-task-first"
    assert result["provenance"]["alignmentAutomaticallyVerified"] is False


def test_explicit_offset_and_milliseconds():
    spectra = merged([1000, 2000, 3000])
    result = sync(spectra=spectra, spectraTimeUnit="milliseconds", timeOffsetSeconds=-1)
    assert [r["timeSeconds"] for r in result["rows"]] == [0, 1, 2]


def test_manual_phase_clock_uses_order_without_stretching():
    spectra, _ = ex.merge_phase_files([file("Task", times=["bad"] * 3), file("Baseline", times=["bad"] * 3)])
    result = sync(spectra=spectra, spectraTimeMode="manual", manualPhases={"Task": {"startSeconds": 1, "intervalSeconds": 1}, "Baseline": {"startSeconds": -10, "intervalSeconds": 2}})
    assert [r["timeSeconds"] for r in result["rows"]] == [1, 2, 3, -10, -8, -6]
    assert [r["valid"] for r in result["rows"]] == [True, True, True, False, False, False]
    with pytest.raises(ValueError, match="Baseline"):
        sync(spectra=spectra, spectraTimeMode="manual", manualPhases={"Task": {"startSeconds": 1, "intervalSeconds": 1}})


@pytest.mark.parametrize("times", [[0, 0, 1], [0, 2, 1], [0, np.nan, 1]])
def test_invalid_unity_clocks_rejected(times):
    with pytest.raises(ValueError, match="時刻"):
        sync(log=unity(times))


def test_bilateral_blink_candidates_and_midpoint_boundaries():
    log = unity()
    log.loc[(log.Time >= 0.8) & (log.Time <= 1.0), ["Left_Openness", "Right_Openness"]] = 0.1
    # A unilateral closure is not a binocular candidate.
    log.loc[(log.Time >= 1.8) & (log.Time <= 2.0), "Left_Openness"] = 0.1
    result = sync(log=log)
    assert len(result["blinkEvents"]) == 1
    candidate = result["blinkEvents"][0]
    assert candidate["startSeconds"] == pytest.approx(0.75)
    assert candidate["endSeconds"] == pytest.approx(1.05)
    assert candidate["durationSeconds"] == pytest.approx(0.3)
    assert result["rows"][0]["metrics"]["blink_count"] == 1
    assert result["rows"][0]["metrics"]["blink_rate_per_min"] == pytest.approx(60)


def test_blink_duration_and_missing_boundary_reject_incomplete_events():
    log = unity()
    log.loc[log.Time < 0.3, ["Left_Openness", "Right_Openness"]] = 0
    log.loc[log.Time > 3.8, ["Left_Openness", "Right_Openness"]] = 0
    log.loc[(log.Time >= 1.5) & (log.Time <= 2.6), ["Left_Openness", "Right_Openness"]] = 0
    assert sync(log=log)["blinkEvents"] == []
    log = unity()
    log.loc[(log.Time >= 0.8) & (log.Time <= 1.0), ["Left_Openness", "Right_Openness"]] = 0
    # Explicit index avoids floating point equality ambiguity.
    log.loc[7, "Right_Openness"] = np.nan
    assert sync(log=log)["blinkEvents"] == []


def test_candidate_does_not_cross_missing_recording_gap():
    log = unity([0, .1, .2, 1.8, 1.9, 2])
    log.loc[[1, 2, 3, 4], ["Left_Openness", "Right_Openness"]] = .1
    assert sync(log=log, blinkMaxSeconds=3)["blinkEvents"] == []


def test_missing_openness_exposure_does_not_become_zero_blinks():
    log = unity()
    log.loc[(log.Time >= 0.6) & (log.Time < 1.4), ["Left_Openness", "Right_Openness"]] = np.nan
    row = sync(log=log)["rows"][0]
    assert row["valid"]  # Other physiology can still be observed.
    assert row["metrics"]["openness_observed_seconds"] < 0.5
    assert row["metrics"]["blink_count"] is None
    assert row["metrics"]["blink_rate_per_min"] is None


def test_candidate_rate_uses_valid_openness_exposure():
    log = unity()
    log.loc[[8, 9, 10], ["Left_Openness", "Right_Openness"]] = .1
    log.loc[[12], ["Left_Openness", "Right_Openness"]] = np.nan
    row = sync(log=log)["rows"][0]
    assert row["metrics"]["blink_count"] == 1
    assert row["metrics"]["openness_observed_seconds"] == pytest.approx(0.8)
    assert row["metrics"]["blink_rate_per_min"] == pytest.approx(75)


def test_angular_dispersion_normalizes_vectors_and_is_geometrically_defined():
    log = unity()
    angle = np.deg2rad(10)
    for eye, sign in [("Left", 1), ("Right", -1)]:
        log[f"{eye}_Gaze_Direction_x"] = sign * np.sin(angle) * 3
        log[f"{eye}_Gaze_Direction_z"] = np.cos(angle) * 3
    metrics = sync(log=log)["rows"][0]["metrics"]
    assert metrics["gaze_dispersion_deg"] == pytest.approx(10)
    assert metrics["gaze_left_dispersion_deg"] == pytest.approx(0, abs=1e-5)


def test_datetime_clocks_respect_explicit_utc_offsets():
    spectra = merged(["2026-01-01T19:00:01+09:00", "2026-01-01T19:00:02+09:00", "2026-01-01T19:00:03+09:00"])
    result = sync(spectra=spectra, spectraTimeUnit="datetime", unityStartTime="2026-01-01T10:00:00Z")
    assert [r["timeSeconds"] for r in result["rows"]] == [1, 2, 3]
    log = unity()
    log["Time"] = [pd.Timestamp("2026-01-01T10:00:00Z") + pd.Timedelta(seconds=t) for t in log.Time]
    result = sync(spectra=spectra, log=log, spectraTimeUnit="datetime", unityTimeUnit="datetime")
    assert [r["timeSeconds"] for r in result["rows"]] == [1, 2, 3]


@pytest.mark.parametrize("datetime_unit", ["ns", "us", "ms"])
def test_clock_alignment_is_independent_of_pandas_datetime_storage_unit(monkeypatch, datetime_unit):
    # pandas 3 (including Pyodide) may infer datetime64[us] from second-precision
    # strings, while pandas 2 commonly uses ns. Raw integer values have different
    # scales, so comparing two native-only ns paths would miss a 1000x clock bug.
    original = pd.to_datetime

    def parsed_with_resolution(*args, **kwargs):
        parsed = original(*args, **kwargs)
        assert isinstance(parsed, pd.Series)
        return parsed.dt.as_unit(datetime_unit)

    monkeypatch.setattr(pd, "to_datetime", parsed_with_resolution)
    spectra = merged(["2026/1/1 10:00:01", "2026/1/1 10:00:06", "2026/1/1 10:00:11"])
    result = sync(spectra=spectra, log=unity(np.arange(0, 13, .1)), spectraTimeUnit="datetime", unityStartTime="2026/1/1 10:00:00")
    assert [row["timeSeconds"] for row in result["rows"]] == [1, 6, 11]
    assert [row["valid"] for row in result["rows"]] == [True, True, True]
    assert [row["unitySamples"] for row in result["rows"]] == [10, 10, 10]
    log = unity(np.arange(0, 13, .1))
    log["Time"] = [pd.Timestamp("2026-01-01T10:00:00Z") + pd.Timedelta(seconds=t) for t in log.Time]
    result = sync(spectra=spectra, log=log, spectraTimeUnit="datetime", unityTimeUnit="datetime")
    assert [r["timeSeconds"] for r in result["rows"]] == [1, 6, 11]


def test_duplicate_minute_timestamps_remain_duplicated_and_warned():
    spectra = merged(["2026/1/1 10:00"] * 3)
    result = sync(spectra=spectra, spectraTimeUnit="datetime", unityStartTime="2026/1/1 10:00:00")
    assert [r["timeSeconds"] for r in result["rows"]] == [0, 0, 0]
    assert any("重複" in warning for warning in result["warnings"])


def test_correlations_use_processed_spectra_and_matching_ids_only():
    spectra = merged([1, 2, 3])
    ids = spectra["experiment_sample_id"].tolist()
    analysis = {"pca": {"ids": ids, "scores": [[-1, 2], [0, 2], [1, 2]]},
                "spectra": {"ids": ids, "processed": [[5, 2, 7], [3, 4, 7], [1, 6, 7]], "wavelengths": [1300, 1400, 1500]}}
    result = ex.synchronize_experiment(spectra, unity(), config(), analysis)
    pupil = next(c for c in result["correlations"] if c["metric"] == "pupil_mean")
    assert [r["r"] for r in pupil["pca"]] == pytest.approx([1, None], nan_ok=True)
    assert pupil["spectra"][0]["r"] == pytest.approx(-1)
    assert pupil["spectra"][1]["r"] == pytest.approx(1)
    assert pupil["spectra"][2]["r"] is None
    assert pupil["pca"][0]["n"] == 3
    analysis["pca"]["ids"] = ids[::-1]
    with pytest.raises(ValueError, match="試料"):
        ex.synchronize_experiment(spectra, unity(), config(), analysis)


@pytest.mark.parametrize("id_column", [None, "custom_unique_id"])
def test_analysis_selected_id_column_is_retained_for_matching(id_column):
    spectra = merged([1, 2, 3])
    spectra["custom_unique_id"] = ["ART-A", "ART-B", "ART-C"]
    ids = wb._labels(spectra, id_column, "試料ID")
    analysis = {"metadata": {"settings": {"idColumn": id_column}},
                "pca": {"ids": ids, "scores": [[-1], [0], [1]]},
                "spectra": {"ids": ids, "processed": [[1, 2, 3], [2, 3, 4], [3, 4, 5]], "wavelengths": [1300, 1400, 1500]}}
    result = ex.synchronize_experiment(spectra, unity(), config(), analysis)
    assert [r["id"] for r in result["rows"]] == ids
    assert result["correlations"][0]["pca"][0]["n"] == 3
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("defect", ["shape", "nonfinite", "format"])
def test_malformed_analysis_is_rejected_before_correlations(defect):
    spectra = merged([1, 2, 3])
    ids = spectra["experiment_sample_id"].tolist()
    analysis = {"pca": {"ids": ids, "scores": [[-1], [0], [1]]},
                "spectra": {"ids": ids, "processed": [[1, 2, 3], [2, 3, 4], [3, 4, 5]], "wavelengths": [1300, 1400, 1500]}}
    if defect == "shape":
        analysis["spectra"]["wavelengths"] = [1300]
    elif defect == "nonfinite":
        analysis["pca"]["scores"][0][0] = float("inf")
    else:
        analysis["pca"] = "invalid"
    with pytest.raises(ValueError, match="解析"):
        ex.synchronize_experiment(spectra, unity(), config(), analysis)


def test_json_and_csv_provenance_exports_are_finite():
    result = sync(spectra=merged([-10, 2, 20]))
    assert json.loads(json.dumps(result, allow_nan=False))["rows"][0]["valid"] is False
    exported = json.loads(result["exports"]["experiment/synchronization.json"])
    assert exported["provenance"]["config"]["windowSeconds"] == 1
    assert "experiment/phase_summary.csv" in result["exports"]
    assert "pupil_mean" in result["exports"]["experiment/synchronized.csv"]
    assert len(result["timeline"]) <= 1500


@pytest.mark.parametrize("option,value", [("windowSeconds", 0), ("maxGapSeconds", -1), ("minCoverage", 1.5),
                                         ("minSamples", 2.2), ("blinkThreshold", True), ("timeOffsetSeconds", float("inf"))])
def test_invalid_sync_parameters(option, value):
    with pytest.raises(ValueError):
        sync(**{option: value})

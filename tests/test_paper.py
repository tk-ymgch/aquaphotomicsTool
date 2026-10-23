"""Synthetic paper-profile checks. No participant/reference values are embedded."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import paper
import workbench as wb


@pytest.fixture(scope="module")
def generated():
    frame, summary = paper.paper_demo_dataset()
    return frame, summary


def one_subject(generated):
    frame = generated[0]
    return frame[frame.subject.eq("Artificial-1")].reset_index(drop=True).copy()


def settings(frame, **paper_overrides):
    return {"analysisProfile": "paper-v1", "analysisEngine": "aquap2py", "idColumn": "sample_id", "groupColumn": "phase",
            "wavelengthColumns": [c for c in frame if wb.parse_wavelength(c)], "range": [1280, 1620], "pipelineMode": "modern",
            "missing": "error", "scatter": "msc", "smooth": True, "window": 11, "polyorder": 2, "derivative": 1,
            "components": 3, "pcaScale": True, "aquagramWavelengths": [1342, 1440, 1512], "aquagramTolerance": 4,
            "aquagramReference": "global", "pls": {"enabled": False, "targetColumn": None, "maxComponents": 3, "folds": 5, "split": "kfold", "cvGroupColumn": None, "seed": 1, "scale": True},
            "paper": {"phaseColumn": "phase", "baselineLabel": "Baseline", "taskLabel": "Task", "subjectColumn": "subject", "timeColumn": "time_seconds", "timeUnit": "seconds", "inputKind": "as-recorded", **paper_overrides}}


def independent_c(frame, reflectance=False):
    cols = [c for c in frame if wb.parse_wavelength(c) is not None and 1300 <= wb.parse_wavelength(c) <= 1600]
    cols.sort(key=wb.parse_wavelength)
    waves = np.array([wb.parse_wavelength(c) for c in cols])
    raw = frame[cols].to_numpy(float)
    if reflectance:
        raw = np.log10(1 / raw)
    snv = np.array([(row - sum(row) / len(row)) / np.sqrt(sum((row - sum(row) / len(row)) ** 2) / (len(row) - 1)) for row in raw])
    positions = [min(range(len(waves)), key=lambda i: abs(waves[i] - target)) for target in paper.TARGETS]
    selected = snv[:, positions]
    c = (selected - np.mean(selected, axis=0)) / np.std(selected, axis=0, ddof=1)
    baseline = np.flatnonzero(frame.phase.eq("Baseline"))[-5:]
    return snv, c, c - np.mean(c[baseline], axis=0)


def test_profile_pipeline_matches_independent_formula_and_keeps_original_input(generated):
    frame = one_subject(generated)
    original = frame.copy(deep=True)
    config = settings(frame)
    result = wb.analyze(frame, config)
    snv, c, delta = independent_c(frame)
    np.testing.assert_allclose(result["spectra"]["processed"], snv, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(result["aquagram"]["samples"]["values"], delta, rtol=1e-10, atol=1e-11)
    actual_c = pd.read_csv(io.StringIO(result["exports"]["paper/normalized_coordinates.csv"]))[paper.LABELS].to_numpy()
    np.testing.assert_allclose(actual_c, c, rtol=1e-10, atol=1e-11)
    pd.testing.assert_frame_equal(frame, original)
    exported = pd.read_csv(io.StringIO(result["exports"]["data/input.csv"]))
    pd.testing.assert_frame_equal(exported, original, check_exact=False, rtol=1e-13)
    assert result["paper"]["mode"]["available"] is False
    assert result["metadata"]["settings"]["smooth"] is False
    assert result["metadata"]["settings"]["derivative"] == 0
    assert result["metadata"]["settings"]["pcaScale"] is False
    assert json.loads(result["exports"]["settings.json"])["_provenance"]["requestedConfig"] == config
    assert result["metadata"]["execution"]["pcaEngine"] == result["metadata"]["execution"]["aquagramEngine"] == "python"
    assert result["metadata"]["execution"]["packageApiExecuted"] is False
    json.dumps(result, allow_nan=False)


def test_fingerprints_and_explicit_time_metadata(generated):
    frame = one_subject(generated)
    result = wb.analyze(frame, settings(frame))
    fp = result["paper"]["provenance"]["inputFingerprint"]
    raw = np.asarray(result["spectra"]["raw"], dtype="<f8")
    assert fp["selectedRawMatrix"] == hashlib.sha256(raw.tobytes(order="C")).hexdigest()
    assert fp["sourceBytesSha256"] is None
    meta = result["aquagram"]["samples"]["metadata"]
    assert {"paper_subject", "paper_phase", "paper_time_seconds", "paper_series"}.issubset(meta)
    first = np.flatnonzero(frame.phase.eq("Task"))[0]
    assert meta["paper_time_seconds"][first] == 0
    assert meta["paper_series"][first] == "Artificial-1 / Task"
    assert json.loads(result["exports"]["aquagram_samples.json"])["samples"]["metadata"] == meta


def test_reflectance_is_an_explicit_distinct_pipeline(generated):
    frame = one_subject(generated)
    result = wb.analyze(frame, settings(frame, inputKind="reflectance"))
    snv, _, delta = independent_c(frame, True)
    np.testing.assert_allclose(result["spectra"]["processed"], snv, atol=1e-12)
    np.testing.assert_allclose(result["aquagram"]["samples"]["values"], delta, atol=1e-10)
    assert result["paper"]["preprocessing"]["inputKind"] == "reflectance"


@pytest.mark.parametrize("change,match", [
    (lambda d, c: c["paper"].update(timeColumn=None), "時刻列"),
    (lambda d, c: c["paper"].update(inputKind="guess"), "入力値"),
    (lambda d, c: c["paper"].update(baselineLabel="Task"), "異なる"),
])
def test_invalid_settings(generated, change, match):
    frame = one_subject(generated); config = settings(frame)
    change(frame, config)
    with pytest.raises(ValueError, match=match):
        wb.analyze(frame, config)


@pytest.mark.parametrize("failure", ["duplicate", "descending", "missing", "non-numeric"])
def test_task_clock_failures_do_not_get_sample_order_fallback(generated, failure):
    frame = one_subject(generated)
    task = np.flatnonzero(frame.phase.eq("Task"))
    if failure == "duplicate":
        frame.loc[task[1], "time_seconds"] = frame.loc[task[0], "time_seconds"]
    elif failure == "descending":
        frame.loc[task[1], "time_seconds"] = -1
    elif failure == "missing":
        frame.loc[task[1], "time_seconds"] = np.nan
    else:
        frame["time_seconds"] = frame.time_seconds.astype(object)
        frame.loc[task[1], "time_seconds"] = "unreadable"
    with pytest.raises(ValueError, match="Task時刻"):
        wb.analyze(frame, settings(frame))


@pytest.mark.parametrize("unit", ["datetime", "milliseconds"])
def test_non_task_unknown_clock_is_null_and_units_match_seconds(generated, unit):
    frame = one_subject(generated)
    current = wb.analyze(frame, settings(frame))
    task = frame.phase.eq("Task")
    frame["clock"] = [((pd.Timestamp("2026-01-01") + pd.Timedelta(seconds=float(t))).isoformat() if unit == "datetime" else t * 1000) if is_task else "" for t, is_task in zip(frame.time_seconds, task)]
    result = wb.analyze(frame, settings(frame, timeColumn="clock", timeUnit=unit))
    assert all(row["timeSeconds"] is None for row in result["paper"]["rows"] if not row["isTask"])
    np.testing.assert_array_equal([r["timeSeconds"] for r in result["paper"]["rows"] if r["isTask"]], [r["timeSeconds"] for r in current["paper"]["rows"] if r["isTask"]])


@pytest.mark.parametrize("unit", ["datetime", "milliseconds"])
def test_large_absolute_clock_does_not_erase_small_relative_gaps(generated, unit):
    frame = one_subject(generated)
    task = np.flatnonzero(frame.phase.eq("Task"))
    frame["clock"] = pd.Series([None] * len(frame), dtype=object)
    for number, index in enumerate(task):
        frame.loc[index, "clock"] = (pd.Timestamp("2026-01-01") + pd.Timedelta(milliseconds=number)).isoformat() if unit == "datetime" else 1_700_000_000_000 + number
    result = wb.analyze(frame, settings(frame, timeColumn="clock", timeUnit=unit))
    np.testing.assert_allclose([r["timeSeconds"] for r in result["paper"]["rows"] if r["isTask"]], np.arange(len(task)) / 1000, rtol=0, atol=1e-14)


@pytest.mark.parametrize("kind", ["baseline", "task", "missing", "constant", "few-waves", "reserved"])
def test_insufficient_or_degenerate_measurements_fail_explicitly(generated, kind):
    frame = one_subject(generated)
    if kind == "baseline":
        frame = frame.drop(frame.index[0]).reset_index(drop=True)
    elif kind == "task":
        frame = frame.loc[~frame.phase.eq("Task") | (frame.time_seconds <= 45)].reset_index(drop=True)
    elif kind == "missing":
        frame.loc[2, "wl_1400"] = np.nan
    elif kind == "constant":
        cols = [c for c in frame if c.startswith("wl_")]
        frame.loc[0, cols] = 1
    elif kind == "few-waves":
        frame = frame.drop(columns=[c for c in frame if c.startswith("wl_")][20:])
    else:
        frame["paper_series"] = "source"
    with pytest.raises(ValueError):
        wb.analyze(frame, settings(frame))


def test_last_five_baseline_centre_does_not_silently_remove_extra_rows(generated):
    frame = one_subject(generated)
    extra = frame.iloc[[0]].copy(); extra["sample_id"] = "EXTRA-BASELINE"
    frame = pd.concat([extra, frame], ignore_index=True)
    result = wb.analyze(frame, settings(frame))
    record = result["paper"]["subjects"][0]
    assert record["baselineRows"] == 6 and record["rows"] == len(frame)
    assert record["baselineIndices"] == [1, 2, 3, 4, 5]
    assert record["normalizationIndices"] == list(range(len(frame)))
    assert any("Baseline6行" in text for text in result["paper"]["limitations"])


def test_post_block_labels_are_explicit_and_never_guessed_minutes(generated):
    frame = one_subject(generated)
    result = wb.analyze(frame, settings(frame))
    blocks = result["paper"]["blocks"]
    assert [block["label"] for block in blocks] == ["Post-1", "Post-2", "Post-3"]
    assert all(block["n"] == 5 and block["sourceFile"] is None and block["modeMean"] is None for block in blocks)
    assert "paper/post_blocks.csv" in result["exports"]


def test_multiple_subject_mode_is_weighted_svd_and_not_the_published_vector(generated):
    frame = generated[0]
    result = wb.analyze(frame, settings(frame))
    output = result["paper"]
    assert output["mode"]["available"] and output["mode"]["participantCount"] == 7
    assert output["mode"]["source"] == "loaded-subject-pooled-svd"
    pieces = []
    for subject in frame.subject.unique():
        subset = frame[frame.subject.eq(subject)]
        _, _, delta = independent_c(subset)
        pieces.append(delta[subset.phase.eq("Task").to_numpy()] / np.sqrt(subset.phase.eq("Task").sum()))
    pooled = np.vstack(pieces)
    _, _, right = np.linalg.svd(pooled, full_matrices=False)
    vector = right[0]
    if np.median(pooled @ vector) < 0:
        vector = -vector
    np.testing.assert_allclose(output["mode"]["loading"], vector, atol=1e-11)
    assert len(output["fits"]) == 7
    assert all(fit["status"] == "fitted" for fit in output["fits"])
    for subject in output["subjects"]:
        baseline = [output["rows"][i]["modeObserved"] for i in subject["baselineIndices"]]
        assert np.median(baseline) == pytest.approx(0, abs=1e-12)
    assert output["provenance"]["aquap2Executed"] is False


@pytest.mark.parametrize("amplitude", [-2.5, 2.5])
def test_signed_delayed_model_recovers_noiseless_parameters(amplitude):
    t = np.linspace(0, 80, 41)
    expected = amplitude * (1 - np.exp(-np.maximum(t - 7.5, 0) / 18))
    fit = paper.fit_paper_task(t, expected, [-.02, -.01, 0, .01, .02])
    assert fit["status"] == "fitted" and fit["success"]
    assert fit["delay"] == pytest.approx(7.5, abs=2e-5)
    assert fit["amplitude"] == pytest.approx(amplitude, abs=2e-5)
    assert fit["tau"] == pytest.approx(18, abs=2e-4)
    assert fit["r2"] > .99999999
    assert fit["optimizer"]["starts"] == 3
    assert all(point["rate"] == 0 for point in fit["points"] if point["time"] < fit["delay"])
    assert np.sign(fit["points"][-1]["rate"]) == np.sign(amplitude)


def test_constant_task_mode_is_reported_unidentifiable():
    fit = paper.fit_paper_task(np.arange(8), np.ones(8), np.zeros(5))
    assert fit["status"] == "unavailable" and fit["tau"] is None


def test_loading_csv_unknown_participant_count_and_explicit_confirmation(generated):
    vector = np.arange(1, 13, dtype=float); vector /= np.linalg.norm(vector)
    table = pd.DataFrame({"CoordinateIndex": range(1, 13), "Coordinate": paper.LABELS, "CommonLoading": vector, "PooledModeEnergy": .8, "UsedForLoading": 1})
    raw = table.to_csv(index=False).encode()
    loading = paper.inspect_paper_reference_bytes(raw, "synthetic_loading.csv")
    assert loading["participantCount"] == 0
    assert loading["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    frame = one_subject(generated)
    with pytest.raises(ValueError, match="参照参加者数"):
        wb.analyze(frame, settings(frame, loading=loading))
    loading["participantCount"] = 3
    result = wb.analyze(frame, settings(frame, loading=loading))
    assert result["paper"]["mode"]["source"] == "external-loading"
    assert result["paper"]["mode"]["participantCount"] == 3
    np.testing.assert_allclose(result["paper"]["mode"]["loading"], vector)


def test_reference_trajectory_derives_count_and_loading_without_embedded_values(generated):
    pieces = []
    for subject in generated[0].subject.unique()[:2]:
        frame = generated[0].loc[generated[0].subject.eq(subject)]
        _, c, _ = independent_c(frame)
        table = pd.DataFrame(c, columns=paper.LABELS)
        table["Subject"] = subject; table["Phase"] = frame.phase.to_numpy()
        pieces.append(table)
    table = pd.concat(pieces, ignore_index=True)
    raw = table.to_csv(index=False).encode()
    loading = paper.inspect_paper_reference_bytes(raw, "synthetic_coordinates.csv")
    assert loading["participantCount"] == 2
    assert np.linalg.norm(loading["values"]) == pytest.approx(1)
    assert 0 < loading["energy"] <= 1


@pytest.mark.parametrize("kind", ["zero", "wrong-order-label", "duplicate-index", "unused", "energy"])
def test_malformed_loading_csv_rejected(kind):
    vector = np.ones(12) / np.sqrt(12)
    table = pd.DataFrame({"CoordinateIndex": range(1, 13), "Coordinate": paper.LABELS, "CommonLoading": vector, "UsedForLoading": 1, "PooledModeEnergy": .8})
    if kind == "zero": table["CommonLoading"] = 0
    elif kind == "wrong-order-label": table.loc[0, "Coordinate"] = "C2"
    elif kind == "duplicate-index": table.loc[0, "CoordinateIndex"] = 2
    elif kind == "unused": table.loc[0, "UsedForLoading"] = 0
    else: table.loc[0, "PooledModeEnergy"] = 2
    with pytest.raises(ValueError):
        paper.inspect_paper_reference_bytes(table.to_csv(index=False).encode(), "synthetic_bad.csv")


def test_reflectance_nonpositive_input_rejected(generated):
    frame = one_subject(generated); frame.loc[0, "wl_1400"] = 0
    with pytest.raises(ValueError, match="正の有限値"):
        wb.analyze(frame, settings(frame, inputKind="reflectance"))


def test_unknown_profile_is_not_silently_current(generated):
    frame = one_subject(generated); config = settings(frame); config["analysisProfile"] = "unknown"
    with pytest.raises(ValueError, match="解析条件"):
        wb.analyze(frame, config)

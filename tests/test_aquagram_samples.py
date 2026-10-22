"""Fixed-transform sample Aquagrams; synthetic data only, no participant fixtures."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import aquap2py as ap
import workbench as wb


def frame():
    waves = np.arange(1300., 1460., 5.)
    t = np.arange(len(waves), dtype=float)
    x = np.array([.3 + .02 * i + (.15 + .004 * i) * np.exp(-((t - 15) / 6) ** 2)
                  + .003 * np.sin(t / 3 + i / 5) for i in range(9)])
    df = pd.DataFrame(x, columns=[f"wl_{w:g}" for w in waves])
    df.insert(0, "sample_id", [f"000{i}" for i in range(len(x))])
    df.insert(1, "group", ["Baseline"] * 2 + ["Task"] * 4 + ["Recovery"] * 3)
    df["trial"] = ["A"] * 5 + ["B"] * 4
    df["Time"] = np.arange(len(x)) * 5
    return df, waves


def settings(df, waves, **overrides):
    return {"analysisEngine": "python", "idColumn": "sample_id", "groupColumn": "group",
            "wavelengthColumns": [c for c in df if wb.parse_wavelength(c) is not None],
            "range": [waves[0], waves[-1]], "missing": "error", "scatter": "none",
            "smooth": False, "window": 5, "polyorder": 2, "derivative": 0,
            "components": 2, "pcaScale": False, "aquagramWavelengths": waves[[2, 10, 20]].tolist(),
            "aquagramTolerance": 0, "aquagramReference": "global", **overrides}


def assert_sample_aggregation(result):
    aq = result["aquagram"]
    samples = aq["samples"]
    assert samples["ids"] == result["spectra"]["ids"] == result["pca"]["ids"]
    assert samples["groups"] == result["spectra"]["groups"]
    values = np.array(samples["values"])
    assert values.shape == (result["metadata"]["samples"], len(aq["labels"]))
    assert np.isfinite(values).all()
    for group in aq["groups"]:
        mask = np.array(samples["groups"]) == group["name"]
        np.testing.assert_allclose(values[mask].mean(axis=0), group["values"], atol=3e-11, rtol=3e-12)
    saved = pd.read_csv(io.StringIO(result["exports"]["data/aquagram_sample_values.csv"]), dtype={"sample_id": str})
    assert saved.sample_id.tolist() == samples["ids"]
    assert saved["group"].tolist() == samples["groups"]
    np.testing.assert_allclose(saved.iloc[:, 2:].to_numpy(), values, atol=1e-12, rtol=1e-12)
    document = json.loads(result["exports"]["aquagram_samples.json"])
    assert document["labels"] == aq["labels"]
    assert document["wavelengths"] == aq["wavelengths"]
    assert document["samples"] == samples
    assert document["csvColumns"] == saved.columns.tolist()
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("pipeline", ["modern", "legacy-python"])
@pytest.mark.parametrize("reference", ["global", "group:Baseline", "none"])
def test_standard_individual_values_use_same_fixed_global_scale(pipeline, reference):
    df, waves = frame()
    config = settings(df, waves, pipelineMode=pipeline, aquagramReference=reference, scatter="snv", smooth=True)
    original = copy.deepcopy(config)
    result = wb.analyze(df, config)
    assert config == original
    positions = [result["spectra"]["wavelengths"].index(w) for w in result["aquagram"]["wavelengths"]]
    selected = np.asarray(result["spectra"]["processed"])[:, positions]
    expected = selected.copy()
    if reference != "none":
        center = selected.mean(0) if reference == "global" else selected[:2].mean(0)
        expected = (selected - center) / selected.std(0, ddof=0)
    # Selecting columns/boolean rows changes NumPy reduction memory layout;
    # compare the independently reconstructed transform at roundoff tolerance.
    np.testing.assert_allclose(result["aquagram"]["samples"]["values"], expected, atol=5e-13, rtol=1e-12)
    assert result["aquagram"]["samples"]["metadata"]["trial"] == df.trial.tolist()
    assert result["aquagram"]["samples"]["metadata"]["Time"] == df.Time.tolist()
    assert_sample_aggregation(result)


@pytest.mark.parametrize("pipeline", ["modern", "legacy-python"])
@pytest.mark.parametrize("reference", ["global", "group:Baseline"])
def test_native_classic_has_sample_sd_and_exact_control_group_mean(pipeline, reference):
    df, waves = frame()
    result = wb.analyze(df, settings(df, waves, analysisEngine="aquap2py", pipelineMode=pipeline,
                                   aquagramReference=reference, scatter="snv", smooth=True))
    x = np.asarray(result["spectra"]["processed"])
    selected = ap.sgolay(x, window=3, polyorder=2)[:, [2, 10, 20]]
    expected = (selected - selected.mean(0)) / selected.std(0, ddof=1)
    if reference != "global":
        expected -= expected[:2].mean(0)
    np.testing.assert_allclose(result["aquagram"]["samples"]["values"], expected, atol=1e-14)
    assert "rowValues" not in result["aquagram"]
    assert result["metadata"]["compatibilityReport"]["completeCompatibility"] is False
    assert_sample_aggregation(result)


def test_zero_sd_standard_coordinates_are_zero_and_raw_mode_is_not_centered():
    df, waves = frame()
    df.loc[:, f"wl_{waves[2]:g}"] = .5
    standard = wb.analyze(df, settings(df, waves))
    assert np.array(standard["aquagram"]["samples"]["values"])[:, 0].tolist() == [0.] * len(df)
    assert_sample_aggregation(standard)
    raw = wb.analyze(df, settings(df, waves, aquagramReference="none"))
    assert np.array(raw["aquagram"]["samples"]["values"])[:, 0].tolist() == [.5] * len(df)


def temperature_data():
    spec = importlib.util.spec_from_file_location("sample_temperature_fixture", ROOT / "tests/test_temperature.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    x, waves, groups, calibration, temp = module.fixture.__wrapped__()
    df = pd.DataFrame(x, columns=[f"wl_{w:g}" for w in waves])
    df.insert(0, "sample_id", [f"row-{i}" for i in range(len(x))])
    df.insert(1, "group", groups)
    cal = pd.DataFrame(calibration, columns=[f"wl_{w:g}" for w in waves])
    cal["temperature"] = temp
    return df, waves, cal, x, groups, calibration, temp


@pytest.mark.parametrize("base", ["sfc", "aucs", "aucs.tn", "aucs.dce", "aucs.tn.dce"])
def test_all_ten_temperature_modes_keep_exact_frame_reference(base):
    df, waves, cal, x, groups, calibration, temp = temperature_data()
    native = {"enabled": True, "mode": base, "coordinateSystem": "ot1.12", "temperatureColumn": "temperature",
              "calibrationSmoothN": 17, "tCalib": [28., 32.], "tExp": 30., "smoothN": 3,
              "msc": False, "referenceGroup": None}
    cfg = settings(df, waves, analysisEngine="aquap2py", aquagramWavelengths=[1342., 1426., 1476.], nativeAquagram=native)
    plain = wb.analyze(df, cfg, calibration=cal)
    diff = wb.analyze(df, {**cfg, "nativeAquagram": {**native, "mode": base + "-diff", "referenceGroup": "global"}}, calibration=cal)
    p, d = [np.asarray(r["aquagram"]["samples"]["values"]) for r in [plain, diff]]
    np.testing.assert_allclose(d, p - np.asarray(plain["aquagram"]["groups"][0]["values"]), atol=1e-13)
    for result in [plain, diff]:
        assert_sample_aggregation(result)
        assert result["aquagram"]["samples"]["metadata"]["sample_id"] == df.sample_id.tolist()
        assert json.loads(result["exports"]["temperature_aquagram.json"])["samples"] == result["aquagram"]["samples"]
    # The actual row transform agrees with the independent sfc definition or
    # raw per-row polygon-area ratios and recorded calibration coefficients.
    if base == "sfc":
        ix = [int(np.flatnonzero(waves == w)[0]) for w in plain["aquagram"]["wavelengths"]]
        centered = ap.sgolay(x, window=3, polyorder=2)[:, ix] - calibration.mean(0)[ix]
        expected = centered / np.sqrt((centered ** 2).sum(0) / (len(x) - 1))
    else:
        from aquap2py.temperature import _auc_table
        aq = plain["aquagram"]
        ratios, _ = _auc_table(ap.sgolay(x, window=3, polyorder=2), waves, aq["coordinateRanges"])
        provenance = aq["provenance"]
        minimum = np.asarray(provenance["calibrationMinima"])
        expected = (ratios - minimum) * 100 / (np.asarray(provenance["calibrationMaxima"]) - minimum)
        if ".tn" in base:
            expected -= np.asarray(provenance["temperatureBaselinePercent"])
        if ".dce" in base:
            expected *= .04
            if ".tn" not in base:
                expected += 28
    np.testing.assert_allclose(p, expected, atol=2e-11, rtol=1e-12)


def test_metadata_bound_prioritizes_provenance_and_uses_safe_json_scalars():
    df, waves = frame()
    extras = {f"extra_{i}": [i] * len(df) for i in range(68)}
    extras.update(experiment_source_file=["synthetic.csv"] * len(df), experiment_original_id=["original"] * len(df))
    # Add the experimental provenance after many columns; it must still survive.
    df = pd.concat([df, pd.DataFrame(extras)], axis=1)
    result = wb.analyze(df, settings(df, waves))
    metadata = result["aquagram"]["samples"]["metadata"]
    assert len(metadata) == 64
    assert metadata["experiment_source_file"] == ["synthetic.csv"] * len(df)
    assert metadata["experiment_original_id"] == ["original"] * len(df)
    assert list(metadata)[:4] == ["sample_id", "group", "experiment_source_file", "experiment_original_id"]
    policy = json.loads(result["exports"]["aquagram_samples.json"])["metadataPolicy"]
    assert policy["omittedColumns"] == 10 and policy["maximumColumns"] == 64
    for value, expected in [(np.inf, None), (np.nan, None), (pd.NA, None), (pd.NaT, None),
                            (np.int64(3), 3), (2**60, str(2**60)), (True, "True"),
                            ({"nested": 1}, None), (pd.Timestamp("2026-01-01"), "2026-01-01T00:00:00")]:
        assert wb._aquagram_metadata_scalar(value) == expected


def test_metadata_can_be_empty_and_invalid_sample_shapes_do_not_escape():
    df, waves = frame()
    numeric = df[[c for c in df if wb.parse_wavelength(c) is not None]]
    result = wb.analyze(numeric, settings(numeric, waves, idColumn=None, groupColumn=None))
    assert result["aquagram"]["samples"]["metadata"] == {}
    assert_sample_aggregation(result)
    for bad in [[], [[0]], [[np.nan] * 3] * len(numeric)]:
        with pytest.raises(ValueError, match="試料値"):
            wb._attach_aquagram_samples(numeric, result, bad, "invalid")

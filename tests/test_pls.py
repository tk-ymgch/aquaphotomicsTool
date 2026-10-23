"""Independent numerical references and leakage checks for nested PLS CV."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("workbench_pls", ROOT / "python" / "workbench.py")
wb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wb)


def dataset(n=32, p=6, seed=19):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, p))
    y = x[:, 0] * 2 - x[:, 1] * 0.7 + rng.normal(0, 0.2, n)
    df = pd.DataFrame(x, columns=[f"wl_{1300 + i * 5}" for i in range(p)])
    df.insert(0, "sample_id", [f"S{i + 1:03d}" for i in range(n)])
    df["group"] = ["A" if i < n // 2 else "B" for i in range(n)]
    df["target"] = y
    return df


def config(df, pls=None, **overrides):
    columns = [column for column in df if wb.parse_wavelength(column) is not None]
    wls = [wb.parse_wavelength(column) for column in columns]
    settings = {
        "idColumn": "sample_id", "groupColumn": "group", "wavelengthColumns": columns,
        "range": [min(wls), max(wls)], "missing": "error", "scatter": "none",
        "smooth": False, "window": 5, "polyorder": 2, "derivative": 0,
        "pcaScale": False, "components": 3, "aquagramWavelengths": [wls[0], wls[len(wls) // 2], wls[-1]],
        "aquagramReference": "global", "aquagramTolerance": 0,
        "pls": {"enabled": True, "targetColumn": "target", "maxComponents": 3, "folds": 4,
                "split": "kfold", "cvGroupColumn": None, "seed": 17, "scale": True},
    }
    if pls:
        settings["pls"].update(pls)
    settings.update(overrides)
    return settings


def model_record(result):
    return json.loads(result["exports"]["pls_model.json"])


def independent_choice(x, y, max_components, seed, scale):
    """Reference uses sklearn's own centering/scaling, not workbench helpers."""
    folds = list(KFold(3, shuffle=True, random_state=seed).split(x))
    curve = []
    for k in range(1, max_components + 1):
        prediction = np.zeros(len(y))
        for train, test in folds:
            model = PLSRegression(n_components=k, scale=scale, max_iter=1000, tol=1e-10)
            prediction[test] = model.fit(x[train], y[train]).predict(x[test]).reshape(-1)
        curve.append(float(np.sqrt(np.mean((prediction - y) ** 2))))
    best = min(curve)
    tie_tolerance = max(1e-12 * float(y.std()), 1e-10 * best)
    selected = next(k + 1 for k, loss in enumerate(curve) if loss <= best + tie_tolerance)
    return selected, curve


@pytest.mark.parametrize("scale", [True, False])
def test_nested_cv_matches_independent_sklearn_loop_and_pooled_metrics(scale):
    df = dataset()
    cfg = config(df, {"scale": scale})
    original = df.copy(deep=True)
    original_cfg = copy.deepcopy(cfg)
    result = wb.analyze(df, cfg)
    pls = result["pls"]
    x = df[cfg["wavelengthColumns"]].to_numpy()
    y = df["target"].to_numpy()
    reference = np.zeros(len(y))
    baseline = np.zeros(len(y))
    reference_components = []
    for train, test in KFold(4, shuffle=True, random_state=17).split(x):
        k, _ = independent_choice(x[train], y[train], 3, 17, scale)
        model = PLSRegression(n_components=k, scale=scale, max_iter=1000, tol=1e-10)
        reference[test] = model.fit(x[train], y[train]).predict(x[test]).reshape(-1)
        baseline[test] = y[train].mean()
        reference_components.append(k)
    final_k, final_curve = independent_choice(x, y, 3, 17, scale)
    np.testing.assert_allclose(pls["predictedCV"], reference, rtol=1e-10, atol=1e-11)
    np.testing.assert_allclose([item["rmseCV"] for item in pls["curve"]], final_curve, atol=1e-11)
    assert pls["selectedComponents"] == final_k
    assert [item["components"] for item in pls["foldModels"]] == reference_components
    residual = y - reference
    np.testing.assert_allclose(pls["metrics"]["rmseCV"], np.sqrt(np.mean(residual ** 2)))
    np.testing.assert_allclose(pls["metrics"]["maeCV"], np.mean(np.abs(residual)))
    np.testing.assert_allclose(pls["metrics"]["r2CV"], 1 - np.sum(residual ** 2) / np.sum((y - y.mean()) ** 2))
    np.testing.assert_allclose(pls["metrics"]["biasCV"], np.mean(reference - y), atol=1e-12)
    np.testing.assert_allclose(pls["metrics"]["baselineRmseCV"], np.sqrt(np.mean((baseline - y) ** 2)))
    pd.testing.assert_frame_equal(df, original)
    assert cfg == original_cfg
    json.dumps(result, allow_nan=False)


def test_grouped_nested_cv_has_no_group_overlap_at_either_level():
    sizes = [2, 3, 4, 5, 6, 7]
    df = dataset(sum(sizes))
    df["subject"] = np.repeat([f"G{i}" for i in range(6)], sizes)
    result = wb.analyze(df, config(df, {"split": "group", "cvGroupColumn": "subject", "folds": 3}))
    record = model_record(result)
    groups = df["subject"].to_numpy()
    coverage = np.zeros(len(df), dtype=int)
    for outer in record["outerFolds"]:
        train, test = outer["trainIndices"], outer["testIndices"]
        assert set(groups[train]).isdisjoint(groups[test])
        assert set(train).isdisjoint(test)
        coverage[test] += 1
        for inner in outer["selection"]["inner"]:
            assert set(inner["trainIndices"]).issubset(train)
            assert set(inner["testIndices"]).issubset(train)
            assert set(groups[inner["trainIndices"]]).isdisjoint(groups[inner["testIndices"]])
    np.testing.assert_array_equal(coverage, 1)
    assert result["pls"]["method"] == "nested-group-kfold"
    y = np.array(result["pls"]["observed"])
    predictions = np.array(result["pls"]["predictedCV"])
    np.testing.assert_allclose(result["pls"]["metrics"]["rmseCV"], np.sqrt(np.mean((y - predictions) ** 2)))


def manual_msc_transform(raw, train_indices):
    training = raw[train_indices]
    medians = np.nanmedian(training, axis=0)
    filled = np.where(np.isfinite(training), training, medians)
    reference = filled.mean(axis=0)
    corrected = []
    for row in filled:
        slope, offset = np.polyfit(reference, row, 1)
        corrected.append((row - offset) / slope)
    return medians, reference, np.array(corrected)


def test_medians_msc_reference_and_scaling_are_fit_only_on_each_training_partition():
    df = dataset(28)
    cols = config(df)["wavelengthColumns"]
    rng = np.random.default_rng(71)
    raw = 10 + np.linspace(0, 8, 6) + rng.normal(0, 0.3, (28, 6))
    raw[1, 0] = np.nan
    raw[5, 2] = np.nan
    raw[12, 4] = np.nan
    raw[0] += np.linspace(20, 60, 6)
    df.loc[:, cols] = raw
    result = wb.analyze(df, config(df, missing="median", scatter="msc"))
    record = model_record(result)
    partitions = []
    for outer in record["outerFolds"]:
        partitions.append(outer)
        partitions.extend(outer["selection"]["inner"])
    partitions.extend(record["finalSelection"]["inner"])
    for partition in partitions:
        medians, reference, corrected = manual_msc_transform(raw, partition["trainIndices"])
        np.testing.assert_allclose(partition["preprocessing"]["medians"], medians)
        np.testing.assert_allclose(partition["preprocessing"]["mscReference"], reference)
        np.testing.assert_allclose(partition["scaling"]["xMean"], corrected.mean(axis=0), atol=1e-10)
        np.testing.assert_allclose(partition["scaling"]["xScale"], corrected.std(axis=0, ddof=1), rtol=1e-9, atol=1e-10)
        np.testing.assert_allclose(partition["scaling"]["yMean"], df["target"].to_numpy()[partition["trainIndices"]].mean())
    # Corrupt only outer fold 1's held-out labels. Its tuning and predictions
    # cannot change, since neither its inner selection nor fit can see them.
    first = record["outerFolds"][0]
    changed = df.copy(deep=True)
    changed.loc[first["testIndices"], "target"] += 1000
    again = wb.analyze(changed, config(changed, missing="median", scatter="msc"))
    repeated_first = model_record(again)["outerFolds"][0]
    assert repeated_first["selection"] == first["selection"]
    np.testing.assert_allclose(np.array(result["pls"]["predictedCV"])[first["testIndices"]],
                               np.array(again["pls"]["predictedCV"])[first["testIndices"]], atol=1e-12)


@pytest.mark.parametrize("scale", [True, False])
def test_exported_affine_coefficients_reproduce_calibration_with_offsets_and_unequal_scales(scale):
    df = dataset()
    cols = config(df)["wavelengthColumns"]
    df.loc[:, cols] = df[cols].to_numpy() * [0.1, 2, 20, 0.5, 0.2, 5] + [1000, 20, -50, 80, 1, 10]
    result = wb.analyze(df, config(df, {"scale": scale}))
    coefficients = result["pls"]["coefficients"]
    processed = np.array(result["spectra"]["processed"])
    reconstructed = processed @ np.array(coefficients["values"]) + coefficients["intercept"]
    np.testing.assert_allclose(reconstructed, result["pls"]["predictedCalibration"], atol=1e-9, rtol=1e-10)
    assert "X_processed" in result["pls"]["definition"]
    record = model_record(result)
    assert record["finalPreprocessing"]["originalWavelengths"] == result["spectra"]["wavelengths"]
    assert record["finalScaling"]["xScaleDdof"] == 1


def test_rank_deficiency_caps_candidates_and_ties_choose_one_component():
    df = dataset()
    cols = config(df)["wavelengthColumns"]
    t = np.linspace(-3, 3, len(df))
    df.loc[:, cols] = np.outer(t, np.arange(1, len(cols) + 1))
    df["target"] = 4 * t + 2
    result = wb.analyze(df, config(df, {"maxComponents": 10}))
    assert result["pls"]["selectedComponents"] == 1
    assert len(result["pls"]["curve"]) == 1
    assert all(fold["components"] == 1 for fold in result["pls"]["foldModels"])
    assert any("ランク" in text for text in result["pls"]["warnings"])
    assert result["pls"]["metrics"]["rmseCV"] < 1e-10


def test_numerically_tied_cv_errors_prefer_fewer_components():
    n = 12
    y = np.linspace(-1, 1, n)
    constraints = []
    for train, _ in KFold(3, shuffle=True, random_state=17).split(y):
        row = np.zeros(n)
        row[train] = y[train] - y[train].mean()
        constraints.append(row)
    # An independent nuisance direction orthogonal to y within every inner
    # training split makes 1 and 2 components equally exact, at full X rank 2.
    _, _, vt = np.linalg.svd(np.array(constraints), full_matrices=True)
    z = vt[-1]
    df = dataset(n, p=3)
    df.loc[:, ["wl_1300", "wl_1305", "wl_1310"]] = np.c_[y, z, 2 * z]
    df["target"] = y
    result = wb.analyze(df, config(df))
    assert len(result["pls"]["curve"]) == 2
    assert max(item["rmseCV"] for item in result["pls"]["curve"]) < 1e-10
    assert result["pls"]["selectedComponents"] == 1


def test_predictions_curves_and_fold_exports_match_results_and_preserve_row_order():
    df = dataset()
    cfg = config(df)
    first = wb.analyze(df, cfg)
    second = wb.analyze(df, cfg)
    assert first["pls"] == second["pls"]
    pls = first["pls"]
    predictions = pd.read_csv(io.StringIO(first["exports"]["data/pls_predictions.csv"]))
    assert predictions["sample_id"].tolist() == df["sample_id"].tolist()
    np.testing.assert_allclose(predictions["observed"], pls["observed"])
    np.testing.assert_allclose(predictions["predicted_cv"], pls["predictedCV"])
    np.testing.assert_allclose(predictions["residual_cv"], pls["residuals"])
    np.testing.assert_array_equal(predictions["outer_fold"], pls["fold"])
    curve = pd.read_csv(io.StringIO(first["exports"]["data/pls_cv_curve.csv"]))
    np.testing.assert_allclose(curve["rmseCV"], [item["rmseCV"] for item in pls["curve"]])
    assert json.loads(first["exports"]["settings.json"])["pls"] == first["metadata"]["settings"]["pls"]
    assert model_record(first)["requestedPLS"] == cfg["pls"]
    json.dumps(first, allow_nan=False)


def test_disabled_pls_preserves_existing_analysis_and_export_set():
    df = dataset()
    cfg = config(df)
    cfg.pop("pls")
    baseline = wb.analyze(df, cfg)
    disabled = wb.analyze(df, {**cfg, "pls": {"enabled": False}})
    assert "pls" not in baseline and "pls" not in disabled
    for key in ["spectra", "pca", "aquagram"]:
        assert baseline[key] == disabled[key]
    assert set(baseline["exports"]) == set(disabled["exports"])


@pytest.mark.parametrize("value", [np.nan, np.inf, "not-a-number"])
def test_missing_or_categorical_target_is_never_imputed(value):
    df = dataset()
    df["target"] = df["target"].astype(object)
    df.loc[0, "target"] = value
    with pytest.raises(ValueError, match="目的変数.*欠損・非数値・無限大"):
        wb.analyze(df, config(df, missing="median"))


@pytest.mark.parametrize("target", ["wl_1300", "sample_id", "subject"])
def test_target_cannot_be_spectrum_id_or_cv_group(target):
    df = dataset()
    df["subject"] = np.arange(len(df)) % 4
    with pytest.raises(ValueError, match="目的変数には波長列・試料ID列・CVグループ列"):
        wb.analyze(df, config(df, {"targetColumn": target, "cvGroupColumn": "subject"}))


def test_global_and_training_fold_constant_targets_fail_explicitly():
    df = dataset(8)
    df["target"] = 3.0
    with pytest.raises(ValueError, match="目的変数が一定値"):
        wb.analyze(df, config(df))
    outer_train, _ = next(KFold(2, shuffle=True, random_state=17).split(df))
    df["target"] = 1.0
    df.loc[outer_train, "target"] = 0.0
    with pytest.raises(ValueError, match="目的変数が一定値"):
        wb.analyze(df, config(df, {"folds": 2}))


@pytest.mark.parametrize("updates, message", [
    ({"maxComponents": 11}, "最大成分数"),
    ({"folds": 11}, "外側分割数"),
    ({"seed": 2147483648}, "乱数シード"),
    ({"seed": -1}, "乱数シード"),
    ({"maxComponents": 1.5}, "整数"),
    ({"targetColumn": None}, "数値目的変数"),
    ({"split": "group", "cvGroupColumn": None}, "CVグループ"),
])
def test_bad_pls_settings_are_actionable(updates, message):
    df = dataset()
    with pytest.raises(ValueError, match=message):
        wb.analyze(df, config(df, updates))


def test_group_count_and_nested_feasibility_are_both_validated():
    df = dataset(24)
    df["subject"] = np.repeat(["A", "B"], 12)
    with pytest.raises(ValueError, match="3つ以上"):
        wb.analyze(df, config(df, {"split": "group", "cvGroupColumn": "subject"}))
    df["subject"] = np.repeat(["A", "B", "C"], 8)
    with pytest.raises(ValueError, match="内側CVに2つ以上"):
        wb.analyze(df, config(df, {"split": "group", "cvGroupColumn": "subject", "folds": 2}))
    result = wb.analyze(df, config(df, {"split": "group", "cvGroupColumn": "subject", "folds": 5}))
    assert result["pls"]["folds"] == 3
    assert result["pls"]["innerFolds"] == 2
    assert result["metadata"]["settings"]["pls"]["folds"] == 3


def test_sample_size_tiny_values_and_computation_limits_fail_explicitly():
    small = dataset(7)
    with pytest.raises(ValueError, match="8試料以上"):
        wb.analyze(small, config(small))
    tiny = dataset()
    tiny["target"] *= 1e-200
    with pytest.raises(ValueError, match="数値範囲が極端"):
        wb.analyze(tiny, config(tiny))
    big = dataset(501)
    with pytest.raises(ValueError, match="500試料"):
        wb.analyze(big, config(big))


def test_pls_geometry_limit_is_checked_before_exploratory_factorization(monkeypatch):
    from sklearn.decomposition import PCA
    def unexpected_factorization(*args, **kwargs):
        raise AssertionError("oversized PLS analysis must be rejected before PCA")
    monkeypatch.setattr(PCA, "fit_transform", unexpected_factorization)
    df = dataset(501)
    with pytest.raises(ValueError, match="500試料"):
        wb.analyze(df, config(df))


def test_demo_has_artificial_continuous_target_without_changing_wavelengths():
    df, summary = wb.demo_dataset()
    assert summary["artificial"] is True
    assert len(summary["wavelengthColumns"]) == 61
    assert pd.api.types.is_numeric_dtype(df["synthetic_target"])
    assert df["synthetic_target"].nunique() > 10
    result = wb.analyze(df, config(df, {"targetColumn": "synthetic_target"}, scatter="snv", smooth=True, window=11))
    assert result["pls"]["metrics"]["rmseCV"] < result["pls"]["metrics"]["baselineRmseCV"]
    assert "人工" in result["exports"]["README.txt"]

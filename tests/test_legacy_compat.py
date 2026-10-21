"""Bounded numerical compatibility with functions read from legacy/app.py.

The legacy functions are AST-extracted at test time: no Streamlit is imported
and no reimplementation of the reference's math is used for the comparison.
This tests explicit matching settings, not all old defaults or fallback paths.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy.signal import savgol_filter
from sklearn.decomposition import PCA

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("legacy_compat_workbench", ROOT / "python" / "workbench.py")
wb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wb)
REFERENCE_NAMES = {"numeric_matrix", "snv", "msc", "valid_window", "preprocess_matrix", "compute_aquagram", "run_python_analysis"}


@pytest.fixture(scope="module")
def old():
    source_path = ROOT / "legacy" / "app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in REFERENCE_NAMES]
    assert {node.name for node in nodes} == REFERENCE_NAMES
    namespace = {"np": np, "pd": pd, "savgol_filter": savgol_filter, "PCA": PCA, "Any": Any}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_path), "exec"), namespace)
    return namespace


def data(irregular=False):
    rng = np.random.default_rng(5317)
    wl = 1300 + np.cumsum(np.resize([3, 5, 7, 4, 6], 31)) if irregular else np.arange(1300, 1455, 5)
    rows = []
    for i in range(24):
        t = (wl - wl.mean()) / 70
        signal = (0.4 + 0.2 * np.exp(-t * t) + 0.025 * (i // 8) * np.exp(-(t - 0.5) ** 2 / 0.3))
        signal = signal * (0.9 + 0.008 * i) + 0.001 * i + rng.normal(0, 0.003, len(wl))
        rows.append(signal)
    x = np.array(rows)
    x[1, 4] = np.nan
    x[11, 9] = np.nan
    x[19, 21] = np.nan
    x[3, 4] += 0.08  # makes column mean and median observably different
    df = pd.DataFrame(x, columns=[f"wl_{w:g}" for w in wl])
    df.insert(0, "group", np.repeat(["A", "B", "C"], 8))
    df.insert(0, "sample_id", [f"S{i:03d}" for i in range(24)])
    df["target"] = np.arange(24) * 0.1 + rng.normal(0, 0.3, 24)
    return df, wl.astype(float)


def config(df, wl, **changes):
    cfg = {"pipelineMode": "legacy-python", "idColumn": "sample_id", "groupColumn": "group",
           "wavelengthColumns": [f"wl_{w:g}" for w in wl], "range": [float(wl[0]), float(wl[-1])],
           "missing": "mean", "scatter": "snv", "smooth": True, "window": 7, "polyorder": 2,
           "derivative": 0, "pcaScale": False, "components": 5,
           "aquagramWavelengths": [float(wl[i]) for i in [3, 10, 18, 27]],
           "aquagramReference": "global", "aquagramTolerance": 0}
    cfg.update(changes)
    return cfg


@pytest.mark.parametrize("irregular", [False, True], ids=["equal-spacing", "unequal-spacing"])
@pytest.mark.parametrize("scatter", ["none", "snv", "msc"])
@pytest.mark.parametrize("derivative", [0, 1, 2])
@pytest.mark.parametrize("reference", ["none", "global", "control"])
def test_legacy_python_matches_extracted_reference_for_explicit_valid_settings(old, irregular, scatter, derivative, reference):
    df, wl = data(irregular)
    cfg = config(df, wl, scatter=scatter, derivative=derivative,
                 aquagramReference="group:A" if reference == "control" else reference)
    original = df.copy(deep=True)
    requested = copy.deepcopy(cfg)
    legacy = old["run_python_analysis"](
        df=df, sample_col="sample_id", group_col="group", target_col="",
        wl_cols=cfg["wavelengthColumns"], wavelengths=wl,
        scatter={"none": "None", "snv": "SNV", "msc": "MSC"}[scatter],
        use_savgol=True, sg_window=7, sg_polyorder=2, derivative_order=derivative,
        aquagram_wavelengths=cfg["aquagramWavelengths"],
        reference_mode={"none": "None", "global": "Global mean", "control": "Control group"}[reference],
        control_group="A" if reference == "control" else "",
    )
    actual = wb.analyze(df, cfg)
    np.testing.assert_allclose(actual["spectra"]["raw"], legacy["x_raw"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(actual["spectra"]["processed"], legacy["x_processed"], rtol=1e-9, atol=1e-10)
    np.testing.assert_array_equal(actual["spectra"]["wavelengths"], legacy["wavelengths"])
    reference_loadings = legacy["loadings"].iloc[:, 1:].to_numpy()
    actual_loadings = np.array(actual["pca"]["loadings"])
    signs = np.where(np.sum(reference_loadings * actual_loadings, axis=0) >= 0, 1.0, -1.0)
    np.testing.assert_allclose(actual_loadings, reference_loadings * signs, rtol=2e-6, atol=2e-7)
    np.testing.assert_allclose(actual["pca"]["scores"], legacy["scores"].iloc[:, 2:].to_numpy() * signs, rtol=2e-6, atol=2e-7)
    np.testing.assert_allclose(actual["pca"]["explainedVariance"], legacy["variance"]["explained_variance"], atol=1e-9, rtol=1e-8)
    for group in actual["aquagram"]["groups"]:
        reference_aq = legacy["aquagram"].loc[legacy["aquagram"]["group"] == group["name"]].sort_values("wavelength")
        np.testing.assert_allclose(group["values"], reference_aq["value"], rtol=1e-8, atol=1e-9)
    provenance = json.loads(actual["exports"]["settings.json"])["_provenance"]
    assert provenance["pipelineMode"] == "legacy-python"
    assert provenance["order"] == ["missing", "sg", "scatter"]
    assert provenance["aquap2_not_executed"] is True
    assert provenance["interpolated"] is False
    if irregular:
        assert any("median(diff(wl))" in message for message in actual["metadata"]["warnings"])
    pd.testing.assert_frame_equal(df, original)
    assert cfg == requested


def test_modern_is_the_unchanged_default_and_modes_have_different_orders():
    df, wl = data()
    modern = config(df, wl, pipelineMode="modern", missing="median")
    implicit = modern.copy()
    implicit.pop("pipelineMode")
    a = wb.analyze(df, implicit)
    b = wb.analyze(df, modern)
    for field in ["spectra", "pca", "aquagram"]:
        assert a[field] == b[field]
    c = wb.analyze(df, {**modern, "pipelineMode": "legacy-python"})
    assert not np.allclose(b["spectra"]["processed"], c["spectra"]["processed"])
    assert b["metadata"]["settings"]["pipelineMode"] == "modern"
    assert json.loads(b["exports"]["settings.json"])["_provenance"]["order"] == ["missing", "scatter", "sg"]


def test_average_imputation_is_explicit_and_distinct_from_median(old):
    df, wl = data()
    cfg = config(df, wl, smooth=False, scatter="none")
    mean = wb.analyze(df, cfg)
    median = wb.analyze(df, {**cfg, "missing": "median"})
    expected = old["numeric_matrix"](df, cfg["wavelengthColumns"])
    np.testing.assert_allclose(mean["spectra"]["raw"], expected, rtol=1e-12, atol=1e-12)
    assert mean["spectra"]["raw"][1][4] != median["spectra"]["raw"][1][4]
    imputed = json.loads(mean["exports"]["settings.json"])["_provenance"]["imputed"]
    assert "mean" in imputed[cfg["wavelengthColumns"][4]]


def test_raw_aquagram_preserves_constant_wavelength_and_single_group_mean():
    df, wl = data()
    df["group"] = "One"
    df["wl_1315"] = 7.0
    cfg = config(df, wl, smooth=False, scatter="none", aquagramReference="none")
    result = wb.analyze(df, cfg)
    assert result["aquagram"]["groups"][0]["values"][0] == 7.0
    assert not any("群平均差は0" in message for message in result["metadata"]["warnings"])
    assert "標準化は行いません" in result["aquagram"]["definition"]
    alias = wb.analyze(df, {**cfg, "aquagramReference": "None"})
    assert alias["aquagram"] == result["aquagram"]
    assert alias["metadata"]["settings"]["aquagramReference"] == "none"
    # An actual group named none remains selectable through the explicit prefix.
    df["group"] = "none"
    control = wb.analyze(df, {**cfg, "aquagramReference": "group:none"})
    np.testing.assert_allclose(control["aquagram"]["groups"][0]["values"], 0)


def test_irregular_spacing_policy_is_mode_specific_and_recorded():
    df, wl = data(True)
    legacy_cfg = config(df, wl)
    modern_cfg = {**legacy_cfg, "pipelineMode": "modern", "aquagramTolerance": 10}
    legacy = wb.analyze(df, legacy_cfg)
    modern = wb.analyze(df, modern_cfg)
    np.testing.assert_array_equal(legacy["spectra"]["wavelengths"], wl)
    np.testing.assert_allclose(modern["spectra"]["wavelengths"], np.linspace(wl[0], wl[-1], len(wl)))
    prov = json.loads(legacy["exports"]["settings.json"])["_provenance"]
    assert prov["sgDelta"] == np.median(np.diff(wl))
    assert prov["irregularWavelengthPolicy"] == "median-step-without-interpolation"


@pytest.mark.parametrize("changes, pattern", [
    ({"pipelineMode": "unknown"}, "処理モード"),
    ({"window": 4}, "SG窓幅"),
    ({"polyorder": 0}, "自動補正は再現しません"),
])
def test_legacy_mode_keeps_strict_validation(changes, pattern):
    df, wl = data()
    with pytest.raises(ValueError, match=pattern):
        wb.analyze(df, config(df, wl, **changes))


def test_legacy_mode_does_not_reproduce_all_missing_zero_fill_or_unknown_control_fallback():
    df, wl = data()
    df["wl_1300"] = np.nan
    with pytest.raises(ValueError, match="有効な数値"):
        wb.analyze(df, config(df, wl))
    df, wl = data()
    with pytest.raises(ValueError, match="対照群.*見つかりません"):
        wb.analyze(df, config(df, wl, aquagramReference="group:unknown"))


def test_legacy_pls_mean_and_post_sg_msc_fit_only_training_rows(old):
    df, wl = data(True)
    cfg = config(df, wl, scatter="msc", derivative=1)
    cfg["pls"] = {"enabled": True, "targetColumn": "target", "maxComponents": 3,
                  "folds": 3, "split": "kfold", "cvGroupColumn": None, "seed": 17, "scale": True}
    result = wb.analyze(df, cfg)
    record = json.loads(result["exports"]["pls_model.json"])
    partitions = []
    for outer in record["outerFolds"]:
        partitions.append(outer)
        partitions.extend(outer["selection"]["inner"])
    partitions.extend(record["finalSelection"]["inner"])
    for partition in partitions:
        training = df.iloc[partition["trainIndices"]]
        filled = old["numeric_matrix"](training, cfg["wavelengthColumns"])
        filtered, _ = old["preprocess_matrix"](filled, wl, "None", True, 7, 2, 1)
        state = partition["preprocessing"]
        np.testing.assert_allclose(state["imputationValues"], np.nanmean(training[cfg["wavelengthColumns"]].to_numpy(), axis=0))
        np.testing.assert_allclose(state["mscReference"], filtered.mean(axis=0), rtol=1e-10, atol=1e-12)
        assert state["pipelineMode"] == "legacy-python"
        assert state["order"] == ["missing", "sg", "scatter"]
        assert state["sgDelta"] == np.median(np.diff(wl))
        assert state["aquap2_not_executed"] is True
    coefficients = result["pls"]["coefficients"]
    reconstructed = np.array(result["spectra"]["processed"]) @ np.array(coefficients["values"]) + coefficients["intercept"]
    np.testing.assert_allclose(reconstructed, result["pls"]["predictedCalibration"], rtol=1e-7, atol=1e-8)
    assert record["pipelineMode"] == "legacy-python"
    json.dumps(result, allow_nan=False)

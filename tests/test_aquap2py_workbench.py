"""File/UI contract around the independent port; native-R parity is tested separately."""
import copy
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import workbench as wb
import aquap2py as port


def settings(df, **changes):
    columns = [c for c in df if wb.parse_wavelength(c) is not None]
    waves = sorted(wb.parse_wavelength(c) for c in columns)
    return {"analysisEngine": "aquap2py", "idColumn": "sample_id", "groupColumn": "group",
        "wavelengthColumns": columns, "range": [waves[0], waves[-1]], "missing": "error",
        "scatter": "snv", "smooth": True, "window": 11, "polyorder": 2, "derivative": 0,
        "pcaScale": False, "components": 5, "aquagramWavelengths": waves[::10],
        "aquagramReference": "global", "aquagramTolerance": 0, **changes}


def test_actual_port_results_exports_and_requested_config_replay():
    df, _ = wb.demo_dataset()
    config = settings(df, endpoint="never-export-transport", token="never-export-token",
        pls={"enabled": False, "targetColumn": "synthetic_target", "maxComponents": 5,
            "folds": 5, "split": "kfold", "cvGroupColumn": None, "seed": 42, "scale": True,
            "token": "never-export-nested"})
    original = copy.deepcopy(config)
    result = wb.analyze(df, config)
    assert config == original
    raw = np.asarray(result["spectra"]["raw"])
    expected = port.preprocess(raw, [{"method": "snv"}, {"method": "sgolay", "window": 11,
        "polyorder": 2, "derivative": 0, "delta": 1}])
    np.testing.assert_array_equal(result["spectra"]["processed"], expected)
    assert result["metadata"]["execution"]["engine"] == "aquap2py"
    assert result["metadata"]["execution"]["packageApiExecuted"] is False
    assert result["aquagram"]["sdDdof"] == 1
    report = result["metadata"]["compatibilityReport"]
    assert report["completeCompatibility"] is False and report["currentRunComparedWithR"] is False
    assert len(report["apiEntries"]) == 64
    assert report == json.loads(result["exports"]["compatibility-report.json"])
    runtime = json.loads(result["exports"]["aquap2py_runtime.json"])
    assert runtime["rRequired"] is False and runtime["nativePipeline"]["rExecuted"] is False
    document = json.loads(result["exports"]["settings.json"])
    provenance = document["_provenance"]
    assert provenance["snvDdof"] == 1 and provenance["sgDelta"] == 1
    assert provenance["interpolated"] is False and provenance["mscReference"] is None
    assert "never-export" not in json.dumps(result)
    replay = wb.analyze(df, provenance["requestedConfig"])
    for key in ["spectra", "pca", "aquagram"]:
        assert result[key] == replay[key]
    for name in ["preprocessed", "pca_scores", "pca_loadings", "pca_variance", "aquagram"]:
        saved = pd.read_csv(io.StringIO(result["exports"][f"data/{name}.csv"]))
        assert not saved.empty
    saved = pd.read_csv(io.StringIO(result["exports"]["data/preprocessed.csv"]))
    np.testing.assert_allclose(saved.iloc[:, 2:], expected, rtol=1e-12, atol=1e-14)
    assert "人工" in result["exports"]["README.txt"]
    assert any("人工" in warning for warning in result["metadata"]["warnings"])
    assert "GNU GENERAL PUBLIC LICENSE" in result["exports"]["aquap2py/LICENSE"]
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_native_snv_and_sg_differ_from_standard_for_documented_reasons():
    df, _ = wb.demo_dataset()
    cfg = settings(df, smooth=False)
    port_result = wb.analyze(df, cfg)
    standard = wb.analyze(df, {**cfg, "analysisEngine": "python"})
    n_columns = len(cfg["wavelengthColumns"])
    factor = np.sqrt((n_columns - 1) / n_columns)
    np.testing.assert_allclose(port_result["spectra"]["processed"], np.asarray(standard["spectra"]["processed"]) * factor, atol=2e-14)
    cfg = settings(df, scatter="none", derivative=1)
    port_result = wb.analyze(df, cfg)
    standard = wb.analyze(df, {**cfg, "analysisEngine": "python"})
    # R's ts=1 is per column; Workbench standard delta=5 is per nm.
    np.testing.assert_allclose(np.asarray(port_result["spectra"]["processed"])[:, 5:-5],
        np.asarray(standard["spectra"]["processed"])[:, 5:-5] * 5, rtol=1e-10, atol=1e-14)


def test_uneven_grid_keeps_measured_columns_and_order_settings():
    rng = np.random.default_rng(87)
    waves = [1300, 1303, 1310, 1315, 1320, 1331, 1340]
    df = pd.DataFrame(rng.normal(size=(8, 7)), columns=[f"wl_{w}" for w in waves])
    df.insert(0, "group", ["A"] * 3 + ["B"] * 5)
    df.insert(0, "sample_id", [f"S{i}" for i in range(8)])
    cfg = settings(df, window=5, components=3, aquagramWavelengths=[1300, 1310, 1340], scatter="msc", aquagramReference="group:A")
    first = wb.analyze(df, cfg)
    second = wb.analyze(df, {**cfg, "pipelineMode": "legacy-python"})
    for result in [first, second]:
        assert result["spectra"]["wavelengths"] == waves
        assert result["aquagram"]["wavelengths"] == [1300, 1310, 1340]
        assert result["aquagram"]["groups"][0]["values"] == [0, 0, 0]
    assert not np.allclose(first["spectra"]["processed"], second["spectra"]["processed"])


@pytest.mark.parametrize("change", [{"missing": "mean"}, {"pcaScale": True},
    {"pls": {"enabled": True}}, {"components": 11}, {"aquagramReference": "none"},
    {"aquagramReference": []}, {"scatter": []}, {"derivative": 3}, {"analysisEngine": "typo"}])
def test_unsupported_requests_fail_without_falling_back(change):
    df, _ = wb.demo_dataset()
    with pytest.raises(ValueError):
        wb.analyze(df, settings(df, **change))

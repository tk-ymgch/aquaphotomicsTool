"""File/settings/export integration for the scoped native Python engines.

No R process is required here. Formal installed-package oracle evidence is
maintained separately by compare_temperature.py and compare_plsr.py.
"""
from __future__ import annotations

import copy
import hashlib
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


def _temperature_fixture():
    # Reuse the independently maintained numerical fixture, rather than
    # duplicating its scientific spectrum/calibration construction here.
    spec = importlib.util.spec_from_file_location("native_temperature_fixture", ROOT / "tests/test_temperature.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fixture.__wrapped__()


@pytest.fixture(scope="module")
def data():
    x, w, groups, calibration, temperatures = _temperature_fixture()
    measurement = pd.DataFrame(x, columns=[f"wl_{v:g}" for v in w])
    measurement.insert(0, "sample_id", ["0001", '引用,"ID"\n日本語'] + [f"{i+1:04d}" for i in range(2, len(x))])
    measurement.insert(1, "group", groups)
    measurement["data_origin"] = wb.ARTIFICIAL
    frame = pd.DataFrame(calibration, columns=[f"wl_{v:g}" for v in w])
    frame.insert(0, "temperature_c", temperatures)
    frame.insert(1, "replicate_note", ["人工校正"] * len(frame))
    frame["data_origin"] = wb.ARTIFICIAL
    return measurement, frame, w


def settings(df, **overrides):
    columns = [c for c in df if wb.parse_wavelength(c) is not None]
    waves = sorted(wb.parse_wavelength(c) for c in columns)
    config = {"analysisEngine": "aquap2py", "pipelineMode": "modern",
              "idColumn": "sample_id", "groupColumn": "group", "wavelengthColumns": columns,
              "range": [waves[0], waves[-1]], "missing": "error", "scatter": "none",
              "smooth": False, "window": 11, "polyorder": 2, "derivative": 0,
              "pcaScale": False, "components": 2,
              "aquagramWavelengths": [1342., 1426., 1476.] if all(v in waves for v in [1342.,1426.,1476.]) else [waves[0], waves[len(waves)//2], waves[-1]],
              "aquagramReference": "global", "aquagramTolerance": 0}
    config.update(overrides)
    return config


def aq_settings(**overrides):
    config = {"enabled": True, "mode": "aucs.tn.dce", "coordinateSystem": "ot1.12",
              "temperatureColumn": "temperature_c", "calibrationSmoothN": 21,
              "tCalib": [28., 32.], "tExp": 30., "smoothN": 3, "msc": False,
              "referenceGroup": None}
    config.update(overrides)
    return config


def native_plsr(**overrides):
    config = {"enabled": True, "targetColumn": "synthetic_target", "components": 2,
              "validation": "LOO", "cvGroupColumn": None}
    config.update(overrides)
    return config


def load_calibration(frame, extension="csv", sheet="校正A"):
    if extension == "csv":
        raw = frame.to_csv(index=False).encode("utf-8-sig")
        return (*wb.inspect_calibration_bytes(raw, "人工温度校正.csv"), raw)
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="校正A", index=False)
        other = frame.copy()
        other["temperature_c"] += 10
        other.to_excel(writer, sheet_name="校正B", index=False)
    raw = stream.getvalue()
    return (*wb.inspect_calibration_bytes(raw, "人工温度校正.xlsx", sheet), raw)


def exported_csv(result, path):
    return pd.read_csv(io.StringIO(result["exports"][path]), dtype={"sample_id": str})


@pytest.mark.parametrize("extension,sheet,expected", [("csv", None, [28.,29.,30.,31.,32.]), ("xlsx", "校正B", [38.,39.,40.,41.,42.])])
def test_calibration_inspection_csv_and_selected_excel_sheet_hash_and_temperatures(data, extension, sheet, expected):
    _, frame, _ = data
    loaded, summary, raw = load_calibration(frame, extension, sheet)
    digest = hashlib.sha256(raw).hexdigest()
    assert summary["sourceSha256"] == loaded.attrs["source_sha256"] == digest
    assert loaded.attrs["source_sheet"] == summary["sheet"] == sheet
    assert summary["artificial"] is True and len(summary["wavelengthColumns"]) == 301
    assert next(c for c in summary["temperatureColumns"] if c["column"] == "temperature_c")["observedTemperatures"] == expected
    json.dumps(summary, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("change,message", [
    (lambda f: f.assign(temperature_c=30.), "2種類"),
    (lambda f: f.assign(temperature_c=[np.nan]+f.temperature_c.tolist()[1:]), "2種類"),
    (lambda f: f.drop(columns=[c for c in f if wb.parse_wavelength(c) is not None]), "波長"),
])
def test_calibration_inspection_bad_files_fail_before_analysis(data, change, message):
    _, frame, _ = data
    with pytest.raises(ValueError, match=message):
        wb.inspect_calibration_bytes(change(frame.copy()).to_csv(index=False).encode(), "invalid.csv")


@pytest.mark.parametrize("mode,unit", [("aucs", "percent"), ("aucs.tn", "percentage-point"), ("aucs.tn.dce", "degC-equivalent-deviation")])
def test_workbench_temperature_auc_labels_units_settings_export_roundtrip(data, mode, unit):
    df, frame, _ = data
    calibration, summary, _ = load_calibration(frame)
    source = {"name": summary["name"], "sheet": summary["sheet"], "sha256": summary["sourceSha256"]}
    cfg = settings(df, nativeAquagram=aq_settings(mode=mode, calibrationSource=source))
    original_cfg, original_frame = copy.deepcopy(cfg), calibration.copy(deep=True)
    result = wb.analyze(df, cfg, calibration=calibration)
    assert cfg == original_cfg
    pd.testing.assert_frame_equal(calibration, original_frame)
    aq = result["aquagram"]
    assert aq["mode"] == mode and aq["unit"] == unit
    assert aq["labels"] == [f"C{i:02d}" for i in range(1,13)]
    assert aq["coordinateRanges"][0] == [1336,1348] and aq["wavelengths"][0] == 1342
    assert all(len(g["values"]) == 12 for g in aq["groups"])
    table = exported_csv(result, "data/aquagram.csv")
    assert len(table) == len(aq["groups"]) * 12
    assert table["unit"].unique().tolist() == [unit]
    for group in aq["groups"]:
        rows = table[table["group"] == group["name"]]
        assert rows["coordinate"].tolist() == aq["labels"]
        np.testing.assert_allclose(rows["value"], group["values"], atol=1e-12)
    saved = json.loads(result["exports"]["settings.json"])
    assert saved["nativeAquagram"] == cfg["nativeAquagram"]
    assert saved["_provenance"]["requestedConfig"]["nativeAquagram"] == cfg["nativeAquagram"]
    cal = json.loads(result["exports"]["temperature_calibration.json"])
    assert cal["fileSource"]["sha256"] == source["sha256"]
    assert json.loads(result["exports"]["temperature_aquagram.json"])["labels"] == aq["labels"]
    recovered = exported_csv(result, "data/calibration_input.csv")
    assert recovered.columns.tolist() == calibration.columns.tolist()
    np.testing.assert_allclose(recovered["temperature_c"], calibration["temperature_c"])
    np.testing.assert_allclose(recovered.filter(like="wl_").to_numpy(), calibration.filter(like="wl_").to_numpy(), atol=1e-15)
    runtime = json.loads(result["exports"]["aquap2py_runtime.json"])
    assert runtime["rRequired"] is False and runtime["currentRunComparedWithR"] is False
    assert result["metadata"]["execution"]["packageApiExecuted"] is False
    assert result["metadata"]["compatibilityReport"]["completeCompatibility"] is False
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_temperature_diff_uses_named_group_even_when_basic_reference_is_none(data):
    df, frame, _ = data
    calibration, _, _ = load_calibration(frame)
    reference = df.group.iloc[0]
    cfg = settings(df, aquagramReference="none", nativeAquagram=aq_settings(mode="aucs-diff",referenceGroup=reference))
    result = wb.analyze(df, cfg, calibration=calibration)
    control = next(g for g in result["aquagram"]["groups"] if g["name"] == reference)
    np.testing.assert_allclose(control["values"], 0, atol=1e-12)
    assert result["metadata"]["settings"]["nativeAquagram"]["referenceGroup"] == reference
    with pytest.raises(ValueError, match="classic|基準なし"):
        wb.analyze(df, settings(df, aquagramReference="none"))


@pytest.mark.parametrize("change,message", [
    ({"tExp":30.1}, "LOESS"),
    ({"tCalib":[28.1,32.]}, "LOESS"),
    ({"temperatureColumn":"absent"}, "温度列"),
    ({"calibrationSource":{"name":"wrong.csv","sheet":None,"sha256":"0"*64}}, "一致"),
])
def test_temperature_missing_or_mismatched_observed_calibration_is_explicit(data, change, message):
    df, frame, _ = data
    calibration, _, _ = load_calibration(frame)
    cfg = settings(df, nativeAquagram=aq_settings(**change))
    with pytest.raises(ValueError, match=message):
        wb.analyze(df, cfg, calibration=calibration)
    with pytest.raises(ValueError, match="別ファイル"):
        wb.analyze(df, settings(df, nativeAquagram=aq_settings()))


@pytest.mark.parametrize("validation,components", [("LOO",2),("LOO",None),("group",2)])
def test_workbench_native_plsr_exports_and_processed_x_prediction_are_consistent(validation, components):
    df, _ = wb.demo_dataset()
    cfg = settings(df, scatter="snv", smooth=True,
                   nativePlsr=native_plsr(validation=validation,components=components,cvGroupColumn="group" if validation=="group" else None))
    result = wb.analyze(df, cfg)
    assert "nativePlsr" in result and "pls" not in result
    assert "pls_model.json" not in result["exports"] and "data/pls_predictions.csv" not in result["exports"]
    model = result["nativePlsr"]
    saved = json.loads(result["exports"]["native_plsr_model.json"])
    assert saved == model
    assert saved["provenance"]["validationScope"] == "native-CV-not-nested-CV"
    assert saved["ids"] == result["spectra"]["ids"]
    assert saved["targetColumn"] == "synthetic_target"
    processed = np.array(result["spectra"]["processed"])
    np.testing.assert_allclose(ap.predict_plsr(saved, processed), saved["predictedCalibration"], atol=1e-12)
    coefs = exported_csv(result, "data/native_plsr_coefficients.csv")
    np.testing.assert_array_equal(coefs["wavelength_nm"], result["spectra"]["wavelengths"])
    np.testing.assert_allclose(processed @ coefs["coefficient"].to_numpy() + saved["coefficients"]["intercept"], saved["predictedCalibration"], atol=1e-12)
    table = exported_csv(result, "data/native_plsr_predictions.csv")
    assert table.sample_id.tolist() == saved["ids"]
    for column, key in [("observed","observed"),("predicted_cv","predictedCV"),("predicted_calibration","predictedCalibration"),("residual_cv","residuals"),("fold","fold")]:
        np.testing.assert_allclose(table[column], saved[key], atol=1e-12)
    settings_json = json.loads(result["exports"]["settings.json"])
    assert settings_json["nativePlsr"] == cfg["nativePlsr"]
    assert settings_json["_provenance"]["requestedConfig"]["nativePlsr"] == cfg["nativePlsr"]
    assert json.loads(result["exports"]["aquap2py_runtime.json"])["nativePlsr"] == saved["provenance"]
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_existing_nested_pls_and_native_plsr_are_distinct_and_cannot_mix():
    df, _ = wb.demo_dataset()
    nested = {"enabled":True,"targetColumn":"synthetic_target","maxComponents":2,"folds":3,
              "split":"kfold","cvGroupColumn":None,"seed":17,"scale":False}
    result = wb.analyze(df, settings(df,analysisEngine="python",pls=nested))
    assert result["pls"]["method"] == "nested-kfold" and "nativePlsr" not in result
    assert "pls_model.json" in result["exports"] and "native_plsr_model.json" not in result["exports"]
    with pytest.raises(ValueError, match="別|PLS"):
        wb.analyze(df, settings(df,pls=nested,nativePlsr=native_plsr()))


def test_package_public_gdmm_and_getcm_expose_independent_native_models_and_copies(data):
    df, _ = wb.demo_dataset()
    columns = [c for c in df if wb.parse_wavelength(c) is not None]
    w = [wb.parse_wavelength(c) for c in columns]
    ds = ap.SpectralData(df[columns].to_numpy(), w, df.sample_id.tolist(), df.group.tolist())
    cube = ap.gdmm(ds,components=2,aquagram_wavelengths=[w[0],w[20],w[40]],
                   plsr={"y":df.synthetic_target.to_numpy(),"ncomp":2,"validation":"LOO"})
    model = ap.getcm(cube,"plsr")
    assert model == cube["plsr"] and "plsr" in cube["provenance"]["supportedModels"]
    model["coefficients"]["values"][0] += 100
    assert model != cube["plsr"]
    assert ap.getcm(cube,"pca") == cube["pca"]
    measurement, calibration, waves = data
    cal = ap.temperature_calibration(calibration.filter(like="wl_").to_numpy(),waves,calibration.temperature_c.to_numpy())
    temperature_cube = ap.gdmm(ap.SpectralData(measurement.filter(like="wl_").to_numpy(),waves,measurement.sample_id.tolist(),measurement.group.tolist()),
        components=2,aquagram_wavelengths=[1342,1426,1476],temperature={"calibration":cal,"mode":"aucs","t_calib":[28,32],"t_exp":30,"smooth_n":3})
    assert ap.getcm(temperature_cube,"aquagram")["mode"] == "aucs"
    assert "aucs" in temperature_cube["provenance"]["supportedModels"]


def test_temperature_aquagram_and_native_plsr_can_share_one_workbench_run(data):
    df, frame, _ = data
    df = df.copy(deep=True)
    columns = [c for c in df if wb.parse_wavelength(c) is not None]
    # Small independent artificial noise avoids the exact low-rank thermal
    # construction, which the PLS modelPlus rank guard intentionally rejects.
    df.loc[:,columns] += np.random.default_rng(339).normal(0,1e-6,(len(df),len(columns)))
    df["target"] = np.linspace(1.,4.,len(df))
    calibration, _, _ = load_calibration(frame)
    cfg = settings(df,nativeAquagram=aq_settings(mode="aucs"),nativePlsr=native_plsr(targetColumn="target",components=1))
    result = wb.analyze(df,cfg,calibration=calibration)
    assert result["aquagram"]["mode"] == "aucs" and result["nativePlsr"]["algorithm"] == "kernelpls"
    assert "temperature_calibration.json" in result["exports"] and "native_plsr_model.json" in result["exports"]
    assert result["nativePlsr"]["ids"] == result["spectra"]["ids"]
    np.testing.assert_allclose(ap.predict_plsr(result["nativePlsr"],result["spectra"]["processed"]),result["nativePlsr"]["predictedCalibration"],atol=1e-11)


@pytest.mark.parametrize("mode,methods", [("modern",["snv","sgolay"]),("legacy-python",["sgolay","snv"])])
def test_pipeline_order_settings_match_native_processed_x_used_for_plsr(mode, methods):
    df, _ = wb.demo_dataset()
    cfg = settings(df,pipelineMode=mode,scatter="snv",smooth=True,nativePlsr=native_plsr(components=1))
    result = wb.analyze(df,cfg)
    steps = {"snv":{"method":"snv"},"sgolay":{"method":"sgolay","window":11,"polyorder":2,"derivative":0,"delta":1}}
    expected = ap.preprocess(np.array(result["spectra"]["raw"]),[steps[k] for k in methods])
    np.testing.assert_allclose(result["spectra"]["processed"],expected,atol=1e-13)
    provenance = json.loads(result["exports"]["settings.json"])["_provenance"]
    assert provenance["pipeline"] == methods
    assert provenance["requestedConfig"]["pipelineMode"] == mode
    assert provenance["order"][-1] == "native-plsr"


def test_same_excel_file_wrong_sheet_identity_refused(data):
    df, frame, _ = data
    calibration, summary, raw = load_calibration(frame,"xlsx","校正A")
    cfg = settings(df,nativeAquagram=aq_settings(calibrationSource={"name":summary["name"],"sheet":"校正B","sha256":hashlib.sha256(raw).hexdigest()}))
    with pytest.raises(ValueError,match="シート.*一致|一致"):
        wb.analyze(df,cfg,calibration=calibration)


@pytest.mark.parametrize("change,message", [
    ({"targetColumn":"sample_id"},"目的変数"),
    ({"targetColumn":"wl_1450"},"目的変数"),
    ({"validation":"group","cvGroupColumn":"synthetic_target"},"CV群"),
    ({"components":31},"30以下"),
])
def test_native_plsr_table_column_contract_guards(change, message):
    df, _ = wb.demo_dataset()
    with pytest.raises(ValueError,match=message):
        wb.analyze(df,settings(df,nativePlsr=native_plsr(**change)))

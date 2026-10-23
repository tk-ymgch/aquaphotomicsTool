"""UI-contract integration: preserve spectra rows while PLSR filters rows."""
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


def fixture():
    spec = importlib.util.spec_from_file_location("plsr_extended_fixture", ROOT / "tests/test_plsr_extended.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    x, y, groups = module.fixture()
    waves = np.linspace(1300, 1600, x.shape[1])
    frame = pd.DataFrame(x, columns=[f"wl_{v:g}" for v in waves])
    frame.insert(0, "sample_id", [f"original-{i:03d}" for i in range(len(y))])
    frame.insert(1, "group", groups)
    frame["target"] = y
    config = {"analysisEngine":"aquap2py", "idColumn":"sample_id", "groupColumn":"group",
        "wavelengthColumns":[c for c in frame if c.startswith("wl_")], "range":[1300,1600],
        "missing":"error", "scatter":"none", "smooth":False, "window":3, "polyorder":2,
        "derivative":0, "components":2, "pcaScale":False,
        "aquagramWavelengths":waves[[1,8,15]].tolist(), "aquagramTolerance":0,
        "aquagramReference":"global", "nativePlsr":{"enabled":True,"targetColumn":"target",
        "components":2,"validation":"LOO","cvGroupColumn":None,"excludeOutliers":True,"outlierRange":0.5}}
    return frame, config


@pytest.mark.parametrize("validation", ["LOO", "group"])
def test_exclusions_keep_original_ids_and_prediction_export_rows(validation):
    frame, config = fixture()
    config["nativePlsr"].update(validation=validation, cvGroupColumn="group" if validation=="group" else None)
    result = wb.analyze(frame, config)
    native = result["nativePlsr"]
    retained, excluded = native["retainedIndices"], native["excludedIndices"]
    assert 3 in excluded and len(retained) < len(frame)
    assert len(result["spectra"]["ids"]) == len(result["pca"]["ids"]) == len(frame)
    assert sum(g["n"] for g in result["aquagram"]["groups"]) == len(frame)
    assert native["ids"] == frame.sample_id.iloc[retained].tolist()
    assert native["excludedIds"] == frame.sample_id.iloc[excluded].tolist()
    table = pd.read_csv(io.StringIO(result["exports"]["data/native_plsr_predictions.csv"]))
    assert table.sample_id.tolist() == native["ids"]
    np.testing.assert_allclose(table.predicted_cv, native["predictedCV"], atol=1e-12)
    removed = pd.read_csv(io.StringIO(result["exports"]["data/native_plsr_exclusions.csv"]))
    assert removed.original_row_index.tolist() == excluded
    assert removed.sample_id.tolist() == native["excludedIds"]
    assert json.loads(result["exports"]["settings.json"])["nativePlsr"] == config["nativePlsr"]


def test_detrend_is_applied_before_existing_steps_and_recorded():
    frame, config = fixture()
    config.update(nativePreprocessing={"detrend":True}, scatter="snv")
    config["nativePlsr"]["enabled"] = False
    result = wb.analyze(frame, config)
    spectrum = result["spectra"]
    expected = ap.preprocess_spectra(spectrum["raw"], spectrum["wavelengths"], [{"method":"detrend"},{"method":"snv"}])
    np.testing.assert_allclose(spectrum["processed"], expected["matrix"], atol=1e-12)
    settings = json.loads(result["exports"]["settings.json"])
    assert settings["nativePreprocessing"] == {"detrend":True}
    assert settings["_provenance"]["pipeline"] == ["detrend","snv"]
    assert result["metadata"]["compatibilityReport"]["completeCompatibility"] is False


def test_invalid_extra_processing_and_outlier_settings_stop():
    frame, config = fixture()
    for value in ({"detrend":"true"}, {"detrend":True,"resample":2}):
        with pytest.raises(ValueError, match="追加前処理"):
            wb.analyze(frame, {**config,"nativePreprocessing":value})
    config["nativePlsr"]["outlierRange"] = -1
    with pytest.raises(ValueError, match="外れ値範囲"):
        wb.analyze(frame, config)

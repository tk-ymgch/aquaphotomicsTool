"""Numerical and file-contract regression tests; run with python -m pytest."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("workbench", ROOT / "python" / "workbench.py")
wb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wb)


def frame(matrix=None, wavelengths=(1300, 1305, 1310)):
    if matrix is None:
        matrix = [[1, 2, 3], [3, 4, 5], [5, 6, 7], [7, 8, 9]]
    df = pd.DataFrame(matrix, columns=[f"wl_{wl:g}" for wl in wavelengths])
    df.insert(0, "group", ["A" if i < len(df) / 2 else "B" for i in range(len(df))])
    df.insert(0, "sample_id", [f"ID-{i + 1}" for i in range(len(df))])
    return df


def config(df, **overrides):
    waves = [(wb.parse_wavelength(column), column) for column in df if wb.parse_wavelength(column) is not None]
    waves.sort()
    values = [item[0] for item in waves]
    settings = {
        "idColumn": "sample_id", "groupColumn": "group",
        "wavelengthColumns": [item[1] for item in waves], "range": [values[0], values[-1]],
        "missing": "error", "scatter": "none", "smooth": False, "window": 3,
        "polyorder": 2, "derivative": 0, "pcaScale": False, "components": 2,
        "aquagramWavelengths": [values[0], values[len(values) // 2], values[-1]],
        "aquagramReference": "global", "aquagramTolerance": 0,
    }
    settings.update(overrides)
    return settings


def test_demo_is_deterministic_and_always_marked_artificial():
    df, summary = wb.demo_dataset()
    again, _ = wb.demo_dataset()
    pd.testing.assert_frame_equal(df, again)
    assert df.shape == (45, 65)
    assert len(summary["wavelengthColumns"]) == 61
    assert "人工" in summary["name"]
    assert summary["artificial"] is True
    assert set(df["data_origin"]) == {wb.ARTIFICIAL}
    result = wb.analyze(df, config(df, scatter="snv", smooth=True, window=11))
    assert "人工" in result["exports"]["README.txt"]
    assert any("人工" in warning for warning in result["metadata"]["warnings"])
    assert json.loads(result["exports"]["settings.json"])["_provenance"]["source"]["artificial"] is True
    # Strict JSON serializability is the Web Worker transfer contract.
    json.dumps(result, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp932"])
def test_csv_round_trip_japanese_and_wavelength_detection(encoding):
    text = "sample_id,group,wl_1450,1455 nm,nm_1460,sample_001,temperature_c\n試料1,対照,1,2,3,4,25\n試料2,処理,2,3,4,5,26\n"
    df, summary = wb.inspect_bytes(text.encode(encoding), "日本語.csv")
    assert summary["suggestedId"] == "sample_id"
    assert summary["suggestedGroup"] == "group"
    assert [item["wavelength"] for item in summary["wavelengthColumns"]] == [1450, 1455, 1460]
    assert summary["preview"][0][0] == "試料1"
    assert summary["sheet"] is None
    assert summary["artificial"] is False
    assert df.attrs["source_name"] == "日本語.csv"


def test_excel_sheet_selection_and_preview_are_json_compatible():
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        frame().to_excel(writer, sheet_name="実験A", index=False)
        frame([[10, 20, 30], [40, 50, 60]]).to_excel(writer, sheet_name="実験B", index=False)
    data = stream.getvalue()
    _, first = wb.inspect_bytes(data, "book.xlsx")
    second_df, second = wb.inspect_bytes(data, "book.xlsx", "実験B")
    assert first["sheets"] == ["実験A", "実験B"]
    assert first["sheet"] == "実験A"
    assert second["sheet"] == "実験B"
    assert second_df.iloc[0]["wl_1300"] == 10
    assert second["rowCount"] == 2
    json.dumps(second, allow_nan=False)
    with pytest.raises(ValueError, match="シート.*見つかりません"):
        wb.inspect_bytes(data, "book.xlsx", "存在しないシート")


@pytest.mark.parametrize("data, message", [
    (b"id,wl_1300,wl_1300\na,1,2\n", "重複"),
    (b"id,,wl_1300\na,1,2\n", "空欄"),
    (b"id,wl_1300\na,1,2\n", "列数"),
    (b"id,wl_1300\n", "データ行"),
    (b"", "空"),
])
def test_invalid_csv_is_rejected_before_analysis(data, message):
    with pytest.raises(ValueError, match=message):
        wb.inspect_bytes(data, "invalid.csv")


def test_snv_and_msc_match_known_affine_spectra():
    vector = np.array([1.0, 2.0, 4.0, 8.0])
    x = np.array([vector, vector * 2 + 3, vector * 0.5 - 2])
    snv = wb._scatter_correct(x, "snv")
    expected = (vector - vector.mean()) / vector.std(ddof=0)
    np.testing.assert_allclose(snv, np.tile(expected, (3, 1)), atol=1e-12)
    np.testing.assert_allclose(snv.mean(axis=1), 0, atol=1e-12)
    np.testing.assert_allclose(snv.std(axis=1), 1, atol=1e-12)
    # Regressing each affine spectrum on their mean must remove both effects.
    msc = wb._scatter_correct(x, "msc")
    np.testing.assert_allclose(msc, np.tile(x.mean(axis=0), (3, 1)), atol=1e-12)
    with pytest.raises(ValueError, match="一定値"):
        wb._scatter_correct(np.ones((3, 4)), "snv")
    with pytest.raises(ValueError, match="一定値"):
        wb._scatter_correct(np.ones((3, 4)), "msc")


@pytest.mark.parametrize("derivative", [1, 2])
def test_sg_derivative_uses_nm_spacing_including_edges(derivative):
    wl = np.arange(1300.0, 1342.0, 2.0)
    centered = wl - 1320
    coefficients = np.array([1.0, 1.5, 2.0, 2.5])
    x = np.array([a * centered ** 2 + 0.3 * centered + 4 for a in coefficients])
    df = frame(x, wl)
    result = wb.analyze(df, config(df, derivative=derivative, smooth=False, window=7, polyorder=2))
    expected = np.array([2 * a * centered + 0.3 for a in coefficients]) if derivative == 1 else np.tile(2 * coefficients[:, None], (1, len(wl)))
    np.testing.assert_allclose(result["spectra"]["processed"], expected, atol=1e-10)
    np.testing.assert_array_equal(result["spectra"]["wavelengths"], wl)


def test_irregular_grid_is_interpolated_explicitly_before_sg():
    wl = np.array([1300.0, 1303.0, 1310.0])
    slopes = np.array([1.0, 2.0, 3.0, 4.0])
    df = frame([slope * (wl - 1300) + 5 for slope in slopes], wl)
    result = wb.analyze(df, config(df, derivative=1, window=3, polyorder=1,
                                   aquagramWavelengths=[1300, 1305, 1310]))
    np.testing.assert_allclose(result["spectra"]["wavelengths"], [1300, 1305, 1310])
    np.testing.assert_allclose(result["spectra"]["processed"], np.tile(slopes[:, None], (1, 3)), atol=1e-12)
    np.testing.assert_allclose(result["spectra"]["raw"], [slope * np.array([0, 5, 10]) + 5 for slope in slopes])
    assert any("等間隔" in warning for warning in result["metadata"]["warnings"])
    saved = json.loads(result["exports"]["settings.json"])
    assert saved["_provenance"]["originalWavelengths"] == [1300, 1303, 1310]
    assert saved["_provenance"]["interpolated"] is True


def test_pca_known_rank_one_reconstructs_centered_data_and_caps_components():
    direction = np.array([1.0, 2.0, 3.0])
    x = np.outer([-2.0, -1.0, 1.0, 2.0], direction) + [7, 10, -3]
    df = frame(x)
    result = wb.analyze(df, config(df, components=99))
    scores = np.array(result["pca"]["scores"])
    loadings = np.array(result["pca"]["loadings"])
    assert scores.shape == (4, 3)
    assert loadings.shape == (3, 3)
    assert result["metadata"]["settings"]["components"] == 3
    np.testing.assert_allclose(scores @ loadings.T, x - x.mean(axis=0), atol=1e-12)
    np.testing.assert_allclose(abs(loadings[:, 0]), direction / np.linalg.norm(direction), atol=1e-12)
    np.testing.assert_allclose(result["pca"]["explainedVariance"][0], 1.0, atol=1e-12)
    two = frame([[1, 2, 3], [4, 6, 8]])
    assert wb.analyze(two, config(two))["metadata"]["settings"]["components"] == 1


def test_scaled_pca_matches_standardized_covariance_eigenvalues():
    df = frame([[1, 20, 0.5], [2, 10, 0.7], [4, 40, 0.4], [7, 30, 0.9]])
    result = wb.analyze(df, config(df, pcaScale=True, components=3))
    x = df.iloc[:, 2:].to_numpy(dtype=float)
    standardized = (x - x.mean(axis=0)) / x.std(axis=0, ddof=0)
    eigenvalues = np.linalg.eigvalsh(np.cov(standardized, rowvar=False))[::-1]
    np.testing.assert_allclose(result["pca"]["explainedVariance"], eigenvalues / eigenvalues.sum(), atol=1e-12)


def test_aquagram_global_and_control_group_match_hand_calculation():
    df = frame()
    x = df.iloc[:, 2:].to_numpy(dtype=float)
    result = wb.analyze(df, config(df))
    aq = result["aquagram"]
    for group_index, rows in enumerate((x[:2], x[2:])):
        expected = (rows.mean(axis=0) - x.mean(axis=0)) / x.std(axis=0, ddof=0)
        np.testing.assert_allclose(aq["groups"][group_index]["values"], expected)
        assert aq["groups"][group_index]["n"] == 2
    assert aq["labels"] == ["1300 nm", "1305 nm", "1310 nm"]
    assert "ddof=0" in aq["definition"]
    control = wb.analyze(df, config(df, aquagramReference="A"))["aquagram"]
    np.testing.assert_allclose(control["groups"][0]["values"], 0)
    np.testing.assert_allclose(control["groups"][1]["values"], (x[2:].mean(axis=0) - x[:2].mean(axis=0)) / x.std(axis=0))
    assert control["reference"] == "対照群: A"


@pytest.mark.parametrize("reserved_name", ["global", "Global mean", "全体平均", "group:global"])
def test_explicit_group_reference_disambiguates_reserved_group_names(reserved_name):
    df = frame()
    df["group"] = [reserved_name, reserved_name, "処理群", "処理群"]
    explicit = f"group:{reserved_name}"
    result = wb.analyze(df, config(df, aquagramReference=explicit))
    np.testing.assert_allclose(result["aquagram"]["groups"][0]["values"], 0)
    assert result["aquagram"]["reference"] == f"対照群: {reserved_name}"
    assert result["metadata"]["settings"]["aquagramReference"] == explicit
    assert json.loads(result["exports"]["settings.json"])["aquagramReference"] == explicit
    global_result = wb.analyze(df, config(df, aquagramReference="global"))
    assert np.all(np.array(global_result["aquagram"]["groups"][0]["values"]) < 0)
    with pytest.raises(ValueError, match="対照群.*見つかりません"):
        wb.analyze(df, config(df, aquagramReference="group:存在しない群"))


def test_missing_policy_uses_column_median_and_never_fills_empty_column_with_zero():
    df = frame([[1, 2, 3], [np.nan, 4, 5], [5, 6, 7], [9, 8, 9]])
    with pytest.raises(ValueError, match="欠損"):
        wb.analyze(df, config(df))
    result = wb.analyze(df, config(df, missing="median"))
    assert result["spectra"]["raw"][1][0] == 5
    provenance = json.loads(result["exports"]["settings.json"])["_provenance"]
    assert provenance["imputed"]["wl_1300"] == {"count": 1, "median": 5}
    df["wl_1300"] = np.nan
    with pytest.raises(ValueError, match="有効な数値"):
        wb.analyze(df, config(df, missing="median"))


def test_duplicate_ids_require_explicit_row_number_selection_and_preserve_source():
    df = frame()
    df.loc[1, "sample_id"] = df.loc[0, "sample_id"]
    with pytest.raises(ValueError, match="試料IDが重複.*行番号を使用"):
        wb.analyze(df, config(df))
    result = wb.analyze(df, config(df, idColumn=None))
    assert result["spectra"]["ids"] == ["S001", "S002", "S003", "S004"]
    original = pd.read_csv(io.StringIO(result["exports"]["data/input.csv"]))
    assert original.loc[0, "sample_id"] == original.loc[1, "sample_id"]


@pytest.mark.parametrize("overrides, message", [
    ({"smooth": True, "window": 4}, "SG窓幅"),
    ({"smooth": True, "window": 5}, "SG窓幅"),
    ({"smooth": True, "polyorder": 3}, "SG多項式"),
    ({"derivative": 2, "polyorder": 1}, "SG多項式"),
    ({"range": [1306, 1310]}, "3列以上"),
    ({"aquagramWavelengths": [1299, 1305, 1310], "aquagramTolerance": 100}, "範囲外"),
    ({"aquagramWavelengths": [1300, 1304, 1310]}, "許容誤差"),
    ({"aquagramWavelengths": [1300, 1301, 1310], "aquagramTolerance": 2}, "同じ測定波長"),
    ({"aquagramReference": "ない群"}, "対照群"),
    ({"components": 1.5}, "整数"),
])
def test_invalid_scientific_settings_are_actionable(overrides, message):
    df = frame()
    with pytest.raises(ValueError, match=message):
        wb.analyze(df, config(df, **overrides))


def test_duplicate_wavelengths_zero_variance_and_memory_limit_fail_explicitly():
    df = frame()
    df["nm_1300"] = df["wl_1300"]
    with pytest.raises(ValueError, match="同じ波長"):
        wb.analyze(df, config(df))
    constant = frame(np.ones((4, 3)))
    with pytest.raises(ValueError, match="変動.*0"):
        wb.analyze(constant, config(constant))
    # A compact broadcast-backed input avoids constructing the result matrices.
    big = pd.DataFrame(np.broadcast_to(np.arange(3), (666_667, 3)), columns=["wl_1300", "wl_1305", "wl_1310"])
    with pytest.raises(ValueError, match="200万要素"):
        wb.analyze(big, {**config(frame()), "idColumn": None, "groupColumn": None})


def test_variable_count_limit_is_independent_of_matrix_element_limit():
    df = pd.DataFrame(np.ones((2, 10_001)), columns=[f"wl_{i}" for i in range(1, 10_002)])
    settings = config(df, idColumn=None, groupColumn=None)
    assert df.size < wb.MAX_MATRIX_ELEMENTS
    with pytest.raises(ValueError, match="波長数は1万列まで"):
        wb.analyze(df, settings)
    with pytest.raises(ValueError, match="波長数は1万列まで"):
        wb.inspect_bytes(df.to_csv(index=False).encode("utf-8"), "too_many_wavelengths.csv")


def test_exports_match_applied_settings_and_analysis_does_not_mutate_inputs():
    df = frame()
    original = df.copy(deep=True)
    settings = config(df, components=20, aquagramWavelengths=[1300, 1304, 1310], aquagramTolerance=1)
    original_settings = copy.deepcopy(settings)
    result = wb.analyze(df, settings)
    pd.testing.assert_frame_equal(df, original)
    assert settings == original_settings
    exports = result["exports"]
    assert all(isinstance(value, str) for value in exports.values())
    processed = pd.read_csv(io.StringIO(exports["data/preprocessed.csv"]))
    np.testing.assert_allclose(processed.iloc[:, 2:], result["spectra"]["processed"])
    saved = json.loads(exports["settings.json"])
    assert saved["components"] == 3
    assert saved["aquagramWavelengths"] == [1300, 1305, 1310]
    assert saved["_provenance"]["requestedConfig"]["aquagramWavelengths"] == [1300, 1304, 1310]
    assert saved["_provenance"]["aquagramMappings"][1] == {"requested": 1304, "actual": 1305, "difference": 1}
    assert "data/input.csv" in exports
    assert "分子種" in exports["README.txt"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_artificial_fixtures_can_be_reimported_and_identified(suffix):
    path = ROOT / "samples" / f"synthetic_spectra.{suffix}"
    df, summary = wb.inspect_bytes(path.read_bytes(), path.name)
    assert summary["rowCount"] == 45
    assert "人工" in summary["name"]
    assert summary["artificial"] is True
    assert wb._is_artificial(df)


def test_artificial_flag_uses_data_origin_not_filename_or_ui_action():
    measured = frame().to_csv(index=False).encode("utf-8")
    _, real_summary = wb.inspect_bytes(measured, "人工という名前を含むだけ.csv")
    assert real_summary["artificial"] is False
    artificial, _ = wb.demo_dataset()
    _, imported_summary = wb.inspect_bytes(artificial.to_csv(index=False).encode("utf-8"), "renamed.csv")
    assert imported_summary["artificial"] is True


def test_inspection_and_demo_do_not_import_analysis_dependencies():
    script = r'''
import builtins, importlib.util
original_import = builtins.__import__
def import_without_analysis(name, *args, **kwargs):
    if name.split('.')[0] in {'scipy', 'sklearn'}:
        raise ImportError('analysis dependencies deliberately unavailable')
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_analysis
spec = importlib.util.spec_from_file_location('wb', 'python/workbench.py')
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)
df, summary = wb.demo_dataset()
assert summary['rowCount'] == 45
data = df.to_csv(index=False).encode('utf-8')
assert wb.inspect_bytes(data, 'artificial.csv')[1]['rowCount'] == 45
'''
    completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_xls_fixture_when_reader_is_available():
    pytest.importorskip("xlrd", reason="通常Pythonにxlrdがない場合はXLS読込テストのみ省略")
    path = ROOT / "samples" / "synthetic_spectra.xls"
    df, summary = wb.inspect_bytes(path.read_bytes(), path.name, "人工スペクトル")
    assert summary["rowCount"] == 45
    assert summary["sheet"] == "人工スペクトル"
    assert summary["artificial"] is True
    assert len(summary["wavelengthColumns"]) == 61
    result = wb.analyze(df, config(df, scatter="snv", smooth=True, window=11))
    json.dumps(result, allow_nan=False)

"""Synthetic regressions for spectrometer exports with an unnamed ID column.

No participant records or original measurement files are included here.
"""
from __future__ import annotations

import importlib.util
import csv
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("import_compat_workbench", ROOT / "python" / "workbench.py")
wb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wb)


def spectral_frame(ids=None):
    """An artificial, varying matrix with three actual wavelength labels."""
    return pd.DataFrame({
        "": ["ARTIFICIAL-A", "ARTIFICIAL-B", "ARTIFICIAL-C", "ARTIFICIAL-D"] if ids is None else ids,
        "1300": [1.0, 1.5, 2.0, 2.5],
        "1350": [1.2, 1.4, 2.2, 2.7],
        "1400": [2.0, 2.4, 2.6, 3.0],
        "note": ["synthetic"] * 4,
    })


def assert_id_repair(loaded, summary, original, *, excel=False):
    assigned = summary["suggestedId"]
    assert assigned
    assert assigned == loaded.columns[0]
    assert loaded.columns.is_unique
    adjustment = loaded.attrs["import_adjustments"][0]
    assert adjustment["columnIndex"] == 0
    assert adjustment["assignedHeader"] == assigned
    assert adjustment["reason"] == "unnamed-leading-sample-column"
    assert summary["importNotes"]
    assert summary["dataKind"] == "spectra"
    assert len(summary["wavelengthColumns"]) == 3
    # Excel's existing reader may represent numeric headings as "1300.0" and
    # values as object dtype. Neither changes the physical wavelength or value.
    if excel:
        for actual, expected in zip(loaded.columns[1:], original.columns[1:]):
            assert actual == expected or (
                wb.parse_wavelength(actual) is not None
                and wb.parse_wavelength(actual) == wb.parse_wavelength(expected)
            )
        pd.testing.assert_frame_equal(loaded.set_axis(original.columns, axis=1), original, check_dtype=False)
    else:
        # Preserve the textual ID representation (including leading zeros).
        # Measurement and metadata values retain their normal CSV inference.
        assert loaded.iloc[:, 0].tolist() == original.iloc[:, 0].astype(str).tolist()
        pd.testing.assert_frame_equal(loaded.iloc[:, 1:], original.iloc[:, 1:])


@pytest.mark.parametrize("ids", [None, [0, 1, 2, 3], ["001", "002", "003", "004"], ["NA", "N/A", "null", "NULL"]],
                         ids=["text-identifiers", "numeric-index", "leading-zero-identifiers", "na-literal-identifiers"])
def test_csv_unnamed_leading_column_is_retained_and_suggested_as_id(ids):
    original = spectral_frame(ids)
    loaded, summary = wb.inspect_bytes(original.to_csv(index=False).encode("utf-8-sig"), "synthetic.csv")
    assert_id_repair(loaded, summary, original)


@pytest.mark.parametrize("ids", [None, ["001", "002", "003", "004"]],
                         ids=["text-identifiers", "leading-zero-identifiers"])
def test_excel_unnamed_leading_column_preserves_identifiers_and_spectra(ids):
    original = spectral_frame(ids)
    stream = io.BytesIO()
    original.to_excel(stream, index=False, sheet_name="Synthetic", engine="openpyxl")
    loaded, summary = wb.inspect_bytes(stream.getvalue(), "synthetic.xlsx", "Synthetic")
    assert_id_repair(loaded, summary, original, excel=True)
    assert summary["sheet"] == "Synthetic"


def test_generated_id_header_does_not_overwrite_an_existing_sample_id():
    original = spectral_frame()
    original["sample_id"] = ["META-A", "META-B", "META-C", "META-D"]
    loaded, summary = wb.inspect_bytes(original.to_csv(index=False).encode(), "collision.csv")
    assert summary["suggestedId"] != "sample_id"
    assert_id_repair(loaded, summary, original)
    assert loaded["sample_id"].tolist() == original["sample_id"].tolist()


@pytest.mark.parametrize("text,message", [
    ("id,1300,,1350,1400\na,1,2,3,4\n", "空欄"),
    (",1300,,1350,1400\na,1,2,3,4\n", "空欄"),
    (",1300,1350,1400,1400\na,1,2,3,4\n", "重複"),
    (",Time,HMD_Position_x\na,1,2\n", "空欄"),
])
def test_repair_is_limited_to_one_leading_blank_in_a_spectral_table(text, message):
    with pytest.raises(ValueError, match=message):
        wb.inspect_bytes(text.encode(), "invalid.csv")


def test_named_spectral_headers_are_unchanged_and_have_no_repair_notice():
    original = spectral_frame().rename(columns={"": "specimen"})
    loaded, summary = wb.inspect_bytes(original.to_csv(index=False).encode(), "named.csv")
    pd.testing.assert_frame_equal(loaded, original)
    assert not loaded.attrs.get("import_adjustments")
    assert not summary.get("importNotes")
    assert summary["dataKind"] == "spectra"


def test_unity_motion_and_eye_log_is_identified_without_inventing_wavelengths():
    text = "Time,HMD_Position_x,Left_Pupil_Diameter\n0.1,0.2,3.0\n0.2,0.3,3.1\n"
    loaded, summary = wb.inspect_bytes(text.encode(), "synthetic-unity.csv")
    assert loaded.shape == (2, 3)
    assert summary["dataKind"] == "unity-log"
    assert summary["wavelengthColumns"] == []
    assert not loaded.attrs.get("import_adjustments")


@pytest.mark.parametrize("header", [
    "Time,HMD_Position_x,other",
    "Time,other,Left_Pupil_Diameter",
    "temperature,replicate,signal",
])
def test_other_tables_are_not_misidentified_as_unity_or_spectra(header):
    _, summary = wb.inspect_bytes((header + "\n1,2,3\n2,3,4\n").encode(), "table.csv")
    assert summary["dataKind"] == "table"
    assert summary["wavelengthColumns"] == []


@pytest.mark.parametrize("engine", ["python", "aquap2py"])
def test_import_adjustment_is_saved_as_provenance_without_becoming_an_analysis_setting(engine):
    original = spectral_frame(["001", "002", "003", "004"])
    loaded, summary = wb.inspect_bytes(original.to_csv(index=False).encode(), "synthetic.csv")
    settings = {
        "idColumn": summary["suggestedId"], "groupColumn": None,
        "wavelengthColumns": [item["column"] for item in summary["wavelengthColumns"]],
        "range": [1300, 1400], "pipelineMode": "modern", "analysisEngine": engine,
        "missing": "error", "scatter": "none", "smooth": False, "window": 3,
        "polyorder": 2, "derivative": 0, "pcaScale": False, "components": 2,
        "aquagramWavelengths": [1300, 1350, 1400], "aquagramReference": "global",
        "aquagramTolerance": 0,
    }
    result = wb.analyze(loaded, settings)
    saved = json.loads(result["exports"]["settings.json"])
    assert saved["_provenance"]["source"]["importAdjustments"] == loaded.attrs["import_adjustments"]
    assert "importAdjustments" not in saved
    assert "importNotes" not in saved
    assert "importAdjustments" not in result["metadata"]["settings"]
    assert result["spectra"]["ids"] == original.iloc[:, 0].tolist()
    saved_input = list(csv.reader(io.StringIO(result["exports"]["data/input.csv"])))
    assert [row[0] for row in saved_input[1:]] == original.iloc[:, 0].tolist()
    np.testing.assert_array_equal(result["spectra"]["raw"], original[["1300", "1350", "1400"]].to_numpy())
    json.dumps(result, ensure_ascii=False, allow_nan=False)

"""Bounded temperature-calibrated Aquagrams from aquap2 0.4.5 definitions.

Observed calibration values use aquap2's exact-value shortcuts. Unobserved
values use a bounded implementation of R's default robust quadratic LOESS.
No R process, arbitrary expression, or hidden calibration data is used.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import numpy as np

from .core import REFERENCE_COMMIT, VERSION, _labels, _vector
from .preprocessing import _finite_result, _matrix, msc as apply_msc, sgolay
from .loess import robust_quadratic_loess

_BANDS12 = ((1336, 1348), (1360, 1366), (1370, 1376), (1380, 1388),
            (1398, 1418), (1422, 1430), (1432, 1444), (1448, 1454),
            (1458, 1468), (1472, 1481), (1482, 1495), (1506, 1516))
_BANDS15 = _BANDS12[:4] + ((1392, 1398), (1402, 1409), (1410, 1412), (1414, 1420)) + _BANDS12[5:]
_NAMES12 = tuple(f"C{i:02d}" for i in range(1, 13))
_NAMES15 = _NAMES12[:4] + ("C05a", "C05b", "C05c", "C05d") + _NAMES12[5:]
_DEFAULT_TARGETS = (1342, 1364, 1374, 1384, 1412, 1426, 1440, 1452, 1462, 1476, 1488, 1512)
_SYSTEMS = {"ot1.12": (_BANDS12, _NAMES12), "ot1.15": (_BANDS15, _NAMES15)}
_MODES = {"sfc", "sfc-diff", "aucs", "aucs-diff", "aucs.tn", "aucs.tn-diff",
          "aucs.tn.dce", "aucs.tn.dce-diff", "aucs.dce", "aucs.dce-diff"}


def _finite_scalar(value: Any, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or not np.isfinite(value):
        raise ValueError(f"{name}は有限の数値にしてください。")
    return float(value)


def _system(name: str):
    if not isinstance(name, str) or name not in _SYSTEMS:
        raise ValueError("座標系はot1.12またはot1.15にしてください。")
    return _SYSTEMS[name]


def _temperatures(value: Any, n: int) -> np.ndarray:
    raw = np.asarray(value)
    if raw.dtype.kind not in "iuf" or raw.shape != (n,):
        raise ValueError("校正温度は校正試料数と同じ長さの数値ベクトルにしてください。")
    result = np.array(raw, dtype=float, copy=True)
    if not np.isfinite(result).all():
        raise ValueError("校正温度に欠損値・非有限値があります。")
    return result


def _polygon_area(x: np.ndarray, y: np.ndarray) -> float:
    # geometry::polyarea uses the unsigned cyclic shoelace expression.
    return float(abs(np.sum(x * (np.roll(y, -1) - np.roll(y, 1)))) / 2)


def _auc_table(matrix: np.ndarray, wavelengths: np.ndarray, bands) -> tuple[np.ndarray, list[list[float]]]:
    selections = []
    actual = []
    for low, high in bands:
        indices = np.flatnonzero((wavelengths >= low) & (wavelengths <= high))
        if not len(indices):
            raise ValueError(f"AUC帯{low}〜{high} nmに測定波長がありません。")
        selections.append(indices)
        actual.append([float(wavelengths[indices[0]]), float(wavelengths[indices[-1]])])
    out = np.empty((len(matrix), len(bands)))
    for i, row in enumerate(matrix):
        full_area = _polygon_area(np.r_[wavelengths, wavelengths[0]], np.r_[row, row[0]])
        numerical_floor = (np.max(np.abs(row)) * (wavelengths[-1] - wavelengths[0])
                           * np.finfo(float).eps * len(wavelengths) * 64)
        if full_area <= numerical_floor or not np.isfinite(full_area):
            raise ValueError("AUCの全スペクトル多角形面積が0または非有限です。直線/退化スペクトルを確認してください。")
        slope = (row[-1] - row[0]) / (wavelengths[-1] - wavelengths[0])
        intercept = row[0] - slope * wavelengths[0]
        for k, ((low, high), indices) in enumerate(zip(bands, selections)):
            wx, sy = wavelengths[indices], row[indices]
            # R evaluates baseline y at nominal band boundaries, but closes the
            # polygon at inner measured x values. It does not interpolate x.
            area_x = np.r_[wx, wx[-1], wx[0], wx[0]]
            area_y = np.r_[sy, high * slope + intercept, low * slope + intercept, sy[0]]
            out[i, k] = _polygon_area(area_x, area_y) / full_area
    return _finite_result(out, "AUC面積比"), actual


def temperature_calibration(matrix: Any, wavelengths: Any, temperatures: Any, *,
                            coordinate_system: str = "ot1.12", smooth_n: int = 17) -> dict:
    """Build JSON calibration from raw spectra, retaining only temperature means.

    SG(p2,m0,ts1) is applied to each full raw spectrum, then wavelengths within
    [1300,1600] are retained, temperature replicates averaged, and AUC ratios
    computed. SFC uses separate unsmoothed raw-temperature means and counts.
    Outlier detection/exclusion is not performed; supply curated calibration.
    """
    x = _matrix(matrix, min_rows=2, min_columns=3)
    w = _vector(wavelengths, x.shape[1], "校正波長")
    temp = _temperatures(temperatures, len(x))
    bands, names = _system(coordinate_system)
    unique = np.unique(temp)
    if len(unique) < 2:
        raise ValueError("校正には異なる温度が2点以上必要です。")
    smoothed = sgolay(x, window=smooth_n, polyorder=2, derivative=0)
    cut = np.flatnonzero((w >= 1300) & (w <= 1600))
    if len(cut) < 3:
        raise ValueError("校正に1300〜1600 nm内の波長が3列以上必要です。")
    cw = w[cut]
    masks = [temp == t for t in unique]
    counts = [int(mask.sum()) for mask in masks]
    raw_means = np.array([x[mask][:, cut].mean(axis=0) for mask in masks])
    means = np.array([smoothed[mask][:, cut].mean(axis=0) for mask in masks])
    universal, actual = _auc_table(means, cw, bands)
    data_hash = hashlib.sha256(x.astype("<f8").tobytes() + w.astype("<f8").tobytes() + temp.astype("<f8").tobytes()).hexdigest()
    return {"schemaVersion": 1, "kind": "aquap2py-temperature-calibration", "implementationVersion": VERSION,
            "referenceAquap2Version": "0.4.5", "referenceCommit": REFERENCE_COMMIT,
            "coordinateSystem": coordinate_system, "coordinateLabels": list(names),
            "coordinateRanges": [list(b) for b in bands], "actualBandRanges": actual,
            "temperatures": unique.tolist(), "wavelengths": cw.tolist(), "counts": counts,
            "rawTemperatureMeans": raw_means.tolist(), "universalAuc": universal.tolist(),
            "provenance": {"engine": "aquap2py", "rExecuted": False, "sourceMatrixSha256": data_hash,
                "sourceSamples": len(x), "sourceVariables": len(w), "sourceRange": [float(w[0]), float(w[-1])],
                "calibrationCutNm": [1300, 1600], "smoothN": int(smooth_n), "sgPolyorder": 2,
                "sgDerivative": 0, "sgTs": 1, "order": ["SG-full-spectrum", "cut-1300-1600", "mean-per-temperature", "polygon-AUC-ratio"],
                "foreignCenterData": "unsmoothed-raw-temperature-means-and-replicate-counts",
                "outlierExclusion": "not-performed-input-must-be-curated", "loessImplemented": True,
                "fullAreaNumericalFloor": "64*eps*variables*max(abs(spectrum))*wavelength-span"}}


def _read_calibration(model: Any):
    if not isinstance(model, dict) or model.get("schemaVersion") != 1 or model.get("kind") != "aquap2py-temperature-calibration":
        raise ValueError("temperature_calibrationで作成した校正modelを指定してください。")
    if model.get("referenceCommit") != REFERENCE_COMMIT or model.get("referenceAquap2Version") != "0.4.5":
        raise ValueError("校正modelの参照版が異なります。")
    bands, names = _system(model.get("coordinateSystem"))
    if model.get("coordinateRanges") != [list(b) for b in bands] or model.get("coordinateLabels") != list(names):
        raise ValueError("校正modelの座標定義が固定版と一致しません。")
    declared_temperatures = model.get("temperatures")
    if not isinstance(declared_temperatures, (list, tuple, np.ndarray)):
        raise ValueError("校正modelに温度配列がありません。")
    temp = _temperatures(declared_temperatures, len(declared_temperatures))
    if len(temp) < 2 or np.any(np.diff(temp) <= 0):
        raise ValueError("校正modelの温度は2点以上・昇順・重複なしにしてください。")
    raw = _matrix(model.get("rawTemperatureMeans"), min_rows=2, min_columns=3)
    w = _vector(model.get("wavelengths"), raw.shape[1], "校正model波長")
    auc = _matrix(model.get("universalAuc"), min_rows=2, min_columns=len(bands))
    counts = np.asarray(model.get("counts"))
    if raw.shape[0] != len(temp) or auc.shape != (len(temp), len(bands)) or counts.shape != temp.shape or counts.dtype.kind not in "iu" or np.any(counts < 1) or np.any(counts > 2000000) or counts.sum() > 2000000:
        raise ValueError("校正modelの温度・件数・行列形状が一致しません。")
    return temp, raw, w, auc, counts, bands, names


def _range(t_calib: Any, t_exp: Any, temperatures: np.ndarray):
    experiment = _finite_scalar(t_exp, "実験温度Texp")
    if t_calib is None:
        limits = [float(temperatures[0]), float(temperatures[-1])]
    elif isinstance(t_calib, str):
        match = re.fullmatch(r"symm@([+]?(?:\d+(?:\.\d*)?|\.\d+))", t_calib)
        if not match:
            raise ValueError("TCalibは2数値、None、またはsymm@正数にしてください。")
        delta = float(match[1])
        limits = [experiment - delta, experiment + delta]
    elif isinstance(t_calib, (list, tuple, np.ndarray)) and len(t_calib) == 2:
        limits = [_finite_scalar(t_calib[0], "TCalib下限"), _finite_scalar(t_calib[1], "TCalib上限")]
    else:
        raise ValueError("TCalibは2数値、None、またはsymm@正数にしてください。")
    if not np.isfinite(limits).all() or limits[0] >= limits[1]:
        raise ValueError("TCalib下限は上限より小さい有限値にしてください。")
    if limits[0] < temperatures[0] or limits[1] > temperatures[-1]:
        raise ValueError("TCalibが校正データの温度範囲外です。")
    if experiment < temperatures[0] or experiment > temperatures[-1]:
        raise ValueError("Texpが校正データの温度範囲外です。LOESS外挿は未対応です。")
    return limits, experiment


def _calibration_at(temperatures, auc, limits, experiment):
    """Match the two separate observed-value branches in aquap2 calc_aqg.r."""
    endpoint_loess = not np.isin(limits, temperatures).all()
    experiment_loess = experiment not in temperatures
    query = (list(limits) if endpoint_loess else []) + ([experiment] if experiment_loess else [])
    if query:
        predicted = np.column_stack([robust_quadratic_loess(temperatures, column, query) for column in auc.T])
    endpoints = predicted[:2] if endpoint_loess else auc[np.isin(temperatures, limits)]
    baseline = predicted[-1] if experiment_loess else auc[temperatures == experiment][0]
    return endpoints, baseline, {
        "endpointLoessUsed": endpoint_loess, "experimentLoessUsed": experiment_loess,
        "bothEndpointsPredictedWhenEitherIsUnobserved": endpoint_loess,
        "loessProfile": {"predictors": 1, "degree": 2, "span": .75, "family": "symmetric",
            "iterations": 4, "surface": "interpolate", "cell": .2,
            "minimumUniqueTemperatures": 8, "singularNeighborhoodsSupported": False,
            "extrapolationSupported": False} if query else None}


def temperature_aquagram(matrix: Any, wavelengths: Any, groups: Any, calibration: dict, *,
                         mode: str = "aucs.dce", t_calib: Any = None, t_exp: float = 28.6,
                         reference: str | None = None, smooth_n: int = 21, msc: bool = False,
                         msc_reference: Any = None, targets: Any = None,
                         nr_corr: bool = False, boot_ci: bool = False) -> dict:
    """Run 10 calibrated modes, including bounded temperature LOESS.

    reference is the exact control-group label for '-diff' modes, not the
    transport/UI prefix 'group:'. AUC coordinates are fixed bands: wavelengths
    in that output are geometric band midpoints for plotting only.
    """
    if not isinstance(mode, str) or mode not in _MODES:
        raise ValueError("温度Aquagramの対応modeを指定してください。classicは既存のclassic_aquagramを使用します。")
    if not all(isinstance(v, bool) for v in (msc, nr_corr, boot_ci)):
        raise ValueError("MSC・観測数補正・bootstrapはtrue/falseにしてください。")
    if nr_corr or boot_ci:
        raise ValueError("温度Aquagramの観測数random補正・bootstrap/CIは未実装です。")
    x = _matrix(matrix, min_rows=2, min_columns=3)
    w = _vector(wavelengths, x.shape[1], "測定波長")
    labels = _labels(groups, len(x), "群")
    names = list(dict.fromkeys(labels))
    if mode.endswith("-diff"):
        if not isinstance(reference, str) or reference not in names:
            raise ValueError("-diffには実在する対照群名をreferenceへ指定してください。")
    elif reference is not None:
        raise ValueError("非diff modeではreference=Noneにしてください。対照群差には-diff modeを選択してください。")
    temp, raw_means, cw, auc, counts, bands, coordinates = _read_calibration(calibration)
    limits, experiment = _range(t_calib, t_exp, temp)
    endpoints, experiment_auc, interpolation = _calibration_at(temp, auc, limits, experiment)
    processed = sgolay(x, window=smooth_n, polyorder=2, derivative=0)
    masks = [np.asarray(labels) == name for name in names]
    warnings = []
    provenance = {"engine": "aquap2py", "implementationVersion": VERSION, "rExecuted": False,
        "referenceAquap2Version": "0.4.5", "referenceCommit": REFERENCE_COMMIT,
        "mode": mode, "coordinateSystem": calibration["coordinateSystem"],
        "tCalibRequested": t_calib if t_calib is None or isinstance(t_calib, str) else [_finite_scalar(v, "TCalib") for v in t_calib], "tCalib": limits, "tExp": experiment,
        "observedTemperaturesOnly": not (interpolation["endpointLoessUsed"] or interpolation["experimentLoessUsed"]),
        "loessImplemented": True, **interpolation,
        "smoothN": int(smooth_n), "sgPolyorder": 2, "sgDerivative": 0, "sgTs": 1,
        "calibrationSmoothN": calibration.get("provenance", {}).get("smoothN"),
        "nrCorr": False, "bootCI": False, "completeCompatibility": False,
        "currentRunComparedWithR": False, "inputSamples": len(x), "inputVariables": len(w),
        "inputRange": [float(w[0]), float(w[-1])], "controlGroup": reference,
        "calibrationSourceSha256": calibration.get("provenance", {}).get("sourceMatrixSha256"),
        "temperatureEquivalentIsEstimatedTemperature": False}
    if mode.startswith("sfc"):
        if not np.array_equal(w, cw):
            raise ValueError("sfc初版は測定格子と校正の1300〜1600 nm内格子の完全一致が必要です。異なる格子の位置index対応は未対応です。")
        requested = np.asarray(_DEFAULT_TARGETS if targets is None else targets)
        if requested.ndim != 1 or requested.dtype.kind not in "iuf" or len(requested) < 1 or len(requested) > 10000 or not np.isfinite(requested).all() or len(set(requested)) != len(requested) or not np.isin(requested, w).all():
            raise ValueError("sfc座標は測定波長と完全一致する有限値・重複なしにしてください。")
        position = np.flatnonzero(np.isin(w, requested))
        if msc:
            processed = apply_msc(processed, msc_reference)
        elif msc_reference is not None:
            raise ValueError("msc_referenceを指定する場合はmsc=Trueにしてください。")
        # tempCalibMakeTable selects raw observations on this half-degree grid.
        grid = np.round(limits[0] + .5 * np.arange(int(np.floor((limits[1] - limits[0]) / .5)) + 1), 1)
        selected = np.isin(temp, grid)
        if not selected.any():
            raise ValueError("sfcの0.5度刻み選択範囲に校正観測がありません。")
        center = np.average(raw_means[selected], axis=0, weights=counts[selected])[position]
        centered = processed[:, position] - center
        with np.errstate(over="ignore", invalid="ignore"):
            denominator = np.sqrt(np.sum(centered ** 2, axis=0) / (len(x) - 1))
        if np.any(denominator == 0) or not np.isfinite(denominator).all():
            raise ValueError("sfcの校正中心からの測定尺度が0または非有限です。")
        values = np.array([(centered / denominator)[mask].mean(axis=0) for mask in masks])
        row_values = centered / denominator
        output_wavelengths = w[position].tolist()
        output_labels = [f"{v:g} nm" for v in output_wavelengths]
        ranges = None
        unit = "dimensionless-foreign-center-scaled"
        definition = "sfc: SG→任意MSC後の測定値から範囲内の未平滑化校正観測平均を減算し、測定値の校正中心からの二乗和/(n−1)の平方根で除して群平均。校正SDによる標準化ではありません。"
        provenance.update(order=["SG", "MSC" if msc else "no-MSC", "select-exact-wavelengths", "foreign-center", "measurement-RMS-n-minus-1", "group-mean"],
                          internalMsc=msc, calibrationSelectedTemperatures=temp[selected].tolist(),
                          calibrationSelectedSamples=int(counts[selected].sum()), foreignCenter=center.tolist(),
                          measurementScales=denominator.tolist(), foreignCenterGridStep=.5)
    else:
        if targets is not None:
            raise ValueError("AUC系は固定帯座標です。targetsを指定せずcoordinate_systemで12/15帯を選択してください。")
        if msc or msc_reference is not None:
            warnings.append("AUC系ではR本体と同じく内部MSC/referenceは使用しません。")
        ratios, actual = _auc_table(processed, w, bands)
        means = np.array([ratios[mask].mean(axis=0) for mask in masks])
        minimum, maximum = endpoints.min(axis=0), endpoints.max(axis=0)
        difference = maximum - minimum
        if np.any(difference == 0) or not np.isfinite(difference).all():
            raise ValueError("TCalib両端の校正AUC面積比が等しい帯があります。校正範囲を確認してください。")
        values = (means - minimum) * 100 / difference
        row_values = (ratios - minimum) * 100 / difference
        if not mode.endswith("-diff") and ".tn" not in mode and np.any((values < 0) | (values > 100)):
            warnings.append("校正範囲に対するAUC%が0〜100%を外れています。値はclipせず、校正範囲と測定/校正条件を確認してください。")
        baseline = (experiment_auc - minimum) * 100 / difference
        if ".tn" in mode:
            values = values - baseline
            row_values = row_values - baseline
        if ".dce" in mode:
            values = values * (limits[1] - limits[0]) / 100
            row_values = row_values * (limits[1] - limits[0]) / 100
            if ".tn" not in mode:
                values = values + limits[0]
                row_values = row_values + limits[0]
        output_wavelengths = [float((a + b) / 2) for a, b in bands]
        output_labels = list(coordinates)
        ranges = [list(b) for b in bands]
        unit = "percent" if ".tn" not in mode else "percentage-point"
        if ".dce" in mode:
            unit = "degC-equivalent-deviation" if ".tn" in mode else "degC-equivalent"
        definition = "AUC: 各測定行の固定帯多角形面積/全入力幅の多角形面積を群平均し、校正TCalib両端の比のmin/maxを0/100%として換算。"
        if ".tn" in mode:
            definition += "同じ校正のTexp%を減算。"
        if ".dce" in mode:
            definition += "校正温度幅/100で℃相当へ換算" + ("。" if ".tn" in mode else "し、TCalib下限を加算。")
        definition += "実温度の推定や統計的有意差を意味しません。"
        provenance.update(order=["SG", "row-polygon-area/full-area", "group-mean", "endpoint-minmax-percent"] + (["subtract-Texp-percent"] if ".tn" in mode else []) + (["temperature-equivalent"] if ".dce" in mode else []),
            internalMsc=False, nominalBandRanges=ranges, actualBandRanges=actual,
            bandBoundaryPolicy="inside-measured-columns-no-interpolation; baseline-y-at-nominal-boundaries",
            fullAreaPolicy="entire-provided-measurement-matrix; calibration-only-cut-1300-1600",
            wavelengthAxis="band-midpoints-for-plotting-not-single-wavelength-values",
            calibrationEndpointOnly=True, calibrationMinima=minimum.tolist(), calibrationMaxima=maximum.tolist(),
            temperatureBaselinePercent=baseline.tolist(), percentClipping=False)
    if mode.endswith("-diff"):
        row_values = row_values - values[names.index(reference)]
        values = values - values[names.index(reference)]
        provenance["order"].append("subtract-control-group")
        definition += "指定対照群の値を減算。"
        if unit == "percent":
            unit = "percentage-point"
        if unit.startswith("degC"):
            unit = "degC-equivalent-difference"
    _finite_result(values, "温度Aquagram")
    return {"wavelengths": output_wavelengths, "labels": output_labels,
        "ddof": 1 if mode.startswith("sfc") else None, "sdDdof": 1 if mode.startswith("sfc") else None,
        "coordinateRanges": ranges, "coordinateSystem": calibration["coordinateSystem"],
        "groups": [{"name": name, "n": int(mask.sum()), "values": value.tolist()} for name, mask, value in zip(names, masks, values)],
        "reference": "対照群: " + reference if reference is not None else "校正基準",
        "definition": definition, "mode": mode, "unit": unit, "provenance": provenance, "warnings": warnings,
        "rowValues": _finite_result(row_values, "温度Aquagram試料値").tolist(),
        "rowDefinition": "群平均前の各試料へ同じ平滑化・校正座標・固定校正尺度を適用。diffは同じ指定対照群の換算平均を減算。再生フレームごとの再校正・標準化は行いません。℃相当値は測定温度の推定ではありません。"}

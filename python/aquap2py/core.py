"""R-free numerical subset of aquap2 0.4.5, with explicit supported scope."""
from __future__ import annotations

import copy
from typing import Any

import numpy as np

from .preprocessing import _finite_result, _int, _matrix, preprocess_spectra, sgolay

REFERENCE_COMMIT = "d31c1231bf71f0e73f1a630a32934602782be488"
VERSION = "0.3.0"


def _vector(value: Any, size: int, label: str) -> np.ndarray:
    raw = np.asarray(value)
    if raw.dtype.kind not in "iuf" or raw.shape != (size,):
        raise ValueError(f"{label}は変数数と同じ長さの数値ベクトルにしてください。")
    x = np.array(raw, dtype=float, copy=True)
    if not np.isfinite(x).all() or np.any(x <= 0) or np.any(np.diff(x) <= 0):
        raise ValueError(f"{label}は有限の正数・昇順・重複なしにしてください。")
    return x


def _labels(value: Any, size: int, label: str, *, unique: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, np.ndarray)) or len(value) != size:
        raise ValueError(f"{label}の数を試料数に一致させてください。")
    if any(not isinstance(x, str) or not x.strip() or "\0" in x or len(x.encode("utf-8")) > 4096 for x in value):
        raise ValueError(f"{label}には空でない文字列を指定してください。")
    out = tuple(str(x) for x in value)
    if unique and len(set(out)) != size:
        raise ValueError("試料IDが重複しています。一意のIDを指定してください。")
    return out


class SpectralData:
    """Validated copies. Matrix/wavelength arrays are read-only; labels immutable."""

    def __init__(self, matrix: Any, wavelengths: Any, ids: Any = None, groups: Any = None):
        x = _matrix(matrix, min_rows=2, min_columns=3)
        w = _vector(wavelengths, x.shape[1], "波長")
        row_ids = _labels(ids if ids is not None else [f"S{i + 1:03d}" for i in range(len(x))], len(x), "試料ID", unique=True)
        row_groups = _labels(groups if groups is not None else ["全試料"] * len(x), len(x), "群")
        x.setflags(write=False)
        w.setflags(write=False)
        self.matrix, self.wavelengths, self.ids, self.groups = x, w, row_ids, row_groups


def ttap(matrix: Any, wavelengths: Any, ids: Any = None, groups: Any = None) -> SpectralData:
    """Explicit Python matrix factory; not an R S4 or arbitrary ttap argument adapter."""
    return SpectralData(matrix, wavelengths, ids, groups)


def pca(matrix: Any, components: int = 5, *, scale: bool = False) -> dict:
    """Column-mean-centered SVD; no per-variable standardization."""
    if scale is not False:
        raise ValueError("aquap2互換PCAは平均中心化のみです。scale=Trueには対応していません。")
    x = _matrix(matrix, min_rows=2)
    k = _int(components, "PCA成分数", 1, min(10, len(x) - 1, x.shape[1]))
    if not np.any(x != x[0]):
        raise ValueError("試料間変動が0のためPCAを計算できません。")
    with np.errstate(over="ignore", invalid="ignore"):
        centered = _finite_result(x - x.mean(axis=0), "PCA中心化")
    if not np.any(centered != 0):
        raise ValueError("試料間変動が0のためPCAを計算できません。")
    try:
        u, singular, vh = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError as exc:
        raise ValueError("PCAのSVDが収束しませんでした。数値範囲を確認してください。") from exc
    # Squaring normalized singular values avoids overflow of a valid large SVD.
    relative = singular / singular[0]
    explained = relative ** 2 / np.sum(relative ** 2)
    scores = _finite_result(u[:, :k] * singular[:k], "PCAスコア")
    loadings = _finite_result(vh[:k].T, "PCA負荷量")
    return {"scores": scores.tolist(), "loadings": loadings.tolist(), "explainedVariance": explained[:k].tolist()}


def classic_aquagram(matrix: Any, wavelengths: Any, groups: Any, targets: Any,
                     reference: str = "global", smooth_n: int = 3) -> dict:
    """Explicit classic/classic-diff profile, sample SD, no internal MSC.

    Targets must be exact measured columns. Their output follows measured
    wavelength order, matching R's which(wls %in% selWls). Initial default SG=3
    is the identity SG used by the installed-package bridge, not R's default
    analysis procedure (SG21, MSC enabled, default mode aucs.dce).
    """
    x = _matrix(matrix, min_rows=2, min_columns=3)
    w = _vector(wavelengths, x.shape[1], "波長")
    labels = _labels(groups, len(x), "群")
    requested = np.asarray(targets)
    if requested.dtype.kind not in "iuf" or requested.ndim != 1 or not 3 <= len(requested) <= min(24, len(w)):
        raise ValueError("Aquagramには実波長と一致する3～24座標を指定してください。")
    requested = np.array(requested, dtype=float, copy=True)
    if not np.isfinite(requested).all() or len(set(requested)) != len(requested) or not np.isin(requested, w).all():
        raise ValueError("Aquagram座標は実波長と完全一致する有限値・重複なしにしてください。")
    names = list(dict.fromkeys(labels))
    if not isinstance(reference, str):
        raise ValueError("Aquagram基準はglobalまたはgroup:群名を指定してください。")
    if reference == "global":
        control, mode, label = None, "classic", "全体平均"
    elif reference.startswith("group:") and reference[6:] in names:
        control, mode, label = reference[6:], "classic-diff", "対照群: " + reference[6:]
    else:
        raise ValueError("Aquagram基準はglobalまたは存在するgroup:群名を指定してください。基準なし・温度校正・AUCは未対応です。")
    processed = sgolay(x, window=smooth_n, polyorder=2, derivative=0)
    positions = np.flatnonzero(np.isin(w, requested))
    selected = processed[:, positions]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        std = selected.std(axis=0, ddof=1)
        if np.any(np.ptp(selected, axis=0) == 0) or np.any(std == 0) or not np.isfinite(std).all():
            raise ValueError("Aquagram座標に標本SDが0または非有限の波長があります。")
        standardized = _finite_result((selected - selected.mean(axis=0)) / std, "Aquagram標準化")
    masks = [np.asarray(labels) == group for group in names]
    values = np.array([standardized[mask].mean(axis=0) for mask in masks])
    if control is not None:
        values = values - values[names.index(control)]
    _finite_result(values, "Aquagram群平均")
    actual = w[positions].tolist()
    definition = ("aquap2 0.4.5 classicのPython移植: 各実波長で全試料を平均中心化し、標本SD(ddof=1)で標準化して群平均。"
                  if control is None else "aquap2 0.4.5 classic-diffのPython移植: classicの標準化群平均から指定対照群を減算（標本SD ddof=1）。")
    return {"wavelengths": actual, "labels": [f"{v:g} nm" for v in actual],
            "groups": [{"name": name, "values": value.tolist(), "n": int(mask.sum())}
                       for name, value, mask in zip(names, values, masks)],
            "reference": label, "definition": definition, "mode": mode, "ddof": 1}


def gdmm(dataset: SpectralData, *, steps: list[dict] | None = None, components: int = 5,
         aquagram_wavelengths: Any, reference: str = "global", aq_smooth_n: int = 3,
         temperature: dict | None = None, plsr: dict | None = None,
         **unsupported) -> dict:
    """Small Python orchestration API, not full R gdmm argument compatibility."""
    if unsupported:
        raise ValueError("未対応のgdmm引数です: " + ", ".join(sorted(unsupported)))
    if not isinstance(dataset, SpectralData):
        raise ValueError("gdmmにはttapまたはSpectralDataで作成したデータを指定してください。")
    requested_steps = copy.deepcopy(steps) if steps is not None else []
    preprocessing = preprocess_spectra(dataset.matrix, dataset.wavelengths, requested_steps)
    transformed, wavelengths = preprocessing["matrix"], preprocessing["wavelengths"]
    def json_value(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            return {k: json_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [json_value(v) for v in value]
        return value
    if temperature is not None:
        if not isinstance(temperature, dict):
            raise ValueError("温度校正Aquagramには校正モデルと明示設定を指定してください。")
        from .temperature import temperature_aquagram
        aquagram = temperature_aquagram(transformed, wavelengths, dataset.groups, **temperature)
    else:
        aquagram = classic_aquagram(transformed, wavelengths, dataset.groups,
                                   aquagram_wavelengths, reference, aq_smooth_n)
    result = {"preprocessed": transformed.tolist(), "wavelengths": wavelengths.tolist(),
            "preprocessingModels": json_value(preprocessing["models"]), "pca": pca(transformed, components),
            "aquagram": aquagram,
            "provenance": {"engine": "aquap2py", "version": VERSION, "implementation": "numpy-scipy",
                           "rExecuted": False, "rPackageApiExecuted": False,
                           "referenceAquap2Version": "0.4.5", "referenceCommit": REFERENCE_COMMIT,
                           "steps": json_value(requested_steps), "snvDdof": 1, "sgTs": 1,
                           "irregularWavelengthPolicy": "explicit-resample-only; SG uses sample index",
                           "pcaCenter": True, "pcaScale": False, "aquagramDdof": aquagram.get("ddof"),
                           "aquagramSmoothN": temperature.get("smooth_n", 21) if temperature else aq_smooth_n,
                           "aquagramInternalMsc": temperature.get("msc", False) if temperature else False,
                           "supportedModels": ["pca", aquagram.get("mode", "classic")],
                           "unsupported": ["classification", "bootstrap", "complete R API compatibility"]}}
    if plsr is not None:
        if not isinstance(plsr, dict):
            raise ValueError("PLSRには数値目的変数と明示設定を指定してください。")
        from .plsr import plsr as native_plsr
        result["plsr"] = native_plsr(transformed, **({"sample_ids":list(dataset.ids), **plsr}))
        result["provenance"]["supportedModels"].append("plsr")
    return result


def getcm(cube: dict, model: str = "pca") -> dict:
    if model not in {"pca", "aquagram", "plsr"}:
        raise ValueError("getcmはpca、aquagram、限定PLSRに対応しています。分類モデルは未対応です。")
    if not isinstance(cube, dict) or model not in cube:
        raise ValueError("gdmmで作成したcubeを指定してください。")
    return copy.deepcopy(cube[model])

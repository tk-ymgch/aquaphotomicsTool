"""Explicit, bounded translations of aquap2 0.4.5 preprocessing definitions.

SNV uses sample SD, MSC follows pls::msc, and SG follows signal::sgolayfilt
including its boundary filters and default ts=1. The explicit spectral-sequence
API also tracks wavelength changes. See NOTICE for references and attribution.
"""
from __future__ import annotations

from functools import lru_cache
import math
from typing import Any

import numpy as np

MAX_ELEMENTS = 2_000_000
MAX_VARIABLES = 10_000
MAX_SHORT_DIMENSION = 1_000


def _matrix(value: Any, *, min_rows: int = 1, min_columns: int = 1) -> np.ndarray:
    try:
        original = np.asarray(value)
        if original.dtype.kind not in "iuf":
            raise ValueError
        out = np.array(original, dtype=np.float64, copy=True)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("スペクトル行列には実数の数値を指定してください。") from exc
    if out.ndim != 2 or out.shape[0] < min_rows or out.shape[1] < min_columns:
        raise ValueError(f"スペクトルは{min_rows}試料以上・{min_columns}変数以上の二次元行列にしてください。")
    if out.size > MAX_ELEMENTS or out.shape[1] > MAX_VARIABLES or min(out.shape) > MAX_SHORT_DIMENSION:
        raise ValueError("解析行列は200万要素・1万波長以下、行列の短辺1000以下にしてください。")
    if not np.isfinite(out).all():
        raise ValueError("スペクトルに欠損値・非有限値があります。解析前に明示的に補完してください。")
    return out


def _int(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or not low <= int(value) <= high:
        raise ValueError(f"{label}は{low}～{high}の整数にしてください。")
    return int(value)


def _finite_result(x: np.ndarray, label: str) -> np.ndarray:
    if not np.isfinite(x).all():
        raise ValueError(f"{label}で非有限値が生じました。数値の大きさや退化したスペクトルを確認してください。")
    return x


def snv(matrix: Any) -> np.ndarray:
    """Autoscale each spectrum by its sample SD (number of variables minus 1)."""
    x = _matrix(matrix, min_columns=2)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        mean = x.mean(axis=1, keepdims=True)
        std = x.std(axis=1, ddof=1, keepdims=True)
        if np.any(np.ptp(x, axis=1) == 0) or np.any(std == 0) or not np.isfinite(std).all():
            raise ValueError("SNVを計算できません。一定値または数値範囲が極端なスペクトルがあります。")
        return _finite_result((x - mean) / std, "SNV")


def msc(matrix: Any, reference: Any | None = None) -> np.ndarray:
    """MSC against the column mean or one explicitly provided reference vector."""
    x = _matrix(matrix, min_columns=2)
    if reference is None:
        with np.errstate(over="ignore", invalid="ignore"):
            ref = x.mean(axis=0)
    else:
        raw = np.asarray(reference)
        if raw.dtype.kind not in "iuf" or raw.shape != (x.shape[1],):
            raise ValueError("MSC参照は波長数と同じ長さの数値ベクトルにしてください。")
        ref = np.array(raw, dtype=float, copy=True)
    if not np.isfinite(ref).all() or np.ptp(ref) == 0:
        raise ValueError("MSC参照スペクトルが一定値または非有限値です。")
    z = np.column_stack([np.ones(x.shape[1]), ref])
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        normal = z.T @ z
        if not np.isfinite(normal).all() or np.linalg.cond(normal) >= 1 / np.finfo(float).eps:
            raise ValueError("MSC参照の回帰行列が特異または不安定です。")
        try:
            coefficients = np.linalg.solve(normal, (x @ z).T).T
        except np.linalg.LinAlgError as exc:
            raise ValueError("MSC参照の回帰行列が特異です。") from exc
        slope = coefficients[:, 1]
        if np.any(np.abs(slope) <= 64 * np.finfo(float).eps) or not np.isfinite(slope).all():
            raise ValueError("MSCの回帰傾きが0に近い試料があります。")
        return _finite_result((x - coefficients[:, :1]) / slope[:, None], "MSC")


@lru_cache(maxsize=32)
def _sg_filter(window: int, polyorder: int, derivative: int) -> np.ndarray:
    """R signal's position-specific SG coefficient matrix, ts fixed at one."""
    k = window // 2
    filters = np.zeros((window, window), dtype=float)
    for position in range(k + 1):
        offsets = np.arange(window, dtype=float) - position
        design = offsets[:, None] ** np.arange(polyorder + 1)[None, :]
        u, singular, vh = np.linalg.svd(design, full_matrices=False)
        keep = singular > np.finfo(float).eps * singular[0]
        inverse = (vh.T[:, keep] / singular[keep]) @ u.T[keep]
        filters[position] = inverse[derivative]
    filters[k + 1:] = (-1) ** derivative * filters[k - 1::-1, ::-1]
    filters *= math.factorial(derivative)
    filters.setflags(write=False)
    return filters


def sgolay(matrix: Any, *, window: int = 21, polyorder: int = 2,
           derivative: int = 0, delta: float = 1.0) -> np.ndarray:
    """R-compatible SG with sample-index spacing; delta other than 1 is refused."""
    from scipy.signal import lfilter

    x = _matrix(matrix, min_columns=3)
    n = _int(window, "SGウィンドウ幅", 3, min(501, x.shape[1]))
    p = _int(polyorder, "SG多項式次数", 0, min(6, n - 1))
    m = _int(derivative, "SG微分次数", 0, min(2, p))
    if n % 2 != 1:
        raise ValueError("SGウィンドウ幅は奇数にしてください。")
    if isinstance(delta, (bool, np.bool_)) or not isinstance(delta, (int, float, np.number)) or delta != 1:
        raise ValueError("aquap2互換SGの間隔は列位置ts=1です。波長nmでのdelta指定には対応していません。")
    f = _sg_filter(n, p, m)
    k = n // 2
    with np.errstate(over="ignore", invalid="ignore"):
        left = x[:, :n] @ f[:k].T
        middle = lfilter(f[k, ::-1], [1.0], x, axis=1)[:, n - 1:]
        right = x[:, -n:] @ f[k + 1:].T
        return _finite_result(np.concatenate([left, middle, right], axis=1), "SG")


def _wavelengths(value: Any, columns: int) -> np.ndarray:
    raw = np.asarray(value)
    if raw.dtype.kind not in "iuf" or raw.ndim != 1 or len(raw) != columns:
        raise ValueError("波長は行列の列数と同じ長さの数値ベクトルにしてください。")
    out = np.array(raw, dtype=float, copy=True)
    if not np.isfinite(out).all() or np.any(out <= 0) or np.any(np.diff(out) <= 0):
        raise ValueError("波長は有限の正数で、重複のない昇順にしてください。")
    return out


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not np.isrealobj(value):
        raise ValueError(f"{label}は有限の正数にしてください。")
    result = float(value)
    if not np.isfinite(result) or result <= 0:
        raise ValueError(f"{label}は有限の正数にしてください。")
    return result


def _range_indices(value: Any, waves: np.ndarray, label: str, minimum: int) -> np.ndarray:
    raw = np.asarray(value)
    if raw.dtype.kind not in "iuf" or raw.shape != (2,):
        raise ValueError(f"{label}は下限・上限の数値2個にしてください。")
    limits = np.asarray(raw, dtype=float)
    if not np.isfinite(limits).all() or limits[0] >= limits[1] or limits[0] < waves[0] or limits[1] > waves[-1]:
        raise ValueError(f"{label}は測定波長内の昇順範囲にしてください。")
    positions = np.flatnonzero((waves >= limits[0]) & (waves <= limits[1]))
    if len(positions) < minimum:
        raise ValueError(f"{label}に測定点が{minimum}個以上必要です。")
    return positions


def detrend(matrix: Any, wavelengths: Any, *, src: Any = None, trg: Any = "src") -> dict:
    """Fit a line on src; subtract it on trg, leaving all other cells intact.

    This ports do_detrend's matrix calculation, not its S4/settings interface.
    Empty/single-point ranges are refused rather than following R's selectWls
    reverse-index or dimension-dropping edge behavior.
    """
    x = _matrix(matrix, min_columns=2)
    waves = _wavelengths(wavelengths, x.shape[1])
    source = np.arange(len(waves)) if src is None else _range_indices(src, waves, "De-trend計算元範囲", 2)
    if trg is None:
        # R's checkDeTrendSrcTrgInput treats all(NULL == "src") as true.
        target = source.copy()
    elif isinstance(trg, str):
        if trg == "src":
            target = source.copy()
        elif trg == "all":
            target = np.arange(len(waves))
        else:
            raise ValueError("De-trend適用先はsrc、all、または波長範囲にしてください。")
    else:
        target = _range_indices(trg, waves, "De-trend適用先範囲", 2)
    # Center the coordinate before regression, then express R lm's intercept.
    # This avoids the poor conditioning of an uncentered near-infrared grid.
    centered = waves[source] - waves[source].mean()
    denominator = centered @ centered
    if not np.isfinite(denominator) or denominator <= np.finfo(float).tiny:
        raise ValueError("De-trend計算元の波長範囲が退化しています。")
    with np.errstate(over="ignore", invalid="ignore"):
        source_mean = x[:, source].mean(axis=1)
        slopes = (x[:, source] - source_mean[:, None]) @ centered / denominator
        intercepts = source_mean - slopes * waves[source].mean()
        out = x.copy()
        out[:, target] = x[:, target] - intercepts[:, None] - slopes[:, None] * waves[target]
    return {"matrix": _finite_result(out, "De-trend"), "wavelengths": waves,
            "model": {"method": "detrend", "coefficientOrder": ["intercept", "slope"],
                      "coefficients": np.column_stack([intercepts, slopes]).tolist(),
                      "sourceIndices": source.tolist(), "targetIndices": target.tolist(),
                      "sourceWavelengths": waves[source].tolist(), "targetWavelengths": waves[target].tolist(),
                      "aquap2ExportModel": None, "modelScope": "Python diagnostic linear fits; aquap2 exports no extra model"}}


def emsc(matrix: Any, vec_load: Any) -> dict:
    """Remove one/two supplied effects against this matrix's mean spectrum.

    The design is intercept, column mean and the supplied vectors, matching
    aquap2::do_emsc. Rank-deficient designs and zero scale coefficients fail
    explicitly; no external reference fitting or automatic PCA is inferred.
    """
    x = _matrix(matrix, min_columns=3)
    raw = np.asarray(vec_load)
    if raw.dtype.kind not in "iuf":
        raise ValueError("EMSCには波長数に一致する1～2列の数値効果ベクトルを指定してください。")
    effects = np.array(raw, dtype=float, copy=True)
    if effects.ndim == 1:
        effects = effects[:, None]
    if effects.ndim != 2 or effects.shape[0] != x.shape[1] or effects.shape[1] not in (1, 2) or not np.isfinite(effects).all():
        raise ValueError("EMSCには波長数に一致する1～2列の有限な効果ベクトルを指定してください。")
    reference = x.mean(axis=0)
    design = np.column_stack([np.ones(x.shape[1]), reference, effects])
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        if not np.isfinite(design).all():
            raise ValueError("EMSC参照の数値範囲が極端です。")
        try:
            coefficients, _, rank, _ = np.linalg.lstsq(design, x.T, rcond=1e-12)
        except np.linalg.LinAlgError as exc:
            raise ValueError("EMSCの回帰行列を解けません。参照の数値範囲を確認してください。") from exc
        if rank != design.shape[1]:
            raise ValueError("EMSC参照・効果ベクトルの回帰行列が特異または不安定です。")
        coefficients = coefficients.T
        scales = coefficients[:, 1]
        if np.any(np.abs(scales) <= 64 * np.finfo(float).eps):
            raise ValueError("EMSCの回帰傾きが0に近い試料があります。")
        out = (x - coefficients[:, :1] - coefficients[:, 2:] @ effects.T) / scales[:, None]
    return {"matrix": _finite_result(out, "EMSC"), "wavelengths": None,
            "model": {"method": "emsc", "reference": reference.tolist(), "vecLoad": effects.tolist(),
                      "coefficients": coefficients.tolist(), "coefficientOrder": ["intercept", "referenceScale"] +
                      [f"effect{i + 1}" for i in range(effects.shape[1])], "aquap2ExportModel": None,
                      "modelScope": "Python diagnostic regression; aquap2 exports no extra model"}}


def gap_derivative(matrix: Any, wavelengths: Any, *, m: int = 1, w: int = 1,
                   s: int = 1, delta_w: float = 1.0) -> dict:
    """Prospectr-style gap-segment derivative with aquap2's shortened grid.

    In pinned aquap2 the endpoint duplication described in its help is commented
    out. The returned matrix and wavelengths therefore both lose half the valid
    filter length on either side. delta_w is explicit sampling interval, never
    guessed from the wavelength coordinates.
    """
    from scipy.signal import convolve

    x = _matrix(matrix, min_columns=3)
    waves = _wavelengths(wavelengths, x.shape[1])
    order = _int(m, "Gap微分次数", 1, 4)
    gap = _int(w, "Gap幅", 1, 501)
    segment = _int(s, "Gap segment幅", 1, 501)
    delta = _positive_number(delta_w, "Gap deltaW")
    if gap % 2 != 1 or segment % 2 != 1:
        raise ValueError("Gap幅とsegment幅は奇数にしてください。")
    length = order * gap + (order + 1) * segment
    if length > x.shape[1]:
        raise ValueError("Gapフィルター長が測定波長数を超えています。")
    blocks = []
    for k in range(order):
        blocks.extend([np.full(segment, (-1) ** (order - k) * math.comb(order, k), dtype=float), np.zeros(gap)])
    kernel = np.concatenate([*blocks, np.ones(segment)])
    half = (length - 1) // 2
    positions = np.arange(length, dtype=float) - half
    normalization = np.sum(positions ** order * kernel) / math.factorial(order)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        denominator = np.float_power(delta, order)
        if not np.isfinite(denominator) or denominator == 0:
            raise ValueError("Gap deltaWの数値範囲が極端です。")
        kernel = kernel / normalization / denominator
        out = convolve(x, kernel[None, ::-1], mode="valid", method="auto")
    return {"matrix": _finite_result(out, "Gap derivative"), "wavelengths": waves[half:len(waves) - half],
            "model": {"method": "gap_derivative", "m": order, "w": gap, "s": segment,
                      "deltaW": delta, "filter": kernel.tolist(), "removedPerSide": half,
                      "boundaryPolicy": "valid-only-no-endpoint-duplication", "aquap2ExportModel": None}}


def resample_nir(matrix: Any, wavelengths: Any, *, target_wavelengths: Any = None,
                 tby: float = 0.5, method: str = "cubic") -> dict:
    """Interpolate inside the observed range, using aquap2's default grid.

    'cubic' means shape-preserving PCHIP, 'spline' means not-a-knot cubic spline.
    These use independent SciPy interpolators rather than translated pracma
    code. Unknown methods, unsorted grids and extrapolation are refused.
    """
    from scipy.interpolate import CubicSpline, PchipInterpolator

    x = _matrix(matrix, min_columns=2)
    waves = _wavelengths(wavelengths, x.shape[1])
    if not isinstance(method, str) or method not in {"linear", "constant", "nearest", "spline", "cubic"}:
        raise ValueError("再標本化方式はlinear、constant、nearest、spline、cubicから選択してください。")
    if target_wavelengths is None:
        delta = _positive_number(tby, "再標本化間隔")
        lower, upper = math.ceil(waves[0] / 2) * 2, math.floor(waves[-1] / 2) * 2
        if upper <= lower:
            raise ValueError("再標本化の既定範囲に2点以上の出力波長が必要です。")
        intervals = (upper - lower) / delta
        if not np.isfinite(intervals) or intervals > MAX_VARIABLES:
            raise ValueError("再標本化の出力は2～1万波長・200万要素以下にしてください。")
        count = math.floor(intervals + 1e-10) + 1
        if count < 2 or count > MAX_VARIABLES or count * len(x) > MAX_ELEMENTS or min(count, len(x)) > MAX_SHORT_DIMENSION:
            raise ValueError("再標本化の出力は2～1万波長・200万要素以下にしてください。")
        targets = lower + np.arange(count) * delta
    else:
        raw = np.asarray(target_wavelengths)
        if raw.ndim != 1 or not 2 <= raw.size <= MAX_VARIABLES or raw.size * len(x) > MAX_ELEMENTS or min(raw.size, len(x)) > MAX_SHORT_DIMENSION:
            raise ValueError("再標本化の出力は2～1万波長・200万要素以下にしてください。")
        targets = _wavelengths(raw, len(raw))
    if targets[0] < waves[0] or targets[-1] > waves[-1]:
        raise ValueError("再標本化の出力波長は元の測定範囲内にしてください。外挿は行いません。")
    if method in {"spline", "cubic"} and len(waves) < 3:
        raise ValueError("cubic/spline再標本化には元の測定点が3個以上必要です。")
    if method == "spline" and len(waves) < 4:
        raise ValueError("spline再標本化は元の測定点4個以上に限定します。R参照の3点splineは非有限値を返します。")
    if method == "linear":
        out = np.array([np.interp(targets, waves, row) for row in x])
    elif method == "constant":
        out = x[:, np.searchsorted(waves, targets, side="right") - 1]
    elif method == "nearest":
        midpoints = (waves[:-1] + waves[1:]) / 2
        out = x[:, np.searchsorted(midpoints, targets, side="right")]
    elif method == "cubic":
        out = PchipInterpolator(waves, x, axis=1, extrapolate=False)(targets)
    else:
        out = CubicSpline(waves, x, axis=1, bc_type="not-a-knot", extrapolate=False)(targets)
    return {"matrix": _finite_result(np.array(out, copy=True), "再標本化"), "wavelengths": targets,
            "model": {"method": "resample", "interpolation": method,
                      "sourceWavelengths": waves.tolist(), "targetWavelengths": targets.tolist(),
                      "defaultGrid": target_wavelengths is None, "extrapolation": False}}


def preprocess_spectra(matrix: Any, wavelengths: Any, steps: list[dict]) -> dict:
    """Apply explicit steps while tracking each change to the spectral grid.

    The older preprocess() intentionally retains its ndarray-only contract and
    original three methods. This API returns per-step diagnostic models, not
    aquap2 S4 objects or interchangeable exportModel objects.
    """
    x = _matrix(matrix)
    waves = _wavelengths(wavelengths, x.shape[1])
    if not isinstance(steps, list) or len(steps) > 32:
        raise ValueError("前処理stepsは32個以下の設定辞書のリストにしてください。")
    allowed = {"detrend": {"method", "src", "trg"}, "emsc": {"method", "vec_load"},
               "gap_derivative": {"method", "m", "w", "s", "delta_w"},
               "resample": {"method", "target_wavelengths", "tby", "interpolation"}}
    models = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("method"), str):
            raise ValueError("前処理にはmethodを持つ設定辞書を指定してください。")
        method = step["method"]
        if method in {"snv", "msc", "sgolay"}:
            x = preprocess(x, [step])
            models.append({"step": index, "method": method, "scope": "existing bounded matrix preprocessing"})
            continue
        if method not in allowed or set(step) - allowed[method]:
            raise ValueError(f"未対応の前処理または引数です: {method}")
        options = {k: v for k, v in step.items() if k != "method"}
        if method == "detrend":
            result = detrend(x, waves, **options)
        elif method == "emsc":
            if "vec_load" not in options:
                raise ValueError("EMSC効果ベクトルvec_loadを指定してください。")
            result = emsc(x, **options)
        elif method == "gap_derivative":
            result = gap_derivative(x, waves, **options)
        else:
            interpolation = options.pop("interpolation", "cubic")
            result = resample_nir(x, waves, method=interpolation, **options)
        x = result["matrix"]
        if result["wavelengths"] is not None:
            waves = result["wavelengths"]
        models.append({"step": index, **result["model"]})
    return {"matrix": x, "wavelengths": waves, "models": models}


def preprocess(matrix: Any, steps: list[dict]) -> np.ndarray:
    """Apply an explicit ordered list; unknown methods/options fail closed."""
    x = _matrix(matrix)
    if not isinstance(steps, list) or len(steps) > 32:
        raise ValueError("前処理stepsは32個以下の設定辞書のリストにしてください。")
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("method"), str):
            raise ValueError("前処理にはmethodを持つ設定辞書を指定してください。")
        method = step["method"]
        allowed = {"snv": {"method"}, "msc": {"method", "reference"},
                   "sgolay": {"method", "window", "polyorder", "derivative", "delta"}}
        if method not in allowed:
            raise ValueError(f"未対応の前処理です: {method}")
        if set(step) - allowed[method]:
            raise ValueError(f"前処理{method}に未対応の引数があります。")
        if method == "snv":
            x = snv(x)
        elif method == "msc":
            x = msc(x, reference=step.get("reference"))
        else:
            x = sgolay(x, **{k: v for k, v in step.items() if k != "method"})
    return x

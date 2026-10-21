"""Explicit, bounded translations of aquap2 0.4.5 preprocessing definitions.

SNV uses sample SD, MSC follows pls::msc, and SG follows signal::sgolayfilt
including its boundary filters and default ts=1. No wavelength resampling is
performed. See the package NOTICE for upstream references and attribution.
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

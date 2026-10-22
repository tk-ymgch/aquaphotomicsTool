"""Bounded one-predictor R LOESS defaults used by aquap2 temperature AUC.

Implements quadratic local fits, span .75, symmetric family (four fits), the
default .2 cell subdivision, and cubic Hermite interpolation. This is not a
general replacement for stats::loess (no SE, multidimensional or custom args).

Algorithm references: R stats loess.R/simpleLoess and loessf.f routines ehg126,
ehg124, ehg127, ehg128, lowesw; https://svn.r-project.org/R/trunk/src/library/stats/.
Python adaptation 2026-10-22. R wrapper is GPL-2.0-or-later; see package LICENSE.

The underlying LOESS algorithm carries the following notice:
Copyright (C) 1998--2020 The R Core Team
The authors of this software are Cleveland, Grosse, and Shyu.
Copyright (c) 1989, 1992 by AT&T.
Permission to use, copy, modify, and distribute this software for any
purpose without fee is hereby granted, provided that this entire notice
is included in all copies of any software which is or includes a copy
or modification of this software and in all copies of the supporting
documentation for such software.
THIS SOFTWARE IS BEING PROVIDED "AS IS", WITHOUT ANY EXPRESS OR IMPLIED
WARRANTY. IN PARTICULAR, NEITHER THE AUTHORS NOR AT&T MAKE ANY
REPRESENTATION OR WARRANTY OF ANY KIND CONCERNING THE MERCHANTABILITY
OF THIS SOFTWARE OR ITS FITNESS FOR ANY PARTICULAR PURPOSE.
"""
from __future__ import annotations

import numpy as np


def _vertices(x: np.ndarray) -> np.ndarray:
    """One-dimensional default k-d subdivision; x is strictly increasing."""
    n = len(x)
    padding = .005 * max(x[-1] - x[0], 1e-10 * max(abs(x[0]), abs(x[-1])) + 1e-30)
    bounds = [float(x[0] - padding), float(x[-1] + padding)]
    threshold = int(np.floor(n * (.75 * .2)))
    queue = [(0, n - 1, bounds[0], bounds[1])]
    while queue:
        low, high, left, right = queue.pop(0)
        if high - low + 1 <= threshold:
            continue
        middle = (low + high) // 2
        split = float(x[middle])
        if split in (left, right):
            continue
        bounds.append(split)
        queue.extend([(low, middle, left, split), (middle + 1, high, split, right)])
    return np.sort(bounds)


def _local(x, y, weights, at):
    distance = (x - at) ** 2
    nf = min(len(x), int(np.floor(len(x) * .75 + 1e-5)))
    indices = np.argsort(distance, kind="stable")[:nf]
    radius = distance[indices[-1]]
    if radius <= 0 or not np.isfinite(radius):
        raise ValueError("LOESSの近傍温度半径が0または非有限です。")
    root_weight = np.sqrt(weights[indices] * (1 - np.sqrt(distance[indices] / radius) ** 3) ** 3)
    delta = x[indices] - at
    design = np.column_stack((np.ones(nf), delta, delta ** 2)) * root_weight[:, None]
    scales = np.sqrt(np.sum(design ** 2, axis=0))
    if np.any(scales == 0) or not np.isfinite(scales).all():
        raise ValueError("LOESSの近傍重みまたは設計行列が退化しています。")
    coefficients, _, rank, _ = np.linalg.lstsq(design / scales, root_weight * y[indices], rcond=100 * np.finfo(float).eps)
    if rank != 3:
        raise ValueError("LOESS近傍が特異です。Rの疑似逆行列・特異近傍は今回の対応範囲外です。")
    return coefficients[:2] / scales[:2]


def _interpolate(vertices, fits, queries):
    i = np.searchsorted(vertices, queries, side="left") - 1
    i = np.clip(i, 0, len(vertices) - 2)
    width = vertices[i + 1] - vertices[i]
    h = (queries - vertices[i]) / width
    return ((1 - h) ** 2 * (1 + 2 * h) * fits[i, 0] + h ** 2 * (3 - 2 * h) * fits[i + 1, 0]
            + (h * (1 - h) ** 2 * fits[i, 1] + h ** 2 * (h - 1) * fits[i + 1, 1]) * width)


def robust_quadratic_loess(x, y, queries):
    """Predict R's bounded 1D symmetric/default-interpolate LOESS profile.

    Unique sorted x and >=8 observations are required. Singular weighted fits
    and extrapolation are explicitly unsupported. The input y is one AUC band.
    """
    x, y, queries = [np.asarray(value, dtype=float) for value in (x, y, queries)]
    if x.ndim != 1 or y.shape != x.shape or queries.ndim != 1 or len(x) < 8 or len(x) > 20000:
        raise ValueError("未観測温度LOESSには8〜20000点の異なる校正温度と同形の帯別AUCが必要です。")
    if not all(np.isfinite(value).all() for value in (x, y, queries)) or np.any(np.diff(x) <= 0):
        raise ValueError("LOESS入力は有限値で、温度は昇順・重複なしにしてください。")
    if np.any((queries < x[0]) | (queries > x[-1])):
        raise ValueError("LOESSの校正温度範囲外への外挿は未対応です。")
    vertices = _vertices(x)
    weights = np.ones(len(x))
    for iteration in range(4):
        fits = np.array([_local(x, y, weights, vertex) for vertex in vertices])
        if iteration == 3:
            break
        residual = np.abs(y - _interpolate(vertices, fits, x))
        cmad = 6 * np.median(residual)
        if cmad < np.finfo(float).tiny:
            weights = np.ones(len(x))
        else:
            # lowesw clamps the inner/outer .001/.999 neighborhoods exactly.
            weights = np.where(residual > .999 * cmad, 0., np.where(residual > .001 * cmad, (1 - (residual / cmad) ** 2) ** 2, 1.))
    result = _interpolate(vertices, fits, queries)
    if not np.isfinite(result).all():
        raise ValueError("LOESS予測が非有限です。校正温度と曲線を確認してください。")
    return result

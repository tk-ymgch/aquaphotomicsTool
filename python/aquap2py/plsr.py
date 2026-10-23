"""Scoped aquap2 0.4.5 PLS1: kernel PLS, CV/adjCV and native selection.

This is not Workbench nested CV. X must already contain the complete native
DPT result: DPT is outside CV; only model centering is fitted within each fold.
Prediction likewise requires X in the same processed variable space. Numerical
equations are independently expressed with NumPy; no R process is involved.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from .preprocessing import _finite_result, _int, _matrix

REFERENCE_COMMIT = "d31c1231bf71f0e73f1a630a32934602782be488"
MAX_COMPONENTS = 30
MAX_FOLDS = 1000
MAX_FITS = 12_000
MAX_WORK = 1_000_000_000


def _y_vector(y: Any, n: int) -> np.ndarray:
    value = np.asarray(y)
    if value.dtype.kind not in "iuf" or value.shape != (n,):
        raise ValueError("PLSRの目的値は試料数と同じ長さの実数ベクトルにしてください。")
    out = np.array(value, dtype=float, copy=True)
    if not np.isfinite(out).all():
        raise ValueError("PLSRの目的値に欠損値・非有限値があります。行の除外を明示してから解析してください。")
    if np.ptp(out) == 0:
        raise ValueError("PLSRの目的値が一定値です。変動する数値目的値を指定してください。")
    return out


def _labels(value: Any, n: int, label: str) -> list[str]:
    if not isinstance(value, (list, tuple, np.ndarray)) or len(value) != n:
        raise ValueError(f"PLSRの{label}を試料数と同じ長さで指定してください。")
    out = []
    for item in value:
        if not isinstance(item, (str, int, float, np.integer, np.floating)) or isinstance(item, (bool, np.bool_)):
            raise ValueError(f"PLSRの{label}には空でない文字列または有限数を指定してください。")
        if isinstance(item, (float, np.floating)) and not np.isfinite(item):
            raise ValueError(f"PLSRの{label}に欠損値があります。")
        text = str(item)
        if not text.strip() or "\0" in text or len(text.encode("utf-8")) > 4096:
            raise ValueError(f"PLSRの{label}には空でない短い値を指定してください。")
        out.append(text)
    return out


def _checked_segments(value: Any, n: int) -> list[np.ndarray]:
    if not isinstance(value, (list, tuple)) or not 2 <= len(value) <= min(n, MAX_FOLDS):
        raise ValueError("PLSRの分割は2個以上の空でない検証行リストにしてください。")
    result, seen = [], []
    for segment in value:
        a = np.asarray(segment)
        if a.ndim != 1 or not len(a) or a.dtype.kind not in "iu" or np.any(a < 0) or np.any(a >= n):
            raise ValueError("PLSRの分割には範囲内の0始まり整数行番号を指定してください。")
        a = np.array(a, dtype=int, copy=True)
        result.append(a)
        seen.extend(a.tolist())
    if len(seen) != n or sorted(seen) != list(range(n)):
        raise ValueError("PLSRの検証分割は各行を重複・欠落なく一度ずつ含めてください。")
    if n - max(map(len, result)) < 3:
        raise ValueError("PLSRの各学習分割には3試料以上が必要です。")
    return result


def _native_segments(n: int, validation: str | int, groups: list[str] | None,
                     sample_ids: list[str] | None, rng: np.random.Generator) -> list[np.ndarray]:
    if validation == "LOO" or isinstance(validation, (int, np.integer)) and validation >= n:
        return [np.array([i]) for i in range(n)]
    if validation == "group":
        # Caller chooses the group order explicitly by first appearance; token
        # factor levels in the oracle preserve the same order.
        names = list(dict.fromkeys(groups))
        return [np.flatnonzero(np.array(groups) == name) for name in names]
    k = int(validation)
    ids = sample_ids if sample_ids is not None else [str(i) for i in range(n)]
    names = list(dict.fromkeys(ids))
    if len(names) <= 2:
        return [np.array([i]) for i in range(n)]
    blocks = [np.flatnonzero(np.array(ids) == name) for name in names]
    k = min(k, len(blocks))
    pool = list(range(len(blocks)))
    count = len(blocks) // k
    picked = []
    for _ in range(k):
        take = rng.choice(pool, size=count, replace=False).tolist()
        picked.append(take)
        pool = [v for v in pool if v not in take]
    for i, remaining in enumerate(pool):
        picked[i].append(remaining)
    return [np.concatenate([blocks[i] for i in part]) for part in picked]


def _rank(x: np.ndarray) -> int:
    centered = _finite_result(x - x.mean(0), "PLSR中心化")
    try:
        return int(np.linalg.matrix_rank(centered))
    except np.linalg.LinAlgError as exc:
        raise ValueError("PLSRのランク判定が収束しませんでした。") from exc


def _kernel(x: np.ndarray, y: np.ndarray, components: int) -> dict:
    """PLS1 covariance-deflation equations, accumulating prediction vectors."""
    n, p = x.shape
    xm, ym = x.mean(0), float(y.mean())
    xc, yc = _finite_result(x - xm, "PLSR中心化"), _finite_result(y - ym, "PLSR目的値中心化")
    if _rank(x) < components:
        raise ValueError("PLSR成分数が中心化した学習行列のランクを超えています。")
    if np.ptp(y) == 0:
        raise ValueError("PLSRの学習分割の目的値が一定値です。")
    r = np.zeros((p, components)); load = r.copy(); weights = r.copy()
    scores = np.zeros((n, components)); q = np.zeros(components)
    coefs = r.copy(); fitted = scores.copy()
    covariance = _finite_result(xc.T @ yc, "PLSR共分散")
    for a in range(components):
        norm = float(np.linalg.norm(covariance))
        if not np.isfinite(norm) or norm <= np.finfo(float).tiny ** .25:
            raise ValueError("PLSRの共分散が0または数値的に小さすぎます。成分数を減らしてください。")
        wa = covariance / norm
        ra = wa.copy()
        if a >= 5:
            ra -= r[:, :a] @ (load[:, :a].T @ wa)
        else:
            for j in range(a):
                ra -= float(load[:, j] @ wa) * r[:, j]
        ta = xc @ ra
        energy = float(ta @ ta)
        if not np.isfinite(energy) or energy <= np.finfo(float).tiny ** .25:
            raise ValueError("PLSRのスコアが退化しています。成分数または数値範囲を確認してください。")
        pa = xc.T @ ta / energy
        qa = float(covariance @ ra / energy)
        covariance = _finite_result(covariance - energy * pa * qa, "PLSR共分散更新")
        r[:, a], load[:, a], weights[:, a], scores[:, a], q[a] = ra, pa, wa, ta, qa
        coefs[:, a] = r[:, :a + 1] @ q[:a + 1]
        fitted[:, a] = scores[:, :a + 1] @ q[:a + 1] + ym
    intercepts = ym - xm @ coefs
    for value in (coefs, fitted, intercepts, scores, load, weights, r, q):
        _finite_result(value, "PLSRモデル")
    return {"ncomp": components, "xMean": xm, "yMean": ym, "coefficients": coefs,
            "intercepts": intercepts, "scores": scores, "loadings": load,
            "weights": weights, "projection": r, "yLoadings": q,
            "fitted": fitted, "residuals": y[:, None] - fitted}


def _curves(y: np.ndarray, model: dict, pred: np.ndarray, press: np.ndarray,
            press0: float, adjustment: np.ndarray) -> list[dict]:
    n = len(y)
    sst = float(np.sum((y - y.mean()) ** 2))
    train = np.sum(model["residuals"] ** 2, axis=0) / n
    cv = press / n
    adj = cv + train - adjustment
    # R sqrt of a negative adjustment is NaN. Fail explicitly, rather than
    # silently clipping it and claiming agreement.
    if not np.isfinite(sst) or sst <= 0 or not np.isfinite(adj).all() or np.any(adj < 0):
        raise ValueError("PLSRの調整済みCV誤差が非有限または負値です。退化や数値範囲を確認してください。")
    rows = [{"components": 0, "rmseCalibration": float(np.sqrt(sst / n)),
             "rmseCV": float(np.sqrt(press0 / n)), "rmseAdjCV": float(np.sqrt(press0 / n)),
             "r2Calibration": 0., "r2CV": float(1 - press0 / sst)}]
    for a in range(model["ncomp"]):
        rows.append({"components": a + 1, "rmseCalibration": float(np.sqrt(train[a])),
                     "rmseCV": float(np.sqrt(cv[a])), "rmseAdjCV": float(np.sqrt(adj[a])),
                     "r2Calibration": float(1 - train[a] * n / sst), "r2CV": float(1 - press[a] / sst)})
    return rows


def _cv_model(x: np.ndarray, y: np.ndarray, requested: int, segments: list[np.ndarray]) -> dict:
    n = len(y)
    a = min(requested, n - max(map(len, segments)) - 1)
    if a < 1:
        raise ValueError("PLSRのCV学習試料が少なすぎます。")
    if min(_rank(x), *(_rank(np.delete(x, seg, axis=0)) for seg in segments)) < a:
        raise ValueError("PLSR成分数がCV学習行列のランクを超えています。成分数を減らしてください。")
    model = _kernel(x, y, a)
    pred = np.zeros((n, a)); adjustment = np.zeros(a)
    for seg in segments:
        train = np.ones(n, dtype=bool); train[seg] = False
        fit = _kernel(x[train], y[train], a)
        all_pred = _finite_result(x @ fit["coefficients"] + fit["intercepts"], "PLSR検証予測")
        pred[seg] = all_pred[seg]
        adjustment += len(seg) * np.sum((all_pred - y[:, None]) ** 2, axis=0)
    press = _finite_result(np.sum((pred - y[:, None]) ** 2, axis=0), "PLSR PRESS")
    press0 = float(np.var(y, ddof=1) * n * n / (n - 1))
    adjustment /= n * n
    model["validation"] = {"method": "CV", "segments": [s.tolist() for s in segments],
                           "pred": pred, "PRESS": press, "PRESS0": press0,
                           "adj": adjustment, "ncomp": a}
    model["curve"] = _curves(y, model, pred, press, press0, adjustment)
    return model


def _json(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _outlier_range(value: Any) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)) or not np.isfinite(value) or value < 0:
        raise ValueError("PLSR外れ値検出rangeは0以上の有限数にしてください。")
    return float(value)


def plsr_outlier_indices(result: dict, *, detection_range: float = .5) -> dict:
    """aquap2's public pls_outlier_getIndices rule for one fitted PLS1 model.

    CV predictions are grouped by equal observed Y, not by spectral/CV group.
    R boxplot uses Tukey hinges (fivenum), not interpolated 25/75% quantiles.
    The upstream outInd is an *inlier/keep* mask despite its name. This helper
    does not refit or remove rows. Unique observed Y normally gives no outliers.
    """
    coefficient = _outlier_range(detection_range)
    if not isinstance(result, dict) or not isinstance(result.get("model"), dict):
        raise ValueError("外れ値判定にはplsrのモデル付き結果を指定してください。")
    model = result["model"]
    try:
        components = _int(model["ncomp"], "PLSRモデル成分数", 1, MAX_COMPONENTS)
        predictions = np.asarray(model["validation"]["pred"], dtype=float)
        observed = np.asarray(result["observed"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("PLSRの目的値・CV予測・成分数の記録が不正です。") from exc
    if predictions.ndim != 2 or observed.ndim != 1 or predictions.shape != (len(observed), components) or not len(observed) or not np.isfinite(predictions).all() or not np.isfinite(observed).all():
        raise ValueError("PLSRの目的値とCV予測の形状・有限値を確認してください。")
    values = predictions[:, components - 1]
    excluded = np.zeros(len(observed), dtype=bool)
    group_records = []
    for target in np.unique(observed):
        indices = np.flatnonzero(observed == target)
        ordered = np.sort(values[indices])
        n = len(ordered)
        # R stats::fivenum's 1-based order statistic locations.
        n4 = np.floor((n + 3) / 2) / 2
        def midpoint(location):
            return float((ordered[int(np.floor(location)) - 1] + ordered[int(np.ceil(location)) - 1]) / 2)
        lower, upper = midpoint(n4), midpoint(n + 1 - n4)
        spread = upper - lower
        low_fence, high_fence = lower - coefficient * spread, upper + coefficient * spread
        if not np.isfinite([low_fence, high_fence]).all():
            raise ValueError("PLSR外れ値判定のフェンスが数値範囲を超えました。")
        flags = ((values[indices] < low_fence) | (values[indices] > high_fence)) if coefficient > 0 else np.zeros(n, dtype=bool)
        excluded[indices[flags]] = True
        group_records.append({"observed": float(target), "n": n, "lowerHinge": lower, "upperHinge": upper,
            "lowerFence": float(low_fence), "upperFence": float(high_fence), "excludedIndices": indices[flags].tolist()})
    return {"schemaVersion": 1, "detectionRange": coefficient, "outInd": (~excluded).tolist(),
        "keepMask": (~excluded).tolist(), "excludedMask": excluded.tolist(),
        "retainedIndices": np.flatnonzero(~excluded).tolist(), "excludedIndices": np.flatnonzero(excluded).tolist(),
        "groupsByObservedY": group_records, "definition": "選択成分のCV予測を実測Yの同値群ごとにTukey hingesの箱ひげ判定。outInd=trueは保持行。range=0は除外なし。",
        "provenance": {"referencePackage": "aquap2", "referenceVersion": "0.4.5", "referenceCommit": REFERENCE_COMMIT,
            "publicApi": "aquap2::pls_outlier_getIndices", "rExecuted": False,
            "grouping": "equal-observed-Y-not-CV-groups", "quartiles": "R-fivenum-Tukey-hinges",
            "indexBase": 0, "completeCompatibility": False}}


def plsr(matrix: Any, y: Any, *, ncomp: int | None = None, validation: str | int = "LOO",
         cv_groups: Any = None, sample_ids: Any = None, iterations: int = 7,
         seed: int = 0, segments_schedule: Any = None, max_selection_batches: int = 100,
         exclude_outliers: bool = False, outlier_range: float = .5,
         **unsupported) -> dict:
    """Native-style PLS1; LOO/group are deterministic, random CV uses NumPy RNG.

    A replay schedule is a list of segment partitions, one per selection trial
    followed by the final model partition. Fixed ncomp consumes only one. This
    permits conditional same-fold oracle comparison without claiming R RNG parity.
    Optional PLS-specific outlier exclusion performs exactly one detection pass
    and one refit, only for deterministic LOO/group partitions. DPT is not
    repeated or refitted after filtering. Missing values and rank-excess
    components are rejected. Input is already in the processed X variable space.
    """
    if unsupported:
        raise ValueError("未対応のPLSR引数です: " + ", ".join(sorted(unsupported)))
    x = _matrix(matrix, min_rows=4)
    observed = _y_vector(y, len(x)); n, p = x.shape
    if not isinstance(exclude_outliers, (bool, np.bool_)):
        raise ValueError("PLSR外れ値除外の有効設定はtrue/falseにしてください。")
    detection_range = _outlier_range(outlier_range)
    if exclude_outliers:
        if validation not in ("LOO", "group") or segments_schedule is not None:
            raise ValueError("PLSR外れ値除外はLOO・群CVのみ対応し、乱数CV・分割scheduleとの併用は未対応です。")
        options = dict(ncomp=ncomp, validation=validation, cv_groups=cv_groups, sample_ids=sample_ids,
            iterations=iterations, seed=seed, max_selection_batches=max_selection_batches)
        initial = plsr(x, observed, **options)
        diagnostic = plsr_outlier_indices(initial, detection_range=detection_range)
        retained = diagnostic["retainedIndices"]
        if len(retained) < 4:
            raise ValueError("PLSR外れ値除外後に4試料以上が必要です。")
        options["cv_groups"] = [cv_groups[i] for i in retained] if cv_groups is not None else None
        options["sample_ids"] = [sample_ids[i] for i in retained] if sample_ids is not None else None
        if validation == "group":
            # Subsetting an R factor retains its original level order even if
            # the first observed row of a level was removed. Preserve that
            # order instead of rediscovering levels from the remaining rows.
            levels = list(dict.fromkeys(_labels(cv_groups, n, "CV群")))
            kept_groups = _labels(options["cv_groups"], len(retained), "CV群")
            partition = [np.flatnonzero(np.array(kept_groups) == level).tolist() for level in levels]
            if any(not segment for segment in partition):
                raise ValueError("PLSR外れ値除外でCV群全体がなくなりました。この因子水準の保持条件は未対応です。")
            repeats = max(2, iterations) + 1 if ncomp is None else 1
            options["segments_schedule"] = [partition for _ in range(repeats)]
        filtered = plsr(x[retained], observed[retained], **options)
        filtered["outlierFiltering"] = {**diagnostic, "enabled": True, "inputRows": n, "retainedRows": len(retained),
            "initialSelectedComponents": initial["selectedComponents"], "initialObserved": observed.tolist(),
            "initialPredictedCV": initial["predictedCV"], "passes": 1, "refitted": True,
            "preprocessingRefitted": False, "scope": "LOO/group-only; one native pass; full-X-DPT-before-exclusion"}
        filtered["retainedIndices"] = retained
        filtered["excludedIndices"] = diagnostic["excludedIndices"]
        filtered["settings"].update(excludeOutliers=True, outlierRange=detection_range)
        filtered["provenance"].update(outlierRemoval=True, originalInputRows=n, retainedRows=len(retained),
            rowMapping="outlierFiltering.retainedIndices-original-zero-based", outlierDetection="CV-prediction-by-observed-Y-Tukey-hinges-one-pass",
            rng="deterministic", cvGroupOrder="original-factor-level-order" if validation == "group" else "original-row-order")
        filtered["warnings"].append("PLSR固有外れ値除外を1回行って再校正しました。出力の試料順はretainedIndicesで元の行へ対応します。前処理は除外後に再fitしていません。")
        return filtered
    if n > MAX_FOLDS:
        raise ValueError("native PLSRの試料数は1000以下にしてください。")
    iterations = _int(iterations, "PLSR選択反復数", 1, 21)
    batches_limit = _int(max_selection_batches, "PLSR選択再試行上限", 1, 100)
    seed = _int(seed, "PLSR seed", 0, 2_147_483_647)
    if isinstance(validation, (int, np.integer)) and not isinstance(validation, (bool, np.bool_)):
        validation = _int(validation, "PLSR CV分割数", 2, MAX_FOLDS)
    elif not isinstance(validation, str) or validation not in {"LOO", "group"}:
        raise ValueError("PLSR検証法はLOO、group、または2以上の整数にしてください。")
    groups = _labels(cv_groups, n, "CV群") if cv_groups is not None else None
    if validation == "group" and (groups is None or len(set(groups)) < 2):
        raise ValueError("PLSRのgroup CVには2群以上のCV群を指定してください。")
    samples = _labels(sample_ids, n, "連続測定の試料番号") if sample_ids is not None else None
    if samples is not None:
        for name in set(samples):
            ix = np.flatnonzero(np.array(samples) == name)
            if np.any(np.diff(ix) != 1):
                raise ValueError("PLSRの同一試料番号は連続した行に並べてください。")
    requested = None if ncomp is None else _int(ncomp, "PLSR成分数", 1, min(MAX_COMPONENTS, n - 1, p))
    schedule = None
    if segments_schedule is not None:
        if not isinstance(segments_schedule, (list, tuple)) or not len(segments_schedule):
            raise ValueError("PLSR分割scheduleは空でない分割リストにしてください。")
        if len(segments_schedule) * n > 200_000:
            raise ValueError("PLSRの分割scheduleは検証行番号の合計20万以下にしてください。")
        schedule = [_checked_segments(s, n) for s in segments_schedule]
        if validation == "group":
            for partition in schedule:
                if len(partition) != len(set(groups)) or any(len(set(np.array(groups)[s])) != 1 for s in partition):
                    raise ValueError("PLSRのgroup再生分割は各群を単独の検証分割にしてください。")
                for group in set(groups):
                    count = sum(bool(np.any(np.array(groups)[s] == group)) for s in partition)
                    if count != 1:
                        raise ValueError("PLSRの再生分割で同じCV群が分離されています。")
    rng = np.random.default_rng(seed)
    schedule_pos = 0; fits = 0; work = 0

    def partition():
        nonlocal schedule_pos
        if schedule is None:
            result = _checked_segments(_native_segments(n, validation, groups, samples, rng), n)
        else:
            if schedule_pos >= len(schedule):
                raise ValueError("PLSRの分割scheduleが不足しています。選択全試行と最終分割が必要です。")
            result = schedule[schedule_pos]
        schedule_pos += 1
        return result

    def evaluate(a, segs):
        nonlocal fits, work
        fits += len(segs) + 1
        work += (len(segs) + 1) * n * p * a
        if fits > MAX_FITS or work > MAX_WORK:
            raise ValueError("PLSRの計算量上限を超えます。試料数・波長数・反復数を減らしてください。")
        return _cv_model(x, observed, a, segs)

    warnings, trials, counts = [], [], []
    effective_iterations = max(2, iterations)
    candidate = requested
    batches = 0
    # R's small-data branch intentionally omits ncomp and uses mvr's default.
    if requested is None:
        candidate = min(int(np.rint(n * .25)), MAX_COMPONENTS, p)
        if candidate == n:
            candidate = n - 1
        switch = 12
        levels = len(np.unique(observed))
        if candidate > levels:
            candidate, switch = levels, levels - 1
        if candidate <= switch:
            candidate = min(n - 1, p)
        cached_key, cached_fit = None, None
        while True:
            batches += 1
            choices = []
            for iteration in range(effective_iterations):
                segs = partition()
                rank_limit = min(_rank(x), *(_rank(np.delete(x, s, axis=0)) for s in segs))
                allowed = min(candidate, n - max(map(len, segs)) - 1, rank_limit)
                if allowed < 1:
                    raise ValueError("PLSRの学習行列に利用できる成分がありません。")
                if allowed < min(candidate, n - max(map(len, segs)) - 1):
                    if "自動成分候補をCV学習行列のランクに制限しました。" not in warnings:
                        warnings.append("自動成分候補をCV学習行列のランクに制限しました。")
                key = (allowed, tuple(tuple(s) for s in segs))
                # Keep only one fitted trial. Random schedules must not retain
                # hundreds of full coefficient/prediction arrays in memory.
                if key != cached_key:
                    cached_key, cached_fit = key, evaluate(allowed, segs)
                fit = cached_fit
                errors = [v["rmseAdjCV"] for v in fit["curve"][1:]]
                chosen = int(np.argmin(errors)) + 1
                choices.append(chosen)
                trials.append({"batch": batches, "iteration": iteration + 1, "components": chosen,
                               "candidateComponents": fit["ncomp"], "rmseAdjCV": errors,
                               "segments": [s.tolist() for s in segs]})
            table = Counter(choices)
            selected = min(table, key=lambda c: (-table[c], c))
            counts = [{"components": c, "count": table[c]} for c in sorted(table)]
            if max(table.values()) > 1:
                break
            if batches >= batches_limit:
                raise ValueError("PLSR成分選択が再試行上限に達しました。成分数を明示してください。")
    else:
        selected = requested
    final_segments = partition()
    model = evaluate(selected, final_segments)
    add = 3 if selected <= 7 else 5 if selected <= 20 else 8
    plus_requested = selected + add
    # mvr validates the requested ncomp before applying the CV cap.
    if plus_requested > min(n - 1, p):
        raise ValueError("PLSRの追加成分モデルが試料数・波長数の上限を超えます。成分数を減らしてください。")
    model_plus = evaluate(plus_requested, final_segments)
    if schedule is not None and schedule_pos != len(schedule):
        raise ValueError("PLSRの分割scheduleに未使用の分割があります。")
    actual = model["ncomp"]
    if actual < selected:
        warnings.append("指定成分数をCV学習試料数に従って減らしました。")
    for fit in (model, model_plus):
        row = fit["curve"][-1]
        residual = observed - fit["validation"]["pred"][:, -1]
        fit["metrics"] = {k: row[k] for k in ("rmseCV", "rmseAdjCV", "rmseCalibration", "r2CV", "r2Calibration")}
        fit["metrics"].update({"biasCV": float(np.mean(residual)), "maeCV": float(np.mean(np.abs(residual))),
                               "baselineRmseCV": fit["curve"][0]["rmseCV"]})
    folds = np.zeros(n, dtype=int)
    for i, seg in enumerate(final_segments, 1):
        folds[seg] = i
    random = isinstance(validation, int) and validation < n
    provenance = {"referencePackage": "aquap2", "referenceVersion": "0.4.5", "referenceCommit": REFERENCE_COMMIT,
                  "algorithm": "kernelpls", "center": True, "scale": False, "rExecuted": False,
                  "preprocessingScope": "all-X-before-CV; input-already-processed",
                  "predictionInput": "same-preprocessed-X-variable-space",
                  "validationScope": "native-CV-not-nested-CV", "segmentsIndexBase": 0,
                  "rng": "explicit-segments-replay" if schedule is not None else "numpy-PCG64" if random else "deterministic",
                  "rSeedParity": False, "missingY": "reject-explicitly", "outlierRemoval": False,
                  "completeCompatibility": False,
                  "guardDifferencesFromR": {"automaticCandidateRankLimit": True, "fixedRankExcess": "reject",
                    "singularOrNonfinite": "reject", "selectionBatchesBounded": batches_limit,
                    "plusRequestedBeyondGlobalNOrP": "reject-like-mvr-before-CV-cap",
                    "plusRankExcess": "reject", "missingY": "reject-instead-of-implicit-row-omission",
                    "noncontiguousSampleIds": "reject-instead-of-assuming-block-order"},
                  "scope": "partial-PLS1-kernelpls-centered-unscaled; LOO/group exact-profile; random-CV no R RNG parity"}
    if random and schedule is None:
        warnings.append("乱数CVはNumPy PCG64を使用します。同じseedのR分割との一致は保証しません。")
    return _json({"schemaVersion": 1, "algorithm": "kernelpls", "selectedComponents": actual,
                  "retainedIndices": list(range(n)), "excludedIndices": [],
                  "observed": observed, "predictedCV": model["validation"]["pred"][:, -1],
                  "predictedCalibration": model["fitted"][:, -1],
                  "residuals": observed - model["validation"]["pred"][:, -1], "fold": folds,
                  "metrics": model["metrics"], "curve": model_plus["curve"],
                  "coefficients": {"values": model["coefficients"][:, -1], "intercept": model["intercepts"][-1]},
                  "model": model, "modelPlus": model_plus,
                  "selection": {"mode": "fixed" if requested is not None else "repeated-adjCV-mode",
                                "iterations": 0 if requested is not None else effective_iterations,
                                "batches": batches, "trials": trials, "counts": counts,
                                "candidateLimitBeforeCV": candidate, "selectedRequested": selected,
                                "plusRequested": plus_requested},
                  "settings": {"ncomp": requested, "validation": validation, "cvGroups": groups,
                               "sampleIds": samples, "iterations": iterations, "seed": seed,
                               "maxSelectionBatches": batches_limit, "center": True, "scale": False},
                  "provenance": provenance, "warnings": warnings,
                  "definition": "aquap2 0.4.5 PLS1互換: kernelpls、中心化・非スケーリング、全X前処理後のCV。自動成分は反復adjCV最小の最頻値。nested CVではありません。"})


def predict_plsr(model: dict, matrix: Any, *, ncomp: int | None = None) -> list[float]:
    """Predict already-processed X; no implicit DPT, refit or interpolation."""
    if not isinstance(model, dict):
        raise ValueError("保存したPLSRモデル辞書を指定してください。")
    fit = model.get("model", model)
    if not isinstance(fit, dict) or not {"ncomp", "coefficients", "intercepts", "xMean", "yMean"} <= fit.keys():
        raise ValueError("PLSRモデルの係数・中心化情報が不足しています。")
    available = _int(fit["ncomp"], "保存PLSRモデルの成分数", 1, 1000)
    k = _int(available if ncomp is None else ncomp, "PLSR予測成分数", 1, available)
    x = _matrix(matrix)
    try:
        coefficients = np.asarray(fit["coefficients"], dtype=float)
        intercepts = np.asarray(fit["intercepts"], dtype=float)
        if coefficients.shape != (x.shape[1], fit["ncomp"]) or intercepts.shape != (fit["ncomp"],):
            raise ValueError
        if not np.isfinite(coefficients).all() or not np.isfinite(intercepts).all():
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError("PLSRモデルの変数数または係数が不正です。学習時と同じ前処理・列順を指定してください。") from exc
    return _finite_result(x @ coefficients[:, k - 1] + intercepts[k - 1], "PLSR未知予測").tolist()

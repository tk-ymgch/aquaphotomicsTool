"""Browser-local experimental phase import and explicit Unity clock alignment.

This module never infers a session anchor from row counts or stretches time.
Openness events are candidates, because Unity exports may lack tracking flags.
"""
from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
import pandas as pd

from workbench import MAX_MATRIX_ELEMENTS, _filename, _labels, _summary, inspect_bytes

PHASES = ("Baseline", "Task", "Recovery")
PREFIX = "experiment_"
METRICS = [
    {"key": "pupil_mean", "label": "平均瞳孔径（両眼）", "unit": "入力値の単位"},
    {"key": "pupil_left_mean", "label": "左瞳孔径", "unit": "入力値の単位"},
    {"key": "pupil_right_mean", "label": "右瞳孔径", "unit": "入力値の単位"},
    {"key": "eye_openness_mean", "label": "平均開閉度", "unit": "0–1"},
    {"key": "gaze_dispersion_deg", "label": "視線方向のばらつき（両眼）", "unit": "deg RMS"},
    {"key": "gaze_left_dispersion_deg", "label": "左視線方向のばらつき", "unit": "deg RMS"},
    {"key": "gaze_right_dispersion_deg", "label": "右視線方向のばらつき", "unit": "deg RMS"},
    {"key": "blink_count", "label": "開閉度による瞬き候補数", "unit": "回"},
    {"key": "blink_rate_per_min", "label": "開閉度による瞬き候補頻度", "unit": "回/観測分"},
    {"key": "pupil_valid_fraction", "label": "瞳孔径の有効割合", "unit": "0–1"},
    {"key": "gaze_valid_fraction", "label": "視線方向の有効割合", "unit": "0–1"},
    {"key": "openness_valid_fraction", "label": "開閉度の有効割合", "unit": "0–1"},
    {"key": "openness_observed_seconds", "label": "開閉度の有効観測時間", "unit": "s"},
]
DEFAULT_CONFIG = {
    "spectraTimeMode": "column", "spectraTimeColumn": None,
    "spectraTimeUnit": "datetime", "unityTimeColumn": "Time", "unityTimeUnit": "seconds",
    "unityStartTime": None, "timeOffsetSeconds": 0.0, "manualPhases": {},
    "windowSeconds": 5.0, "maxGapSeconds": 0.25, "minCoverage": 0.5, "minSamples": 3,
    "blinkThreshold": 0.2, "blinkMinSeconds": 0.05, "blinkMaxSeconds": 0.8,
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _number(config: dict, key: str, minimum: float, *, strict=False, maximum=None) -> float:
    value = config.get(key)
    number = None if isinstance(value, bool) else _finite(value)
    if number is None or number < minimum or (strict and number == minimum) or (maximum is not None and number > maximum):
        raise ValueError(f"時刻同期の設定「{key}」を有効な範囲の数値にしてください。")
    return number


def _datetime_seconds(values: pd.Series, label: str) -> np.ndarray:
    # Explicit format='mixed' accepts slash-separated seconds/minutes without
    # letting the first row's precision determine all other rows' parsing.
    try:
        parsed = pd.to_datetime(values.astype(str), format="mixed", errors="coerce", utc=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label}の日時を読み取れません。") from exc
    if parsed.isna().any():
        raise ValueError(f"{label}に読み取れない日時があります。時刻列と日時形式を確認してください。")
    # pandas 3 (including Pyodide) may infer microsecond resolution, while
    # pandas 2 commonly returns nanoseconds. Normalize before integer conversion.
    return parsed.dt.as_unit("ns").astype("int64").to_numpy(dtype=float) / 1e9


def _time_candidates(frame: pd.DataFrame, exclude: set[str] | None = None) -> list[dict]:
    result = []
    for column in frame.columns:
        if column in (exclude or set()) or str(column).startswith(PREFIX):
            continue
        values = frame[column]
        strings = values.dropna().astype(str).str.strip()
        if not len(strings):
            continue
        numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        time_name = bool(re.search(r"time|timestamp|時刻|日時|タイム|elapsed", str(column), re.I))
        # Never interpret arbitrary identifiers or temperatures as time.
        if time_name and np.isfinite(numeric).all():
            result.append({"column": column, "kind": "seconds", "uniqueValues": int(values.nunique()), "rows": len(values)})
        elif strings.str.contains(r"\d{4}[/\-]\d{1,2}[/\-]\d{1,2}.*\d{1,2}:\d{2}", regex=True).all():
            try:
                _datetime_seconds(values, str(column))
            except ValueError:
                continue
            coarse = int(strings.str.contains(r"(?:^|[T\s])\d{1,2}:\d{2}\s*$", regex=True).sum())
            result.append({"column": column, "kind": "datetime", "uniqueValues": int(values.nunique()),
                           "rows": len(values), "minutePrecisionRows": coarse})
    return result


def merge_phase_files(files: list[dict]) -> tuple[pd.DataFrame, dict]:
    """Read all files before returning: a failure cannot partially replace state."""
    if not isinstance(files, list) or not files or len(files) > 30:
        raise ValueError("測定CSVを1〜30ファイル選択し、各ファイルのフェーズを指定してください。")
    frames, records, seen_wavelengths = [], [], None
    warnings = []
    for file_index, item in enumerate(files):
        if not isinstance(item, dict) or item.get("phase") not in PHASES:
            raise ValueError("各測定ファイルのフェーズにBaseline・Task・Recoveryのいずれかを指定してください。")
        frame, summary = inspect_bytes(item["data"], item["name"], item.get("sheet"))
        wave_map = {entry["wavelength"]: entry["column"] for entry in summary["wavelengthColumns"]}
        if len(wave_map) < 3 or len(wave_map) != len(summary["wavelengthColumns"]):
            raise ValueError("各測定ファイルに重複のない3列以上の波長が必要です。Unityログは別に読み込んでください。")
        if any(str(column).startswith(PREFIX) for column in frame.columns):
            raise ValueError("入力列名のexperiment_接頭辞は実験結合用に予約されています。列名を変更してください。")
        if seen_wavelengths is None:
            seen_wavelengths = wave_map
        elif set(wave_map) != set(seen_wavelengths):
            raise ValueError("測定ファイル間で波長が一致しません。暗黙の補間や列削除は行いません。")
        frame = frame.rename(columns={column: seen_wavelengths[wave] for wave, column in wave_map.items()}).copy()
        phase, name = item["phase"], _filename(item["name"])
        original_id = frame[summary["suggestedId"]].astype(str) if summary["suggestedId"] else pd.Series([str(i + 1) for i in range(len(frame))])
        frame[PREFIX + "sample_id"] = [f"{phase}:{file_index + 1}:{i + 1}" for i in range(len(frame))]
        frame[PREFIX + "original_id"] = original_id.to_numpy()
        frame[PREFIX + "phase"] = phase
        frame[PREFIX + "source_file"] = name
        frame[PREFIX + "source_row"] = np.arange(2, len(frame) + 2)
        frames.append(frame)
        records.append({"name": name, "phase": phase, "rows": len(frame)})
        warnings.extend(summary.get("importNotes", []))
    if sum(len(f) for f in frames) * len(seen_wavelengths) > MAX_MATRIX_ELEMENTS:
        raise ValueError("結合後の解析行列は200万要素（試料数×波長数）までです。")
    # Preserve selection order, as manual timing is defined by row order within
    # each phase. Missing metadata may coexist; missing spectra may not be hidden.
    merged = pd.concat(frames, ignore_index=True, sort=False)
    merged.attrs.update(source_name="実験フェーズ結合.csv", source_sheet=None,
                        artificial=all(bool(f.attrs.get("artificial")) for f in frames))
    summary = _summary(merged, "実験フェーズ結合.csv", [], None)
    candidates = _time_candidates(merged, set(seen_wavelengths.values()))
    for candidate in candidates:
        if candidate.get("minutePrecisionRows", 0):
            warnings.append(f"「{candidate['column']}」に分単位の日時が含まれます。秒単位の測定時刻は復元できません。必要ならフェーズ開始時刻と測定間隔を明示してください。")
    anchors = [{"phase": phase, "column": candidate["column"], "kind": candidate["kind"],
                "value": str(merged.loc[merged[PREFIX + "phase"].eq(phase), candidate["column"]].iloc[0])}
               for phase in PHASES if phase in set(merged[PREFIX + "phase"]) for candidate in candidates]
    experiment = {"files": records, "phases": [p for p in PHASES if p in set(merged[PREFIX + "phase"])],
                  "timeColumns": candidates, "phaseTimeAnchors": anchors, "warnings": list(dict.fromkeys(warnings))}
    merged.attrs["experiment"] = experiment
    summary.update(suggestedId=PREFIX + "sample_id", suggestedGroup=PREFIX + "phase", experiment=experiment)
    return merged, summary


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float).copy()


def _unity_signals(frame: pd.DataFrame) -> dict:
    pupils, openness, directions = [], [], []
    mapping = {}
    for eye in ("Left", "Right"):
        p_name, o_name = f"{eye}_Pupil_Diameter", f"{eye}_Openness"
        pupil, opened = _column(frame, p_name), _column(frame, o_name)
        pupil[~np.isfinite(pupil) | (pupil <= 0)] = np.nan
        opened[~np.isfinite(opened) | (opened < 0) | (opened > 1)] = np.nan
        names = [f"{eye}_Gaze_Direction_{axis}" for axis in "xyz"]
        vectors = np.column_stack([_column(frame, name) for name in names])
        lengths = np.linalg.norm(vectors, axis=1)
        valid = np.isfinite(vectors).all(axis=1) & (lengths > 1e-12)
        vectors[valid] /= lengths[valid, None]
        vectors[~valid] = np.nan
        pupils.append(pupil); openness.append(opened); directions.append(vectors)
        mapping[eye.lower()] = {"pupil": p_name if p_name in frame else None,
                                "openness": o_name if o_name in frame else None,
                                "gazeDirection": names if all(n in frame for n in names) else []}
    def mean_rows(values):
        values = np.column_stack(values)
        count = np.isfinite(values).sum(axis=1)
        return np.divide(np.nansum(values, axis=1), count, out=np.full(len(values), np.nan), where=count > 0)
    # A bilateral openness candidate requires both exported eyes, except when
    # the entire export contains only one eye's openness channel.
    available = [i for i, eye in enumerate(("left", "right")) if mapping[eye]["openness"]]
    event_openness = np.min(np.column_stack([openness[i] for i in available]), axis=1) if len(available) == 1 else np.max(np.column_stack(openness), axis=1)
    return {"pupils": pupils, "openness": openness, "directions": directions,
            "pupilMean": mean_rows(pupils), "opennessMean": mean_rows(openness),
            "eventOpenness": event_openness, "mapping": mapping}


def inspect_unity_bytes(data: bytes, filename: str) -> tuple[pd.DataFrame, dict]:
    frame, _ = inspect_bytes(data, filename)
    candidates = _time_candidates(frame)
    signals = _unity_signals(frame)
    mapping = signals["mapping"]
    if not candidates:
        raise ValueError("Unityログの時刻列を認識できません。Timeなどの名前を持つ数値列、または日時列が必要です。")
    if not any(eye["pupil"] or eye["openness"] or eye["gazeDirection"] for eye in mapping.values()):
        raise ValueError("Unityログに対応する瞳孔径・開閉度・視線方向列がありません。列名を確認してください。")
    if len(frame) > 1_000_000:
        raise ValueError("Unityログは100万行までです。解析区間を分割してください。")
    candidate = next((c for c in candidates if c["column"] == "Time"), candidates[0])
    summary = {"name": _filename(filename), "rowCount": len(frame), "columns": list(frame.columns),
               "timeColumns": candidates, "suggestedTimeColumn": candidate["column"],
               "suggestedTimeUnit": candidate["kind"], "metricColumns": mapping,
               "warnings": ["Unityの相対時刻だけでは測定CSVの日時と同期できません。セッション開始日時または手動のフェーズ時刻を明示してください。",
                            "開閉度による瞬き候補は、トラッキング欠落と区別できない場合があります。視線・瞳孔の欠損率も確認してください。"]}
    frame.attrs["unity_summary"] = summary
    return frame, summary


def _time_values(frame: pd.DataFrame, column: str, unit: str, label: str) -> np.ndarray:
    if column not in frame:
        raise ValueError(f"{label}の時刻列を選択してください。")
    if unit == "datetime":
        return _datetime_seconds(frame[column], label)
    if unit not in {"seconds", "milliseconds"}:
        raise ValueError("時刻の単位は秒・ミリ秒・日時から選択してください。")
    values = _column(frame, column)
    if not np.isfinite(values).all():
        raise ValueError(f"{label}の時刻列に欠損・非数値・無限大があります。")
    return values / (1000.0 if unit == "milliseconds" else 1.0)


def _clocks(spectra: pd.DataFrame, unity: pd.DataFrame, config: dict):
    unity_times = _time_values(unity, config["unityTimeColumn"], config["unityTimeUnit"], "Unity")
    if len(unity_times) < 2 or np.any(np.diff(unity_times) <= 0):
        raise ValueError("Unity時刻は重複のない昇順の2行以上が必要です。並び・単位・時計のリセットを確認してください。")
    mode = config["spectraTimeMode"]
    if mode == "manual":
        times = np.empty(len(spectra), dtype=float)
        manual = config.get("manualPhases")
        if not isinstance(manual, dict):
            raise ValueError("各フェーズの開始秒と測定間隔を入力してください。")
        for phase in dict.fromkeys(spectra[PREFIX + "phase"]):
            values = manual.get(phase)
            if not isinstance(values, dict):
                raise ValueError(f"{phase}の開始秒と測定間隔を入力してください。")
            start = _number(values, "startSeconds", -1e15)
            interval = _number(values, "intervalSeconds", 0, strict=True)
            indices = np.flatnonzero(spectra[PREFIX + "phase"].to_numpy() == phase)
            times[indices] = start + np.arange(len(indices)) * interval
        origin = unity_times[0] if config["unityTimeUnit"] == "datetime" else 0.0
        unity_times = unity_times - origin
        anchor = "manual-phase-start-and-interval"
    elif mode == "column":
        times = _time_values(spectra, config["spectraTimeColumn"], config["spectraTimeUnit"], "測定CSV")
        unity_date, spectra_date = config["unityTimeUnit"] == "datetime", config["spectraTimeUnit"] == "datetime"
        if spectra_date != unity_date:
            if not spectra_date:
                raise ValueError("Unityが日時の場合、測定CSVも日時列にするか手動フェーズ時刻を指定してください。")
            value = config.get("unityStartTime")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Unityの0秒に対応するセッション開始日時を入力してください。自動の時刻対応付けは行いません。")
            origin = float(_datetime_seconds(pd.Series([value]), "Unity開始日時")[0])
            times = times - origin
            anchor = "user-specified-unity-zero-datetime"
        elif unity_date:
            origin = float(unity_times[0])
            unity_times = unity_times - origin; times = times - origin
            anchor = "shared-datetime-clock"
        else:
            anchor = "shared-numeric-clock"
    else:
        raise ValueError("測定時刻は日時列または手動のフェーズ開始時刻から指定してください。")
    offset = _number(config, "timeOffsetSeconds", -1e15)
    return times + offset, unity_times, anchor


def _blink_events(times, openness, config):
    threshold, min_duration, max_duration, gap = (config[k] for k in ("blinkThreshold", "blinkMinSeconds", "blinkMaxSeconds", "maxGapSeconds"))
    closed = np.isfinite(openness) & (openness < threshold)
    events = []
    i = 0
    while i < len(times):
        if not closed[i]:
            i += 1; continue
        first = i
        while i + 1 < len(times) and closed[i + 1] and times[i + 1] - times[i] <= gap + 1e-9:
            i += 1
        last = i
        # Complete candidates need observed open eyes on both boundaries.
        if first > 0 and last + 1 < len(times) and np.isfinite(openness[first - 1]) and np.isfinite(openness[last + 1]):
            if not closed[first - 1] and not closed[last + 1] and times[first] - times[first - 1] <= gap + 1e-9 and times[last + 1] - times[last] <= gap + 1e-9:
                start = float((times[first - 1] + times[first]) / 2)
                end = float((times[last] + times[last + 1]) / 2)
                duration = end - start
                if min_duration - 1e-12 <= duration <= max_duration + 1e-12:
                    events.append({"startSeconds": start, "endSeconds": end, "midpointSeconds": (start + end) / 2, "durationSeconds": duration})
        i += 1
    return events


def _coverage(times, start, end, max_gap, valid=None):
    left, right = max(0, int(np.searchsorted(times, start)) - 1), min(len(times) - 1, int(np.searchsorted(times, end)))
    a, b = times[left:right], times[left + 1:right + 1]
    if not len(a):
        return 0.0
    lengths = np.maximum(0.0, np.minimum(b, end) - np.maximum(a, start))
    supported = (b - a) <= max_gap + 1e-9
    if valid is not None:
        supported &= valid[left:right] & valid[left + 1:right + 1]
    return float(np.sum(lengths[supported]) / (end - start))


def _mean(values):
    values = np.asarray(values, dtype=float)
    valid = values[np.isfinite(values)]
    return float(np.mean(valid)) if len(valid) else None


def _dispersion(vectors):
    vectors = vectors[np.isfinite(vectors).all(axis=1)]
    if len(vectors) < 2:
        return None
    direction = vectors.mean(axis=0)
    length = np.linalg.norm(direction)
    if length < 1e-12:
        return None
    angles = np.degrees(np.arccos(np.clip(vectors @ (direction / length), -1, 1)))
    return float(np.sqrt(np.mean(angles ** 2)))


def _pearson(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    if n < 3 or np.ptp(x[mask]) <= 1e-12 or np.ptp(y[mask]) <= 1e-12:
        return n, None
    return n, float(np.clip(np.corrcoef(x[mask], y[mask])[0, 1], -1, 1))


def synchronize_experiment(spectra: pd.DataFrame, unity: pd.DataFrame, config: dict, analysis: dict | None = None) -> dict:
    """Aggregate observed half-open windows; no interpolation or clock inference."""
    if not isinstance(config, dict):
        raise ValueError("時刻同期の設定を確認してください。")
    config = {**DEFAULT_CONFIG, **config}
    for key, minimum, strict, maximum in [("windowSeconds", 0, True, 3600), ("maxGapSeconds", 0, True, 60),
                                          ("minCoverage", 0, False, 1), ("blinkThreshold", 0, False, 1),
                                          ("blinkMinSeconds", 0, True, 10), ("blinkMaxSeconds", 0, True, 10)]:
        config[key] = _number(config, key, minimum, strict=strict, maximum=maximum)
    if config["blinkMinSeconds"] > config["blinkMaxSeconds"]:
        raise ValueError("瞬き候補の最小時間は最大時間以下にしてください。")
    min_samples = _number(config, "minSamples", 2)
    if min_samples != int(min_samples):
        raise ValueError("最低Unity行数は2以上の整数にしてください。")
    config["minSamples"] = int(min_samples)
    if not {PREFIX + "sample_id", PREFIX + "phase", PREFIX + "source_file", PREFIX + "source_row"}.issubset(spectra.columns):
        raise ValueError("最初に測定CSVをフェーズ指定して一括読込してください。")
    times, unity_times, anchor = _clocks(spectra, unity, config)
    signals = _unity_signals(unity)
    events = _blink_events(unity_times, signals["eventOpenness"], config)
    midpoints = np.array([e["midpointSeconds"] for e in events])
    scores = processed = wavelengths = None
    analysis_ids = spectra[PREFIX + "sample_id"].astype(str).tolist()
    if analysis is not None:
        if not isinstance(analysis, dict) or not isinstance(analysis.get("pca"), dict) or not isinstance(analysis.get("spectra"), dict):
            raise ValueError("スペクトル解析結果の形式を確認し、現在のデータで解析し直してください。")
        settings = analysis.get("metadata", {}).get("settings", {})
        if "idColumn" in settings:
            analysis_ids = _labels(spectra, settings["idColumn"], "試料ID")
        if analysis.get("pca", {}).get("ids") != analysis_ids or analysis.get("spectra", {}).get("ids") != analysis_ids:
            raise ValueError("解析結果の試料と現在の結合データが一致しません。現在のデータで解析し直してください。")
        try:
            scores = np.asarray(analysis["pca"]["scores"], dtype=float)
            processed = np.asarray(analysis["spectra"]["processed"], dtype=float)
            wavelengths = np.asarray(analysis["spectra"]["wavelengths"], dtype=float)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("解析結果の行列と波長の形式を確認してください。") from exc
        if scores.ndim != 2 or wavelengths.ndim != 1 or processed.shape != (len(spectra), len(wavelengths)) or len(scores) != len(spectra):
            raise ValueError("解析結果の行数・波長数が一致しません。")
        if not np.isfinite(scores).all() or not np.isfinite(processed).all() or not np.isfinite(wavelengths).all():
            raise ValueError("解析結果に非数値・無限大・欠損があります。現在のデータで解析し直してください。")
    warnings = list(spectra.attrs.get("experiment", {}).get("warnings", []))
    warnings.extend(["同期は指定された時計・開始時刻に基づきます。装置間の時計ずれや実際のイベント対応を自動検証するものではありません。",
                     "瞬き候補は開閉度が閾値未満の連続区間です。真の瞬きとトラッキング欠落の区別は保証しません。",
                     "相関は探索的なPearson相関です。重複する時間窓・同一参加者の反復測定は独立ではなく、因果関係や統計的有意差を示しません。"])
    if len(np.unique(times)) < len(times):
        warnings.append("測定時刻が重複しています。分単位の時刻・重複窓に由来する指標の重複に注意してください。")
    rows = []
    half = config["windowSeconds"] / 2
    for i, (time, (_, source)) in enumerate(zip(times, spectra.iterrows())):
        start, end = float(time - half), float(time + half)
        a, b = np.searchsorted(unity_times, [start, end], side="left")
        count = int(b - a)
        coverage = _coverage(unity_times, start, end, config["maxGapSeconds"])
        valid = count >= min_samples and coverage + 1e-12 >= config["minCoverage"]
        reason = None if valid else "時間範囲の重なりがありません" if count == 0 else "Unity行数または時間被覆率が不足しています"
        metrics = {m["key"]: None for m in METRICS}
        if valid:
            pupils = [v[a:b] for v in signals["pupils"]]
            dirs = [v[a:b] for v in signals["directions"]]
            candidate_count = int(np.sum((midpoints >= start) & (midpoints < end)))
            openness_valid = np.isfinite(signals["eventOpenness"][a:b])
            openness_coverage = _coverage(unity_times, start, end, config["maxGapSeconds"], np.isfinite(signals["eventOpenness"]))
            openness_seconds = openness_coverage * config["windowSeconds"]
            blink_valid = openness_valid.sum() >= min_samples and openness_coverage + 1e-12 >= config["minCoverage"] and openness_seconds > 0
            metrics.update(pupil_mean=_mean(signals["pupilMean"][a:b]), pupil_left_mean=_mean(pupils[0]), pupil_right_mean=_mean(pupils[1]),
                           eye_openness_mean=_mean(signals["opennessMean"][a:b]), gaze_dispersion_deg=_dispersion(np.concatenate(dirs)),
                           gaze_left_dispersion_deg=_dispersion(dirs[0]), gaze_right_dispersion_deg=_dispersion(dirs[1]),
                           blink_count=candidate_count if blink_valid else None,
                           blink_rate_per_min=float(candidate_count * 60 / openness_seconds) if blink_valid else None,
                           pupil_valid_fraction=float(np.isfinite(np.concatenate(pupils)).mean()),
                           gaze_valid_fraction=float(np.isfinite(np.concatenate(dirs)).all(axis=1).mean()),
                           openness_valid_fraction=float(openness_valid.mean()), openness_observed_seconds=float(openness_seconds))
        rows.append({"id": analysis_ids[i], "phase": str(source[PREFIX + "phase"]),
                     "sourceFile": str(source[PREFIX + "source_file"]), "sourceRow": int(source[PREFIX + "source_row"]),
                     "timeSeconds": float(time), "windowStart": start, "windowEnd": end,
                     "unitySamples": count, "coverage": min(1.0, max(0.0, coverage)), "valid": bool(valid), "reason": reason,
                     "metrics": metrics, "pcaScores": scores[i].tolist() if scores is not None else None})
    phase_summaries = []
    for phase in PHASES:
        subset = [r for r in rows if r["phase"] == phase]
        if not subset:
            continue
        stats = {}
        for metric in METRICS:
            values = [r["metrics"][metric["key"]] for r in subset if r["valid"] and r["metrics"][metric["key"]] is not None]
            stats[metric["key"]] = {"n": len(values), "mean": _mean(values), "sd": float(np.std(values, ddof=1)) if len(values) > 1 else None}
        phase_summaries.append({"phase": phase, "totalSpectra": len(subset), "matchedSpectra": sum(r["valid"] for r in subset), "metrics": stats})
    unmatched = sum(not r["valid"] for r in rows)
    if unmatched:
        warnings.append(f"{unmatched}/{len(rows)}試料は時間窓がUnityログと十分に重ならず、指標と相関から除外しました。")
    correlations = []
    if processed is not None:
        for metric in METRICS[:9]:
            x = np.array([r["metrics"][metric["key"]] if r["valid"] and r["metrics"][metric["key"]] is not None else np.nan for r in rows])
            pc = []
            for j in range(scores.shape[1]):
                n, r = _pearson(x, scores[:, j]); pc.append({"component": j + 1, "n": n, "r": r})
            spectrum = []
            for j, wave in enumerate(wavelengths):
                n, r = _pearson(x, processed[:, j]); spectrum.append({"wavelength": wave, "n": n, "r": r})
            correlations.append({"metric": metric["key"], "pca": pc, "spectra": spectrum})
    # Deterministic decimation is solely for display; aggregates use every row.
    stride = max(1, int(np.ceil(len(unity) / 1500)))
    timeline = []
    directions = signals["directions"]
    for i in range(0, len(unity), stride):
        gaze = directions[0][i]
        angle = float(np.degrees(np.arctan2(gaze[0], gaze[2]))) if np.isfinite(gaze).all() else None
        timeline.append({"timeSeconds": float(unity_times[i]), "pupilMean": _finite(signals["pupilMean"][i]),
                         "opennessMean": _finite(signals["opennessMean"][i]), "gazeAngleDeg": angle})
    provenance = {"version": "1.0.0", "config": config, "anchor": anchor, "anchorConfirmation": config.get("anchorConfirmation", "user-entered-settings"), "alignmentAutomaticallyVerified": False,
                  "unitySource": unity.attrs.get("source_name", "Unity.csv"), "unityRows": len(unity),
                  "unityTimeRange": [float(unity_times[0]), float(unity_times[-1])], "metricColumns": signals["mapping"],
                  "windowRule": "[spectral time − window/2, spectral time + window/2)",
                  "coverageDefinition": "Overlap of adjacent Unity timestamps separated by no more than maxGapSeconds, divided by full requested window duration; no extrapolation.",
                  "blinkDefinition": "Both available eyes below openness threshold; complete open-closed-open interval, midpoint boundaries, configured duration; candidates may include tracking loss.",
                  "blinkRateDefinition": "Candidate count divided by minutes of adjacent original Unity intervals with finite event openness at both ends and gap <= maxGapSeconds; insufficient valid openness exposure returns null.",
                  "pupilDefinition": "Finite positive pupil values only; row-wise mean of available eyes, then equal frame-weight mean.",
                  "gazeDefinition": "Finite nonzero direction vectors normalized to unit length; RMS angular deviation from normalized mean direction; binocular concatenation.",
                  "phaseSummaryDefinition": "Unweighted mean and sample SD across valid spectral windows, not continuous phase exposure or paired statistical testing.",
                  "timezonePolicy": "Offset-aware timestamps converted to UTC. Naive timestamps share the explicitly entered wall clock; no timezone is inferred.",
                  "correlationDefinition": "Exploratory Pearson r over matched finite windows, minimum three pairs; constant vectors return null; no p values."}
    flat = [{**{k: v for k, v in r.items() if k not in {"metrics", "pcaScores"}}, **r["metrics"],
             **({f"PC{i + 1}": value for i, value in enumerate(r["pcaScores"])} if r["pcaScores"] else {})} for r in rows]
    phase_flat = [{"phase": s["phase"], "total_spectra": s["totalSpectra"], "matched_spectra": s["matchedSpectra"],
                   "metric": k, **v} for s in phase_summaries for k, v in s["metrics"].items()]
    correlation_flat = [{"metric": c["metric"], "kind": kind, **item} for c in correlations for kind in ("pca", "spectra") for item in c[kind]]
    exports = {"experiment/synchronized.csv": pd.DataFrame(flat).to_csv(index=False, lineterminator="\n"),
               "experiment/phase_summary.csv": pd.DataFrame(phase_flat).to_csv(index=False, lineterminator="\n"),
               "experiment/blink_candidates.csv": pd.DataFrame(events, columns=["startSeconds", "endSeconds", "midpointSeconds", "durationSeconds"]).to_csv(index=False, lineterminator="\n"),
               "experiment/correlations.csv": pd.DataFrame(correlation_flat).to_csv(index=False, lineterminator="\n"),
               "experiment/synchronization.json": json.dumps({"provenance": provenance, "warnings": warnings}, ensure_ascii=False, indent=2, allow_nan=False)}
    return {"rows": rows, "phaseSummaries": phase_summaries, "correlations": correlations, "metrics": METRICS,
            "timeline": timeline, "blinkEvents": events, "warnings": list(dict.fromkeys(warnings)), "provenance": provenance, "exports": exports}

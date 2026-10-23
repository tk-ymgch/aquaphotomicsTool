"""Explicit paper-condition calculation, separate from aquap2 package APIs.

No participant values, published loading vector, or fitted coefficients are
embedded. Every normalization population and clock comes from the loaded input.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from typing import Any

import numpy as np
import pandas as pd

TARGETS = np.array([1342, 1364, 1374, 1384, 1412, 1426, 1440, 1452, 1462, 1476, 1488, 1512], dtype=float)
LABELS = [f"C{i}" for i in range(1, 13)]
VERSION = "paper-v1.0"
DEFINITION = (
    "1300–1600 nmの読込済み実測波長で行SNV（標本SD、ddof=1）→最近傍12座標→"
    "参加者ごとの全読込行を母集団とした座標z値（標本SD、ddof=1）→最後のBaseline5行の平均差ΔC。"
    "SG・波長補間は行いません。基準と尺度は表示の選択に応じて再計算しません。"
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _finite_number(value, label):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label}は有限の数値が必要です。")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label}は有限の数値が必要です。") from exc
    if not np.isfinite(result):
        raise ValueError(f"{label}は有限の数値が必要です。")
    return result


def _column_labels(df, column, label):
    if not isinstance(column, str) or column not in df:
        raise ValueError(f"論文条件の{label}列を指定してください。")
    if df[column].isna().any():
        raise ValueError(f"{label}列に欠損があります。")
    labels = df[column].astype(str).str.strip().tolist()
    if any(not value for value in labels):
        raise ValueError(f"{label}列に空欄があります。")
    return labels


def _paper_config(df, config):
    value = config.get("paper")
    if not isinstance(value, dict):
        raise ValueError("論文条件の参加者・フェーズ・時計・入力値の種類を設定してください。")
    baseline, task = value.get("baselineLabel"), value.get("taskLabel")
    if not isinstance(baseline, str) or not baseline.strip() or not isinstance(task, str) or not task.strip() or baseline.strip() == task.strip():
        raise ValueError("BaselineとTaskの異なるフェーズ名を指定してください。")
    phases = _column_labels(df, value.get("phaseColumn"), "フェーズ")
    subject = value.get("subjectColumn")
    subjects = _column_labels(df, subject, "参加者") if subject is not None else ["single"] * len(df)
    time = value.get("timeColumn")
    if not isinstance(time, str) or time not in df:
        raise ValueError("論文の時間解析にはTaskの測定時刻列を明示指定してください。試料順を秒へ置き換えません。")
    unit = value.get("timeUnit")
    if unit not in {"seconds", "milliseconds", "datetime"}:
        raise ValueError("論文条件の時刻単位は秒・ミリ秒・日時を選択してください。")
    kind = value.get("inputKind")
    if kind not in {"as-recorded", "reflectance"}:
        raise ValueError("入力値はCSV記録値をそのまま使用するか、反射率としてlog変換するか明示してください。")
    paper = {"phaseColumn": value["phaseColumn"], "baselineLabel": baseline.strip(), "taskLabel": task.strip(),
             "subjectColumn": subject, "timeColumn": time, "timeUnit": unit, "inputKind": kind}
    if value.get("loading") is not None:
        paper["loading"] = _validate_loading(value["loading"], require_participants=True)
    return paper, np.array(phases), np.array(subjects)


def _validate_loading(value, *, require_participants):
    if not isinstance(value, dict) or not isinstance(value.get("values"), list) or len(value["values"]) != 12:
        raise ValueError("共通モードの外部loadingはC1〜C12の12値が必要です。")
    vector = np.array([_finite_number(v, "loading") for v in value["values"]])
    norm = float(np.linalg.norm(vector))
    if abs(norm - 1) > 1e-6:
        raise ValueError("外部loadingはノルム1の12次元ベクトルが必要です。暗黙の再標準化は行いません。")
    source = value.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("name"), str) or not source["name"].strip() or re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))) is None:
        raise ValueError("外部loadingの元ファイル名とSHA-256来歴が必要です。")
    count = _finite_number(value.get("participantCount"), "loading参照参加者数")
    if count != int(count) or count < (1 if require_participants else 0):
        raise ValueError("外部loadingの参照参加者数を確認し、1以上の整数で入力してください。CSVだけでは不明な場合は推定しません。")
    output = {"values": vector.tolist(), "source": {"name": re.split(r"[/\\]", source["name"])[-1], "sha256": source["sha256"]}, "participantCount": int(count)}
    if "energy" in value:
        energy = _finite_number(value["energy"], "loading寄与割合")
        if not 0 <= energy <= 1:
            raise ValueError("loading寄与割合は0〜1が必要です。")
        output["energy"] = energy
    return output


def _pooled_loading(coordinates, subjects, phases, baseline_label, task_label):
    pieces = []
    for subject in dict.fromkeys(subjects):
        base = np.flatnonzero((subjects == subject) & (phases == baseline_label))
        task = np.flatnonzero((subjects == subject) & (phases == task_label))
        if len(base) < 5 or len(task) < 6:
            raise ValueError("共通モード参照には各参加者のBaseline5行以上とTask6行以上が必要です。")
        delta = coordinates[task] - coordinates[base[-5:]].mean(axis=0)
        pieces.append(delta / np.sqrt(len(task)))
    pooled = np.vstack(pieces)
    _, singular, vh = np.linalg.svd(pooled, full_matrices=False)
    if not len(singular) or not np.isfinite(singular).all() or singular[0] <= 0:
        raise ValueError("Taskの共通変動が0のため共通モードを計算できません。")
    if len(singular) > 1 and abs(singular[0] - singular[1]) <= singular[0] * 1e-10:
        raise ValueError("第1・第2特異値が重なり共通loadingが一意に定まりません。")
    loading = vh[0]
    if np.median(pooled @ loading) < 0:
        loading = -loading
    return loading, float(singular[0] ** 2 / np.sum(singular ** 2))


def inspect_paper_reference_bytes(data: bytes, name: str) -> dict:
    """Read a twelve-row loading CSV or derive loading from uploaded C rows.

    A standalone loading CSV with no ParticipantCount returns zero (unknown).
    The UI must ask for a positive declared count before analysis can use it.
    """
    from workbench import inspect_bytes
    frame, _ = inspect_bytes(data, name)
    source = {"name": re.split(r"[/\\]", str(name))[-1], "sha256": hashlib.sha256(bytes(data)).hexdigest()}
    if {"Subject", "Phase", *LABELS}.issubset(frame.columns):
        subjects = np.array(_column_labels(frame, "Subject", "参照参加者"))
        phases = np.array(_column_labels(frame, "Phase", "参照フェーズ"))
        coordinates = frame[LABELS].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(coordinates).all() or len(frame) > 100_000:
            raise ValueError("参照C座標に欠損・非数値・無限大があるか、行数が10万を超えています。")
        if len(set(subjects)) < 2:
            raise ValueError("共通モード参照軌跡には2参加者以上が必要です。")
        loading, energy = _pooled_loading(coordinates, subjects, phases, "Baseline", "Task")
        return {"values": loading.tolist(), "source": source, "participantCount": len(set(subjects)), "energy": energy}
    if not {"CoordinateIndex", "Coordinate", "CommonLoading"}.issubset(frame.columns) or len(frame) != 12:
        raise ValueError("参照CSVはCoordinateIndex・Coordinate・CommonLoadingの12行、またはSubject・Phase・C1〜C12の座標軌跡が必要です。")
    indices = pd.to_numeric(frame["CoordinateIndex"], errors="coerce").to_numpy(dtype=float)
    if set(indices) != set(range(1, 13)):
        raise ValueError("参照loadingのCoordinateIndexは重複のない1〜12が必要です。")
    frame = frame.iloc[np.argsort(indices)]
    if frame["Coordinate"].astype(str).str.strip().tolist() != LABELS:
        raise ValueError("参照loadingのCoordinateはC1〜C12が必要です。")
    if "UsedForLoading" in frame and not frame["UsedForLoading"].astype(str).str.strip().str.lower().isin(["1", "1.0", "true"]).all():
        raise ValueError("この論文条件は12座標すべてを使う参照loadingに対応します。")
    count = 0
    if "ParticipantCount" in frame:
        counts = pd.to_numeric(frame["ParticipantCount"], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(counts).all() or len(set(counts)) != 1:
            raise ValueError("ParticipantCountは全12行で同じ整数が必要です。")
        count = float(counts[0])
    result = {"values": pd.to_numeric(frame["CommonLoading"], errors="coerce").tolist(), "source": source, "participantCount": count}
    if "PooledModeEnergy" in frame:
        energy = pd.to_numeric(frame["PooledModeEnergy"], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(energy).all() or np.ptp(energy) > 1e-10:
            raise ValueError("PooledModeEnergyは全行で同じ有限値が必要です。")
        result["energy"] = float(energy[0])
    return _validate_loading(result, require_participants=False)


def _task_clock(df, paper, subjects, phases):
    values = df[paper["timeColumn"]]
    epoch = valid_dates = None
    if paper["timeUnit"] == "datetime":
        parsed = pd.to_datetime(values.astype(str), format="mixed", errors="coerce", utc=True)
        # Force one declared unit before reading integer epoch storage; pandas
        # releases can preserve microsecond/millisecond datetime resolutions.
        epoch = parsed.dt.as_unit("ns").astype("int64").to_numpy()
        valid_dates = ~parsed.isna().to_numpy()
    else:
        numbers = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    relative = np.full(len(df), np.nan)
    for subject in dict.fromkeys(subjects):
        selected = subjects == subject
        task = np.flatnonzero(selected & (phases == paper["taskLabel"]))
        if len(task) < 6:
            raise ValueError(f"参加者「{subject}」のTaskは6行以上必要です。")
        if epoch is not None:
            if not valid_dates[task].all():
                raise ValueError(f"参加者「{subject}」のTask時刻に読み取れない日時があります。")
            origin = int(epoch[task[0]])
            # Subtract integer epochs before conversion to seconds, so a
            # modern timestamp's large absolute value cannot erase small gaps.
            relative[selected] = [(int(epoch[i]) - origin) / 1e9 if valid_dates[i] else np.nan for i in np.flatnonzero(selected)]
        else:
            relative[selected] = (numbers[selected] - numbers[task[0]]) / (1000 if paper["timeUnit"] == "milliseconds" else 1)
        times = relative[task]
        if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
            raise ValueError(f"参加者「{subject}」のTask時刻は有限値・重複なし・入力順で厳密な昇順が必要です。時刻を推定・並べ替えません。")
    return relative


def fit_paper_task(times, observed, baseline_observed, subject="single") -> dict:
    """MATLAB objective/bounds/transforms/three starts with SciPy Nelder-Mead."""
    from scipy.optimize import minimize
    times, y = np.asarray(times, dtype=float), np.asarray(observed, dtype=float)
    if times.ndim != 1 or y.shape != times.shape or len(y) < 6 or not np.isfinite(times).all() or not np.isfinite(y).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Taskモデルには6点以上の有限値と厳密な昇順時刻が必要です。")
    times = times - times[0]
    empty = {"subject": subject, "status": "unavailable", "reason": "Taskスコアの変動が0でパラメータを同定できません。", "delay": None, "amplitude": None, "tau": None, "noise": None, "rmse": None, "r2": None, "cost": None, "success": False, "points": []}
    if np.ptp(y) <= np.finfo(float).eps * max(1.0, float(np.max(np.abs(y)))):
        return empty
    noise = float(np.std(baseline_observed, ddof=1))
    if not np.isfinite(noise) or noise <= np.finfo(float).eps:
        noise = 1.0
    duration, dt = float(times[-1]), float(np.median(np.diff(times)))
    amp0 = float(np.median(y[-int(np.ceil(len(y) * .2)):]))
    if not np.isfinite(amp0) or abs(amp0) <= np.finfo(float).eps:
        amp0 = float(np.median(y))
    direction = float(np.sign(amp0)) or 1.0
    onset = np.flatnonzero(direction * y >= .1 * abs(amp0))
    delay0 = float(times[onset[0]]) if len(onset) else 0.0
    upper_delay = .8 * duration
    lower_tau = max(dt / 10, 1e-3)
    upper_tau = max(lower_tau * 10, 20 * duration)
    amplitude_bound = max(float(np.max(np.abs(y))), abs(amp0), 1.0) * 8
    def inverse(value):
        value = np.clip(value, 1e-8, 1 - 1e-8)
        return np.log(value / (1 - value))
    def encode(parameters):
        return np.array([inverse(parameters[0] / upper_delay), np.arctanh(np.clip(parameters[1] / amplitude_bound, -.999999, .999999)), inverse((np.log(parameters[2]) - np.log(lower_tau)) / (np.log(upper_tau) - np.log(lower_tau)))])
    def decode(parameters):
        logistic = lambda value: 1 / (1 + np.exp(-np.clip(value, -700, 700)))
        return np.array([upper_delay * logistic(parameters[0]), amplitude_bound * np.tanh(parameters[1]), np.exp(np.log(lower_tau) + (np.log(upper_tau) - np.log(lower_tau)) * logistic(parameters[2]))])
    def curve(parameters):
        return parameters[1] * -np.expm1(-np.maximum(times - parameters[0], 0) / parameters[2])
    def objective(parameters):
        residual = (curve(decode(parameters)) - y) / noise
        return float(np.sum(2 * (np.sqrt(1 + residual ** 2) - 1)))
    starts = [[delay0, amp0, max(dt, duration / 4)], [0, amp0, max(dt, duration / 10)], [min(.1 * duration, upper_delay), amp0, min(duration, upper_tau)]]
    fits = [minimize(objective, encode(start), method="Nelder-Mead", options={"maxiter": 12000, "maxfev": 25000, "xatol": 1e-9, "fatol": 1e-9}) for start in starts]
    candidates = [fit for fit in fits if np.isfinite(fit.fun) and np.isfinite(fit.x).all()]
    if not candidates:
        return {**empty, "reason": "有限なTaskモデル最適化結果が得られませんでした。"}
    best = min(candidates, key=lambda fit: fit.fun)
    delay, amplitude, tau = decode(best.x)
    predicted = curve((delay, amplitude, tau))
    residual = y - predicted
    total = float(np.sum((y - np.mean(y)) ** 2))
    rate = np.where(times < delay, 0.0, amplitude / tau * np.exp(-np.maximum(times - delay, 0) / tau))
    return {"subject": subject, "status": "fitted", "reason": None if best.success else "最適化の収束条件に達していません。", "delay": float(delay), "amplitude": float(amplitude), "tau": float(tau), "noise": noise, "rmse": float(np.sqrt(np.mean(residual ** 2))), "r2": float(1 - np.sum(residual ** 2) / total) if total > 0 else None, "cost": float(best.fun), "success": bool(best.success),
            "points": [{"time": float(t), "observed": float(y0), "predicted": float(y1), "rate": float(v)} for t, y0, y1, v in zip(times, y, predicted, rate)],
            "bounds": {"delay": [0, upper_delay], "amplitude": [-amplitude_bound, amplitude_bound], "tau": [lower_tau, upper_tau]},
            "optimizer": {"method": "SciPy Nelder-Mead", "starts": 3, "iterations": int(best.nit), "evaluations": int(best.nfev), "objective": "sum(2*(sqrt(1+(residual/baseline_sample_SD)^2)-1))", "baselineIntercept": 0}}


def analyze_paper(df: pd.DataFrame, config: dict) -> dict:
    import workbench as wb
    if not isinstance(df, pd.DataFrame) or len(df) < 2 or not df.columns.is_unique:
        raise ValueError("論文条件には重複列のない2行以上の入力表が必要です。")
    if {"paper_subject", "paper_phase", "paper_time_seconds", "paper_series"} & set(df.columns):
        raise ValueError("paper_subject・paper_phase・paper_time_seconds・paper_seriesは論文条件の出力用に予約されています。入力列名を変更してください。")
    paper, phases, subjects = _paper_config(df, config)
    entries = [(wb.parse_wavelength(str(column)), column) for column in df.columns]
    entries = sorted(((wave, column) for wave, column in entries if wave is not None and 1300 <= wave <= 1600), key=lambda item: item[0])
    if len(entries) < 48 or len(set(wave for wave, _ in entries)) != len(entries):
        raise ValueError("論文条件には1300–1600 nm内の重複しない実測波長が48列以上必要です。補間で列数を増やしません。")
    if len(entries) * len(df) > wb.MAX_MATRIX_ELEMENTS:
        raise ValueError("論文条件の解析行列は200万要素までです。")
    waves = np.array([wave for wave, _ in entries])
    columns = [column for _, column in entries]
    raw = df[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(raw).all():
        raise ValueError("論文条件の波長列に欠損・非数値・無限大があります。欠損補完は行いません。")
    transformed = raw.copy()
    if paper["inputKind"] == "reflectance":
        if np.any(transformed <= 0):
            raise ValueError("反射率のlog10(1/R)変換には正の有限値だけが必要です。")
        transformed = -np.log10(transformed)
    row_sd = transformed.std(axis=1, ddof=1)
    if not np.isfinite(row_sd).all() or np.any(row_sd <= np.finfo(float).eps * np.max(np.abs(transformed), axis=1)):
        raise ValueError("スペクトルが一定値または数値精度内で一定の行があり、行SNVを計算できません。")
    processed = (transformed - transformed.mean(axis=1, keepdims=True)) / row_sd[:, None]
    positions = np.array([int(np.argmin(abs(waves - target))) for target in TARGETS])
    if waves[0] > TARGETS[0] or waves[-1] < TARGETS[-1] or len(set(positions)) != 12:
        raise ValueError("12座標の指定波長に対応する異なる最近傍実測波長がありません。")
    selected = processed[:, positions]
    coordinates, delta = np.empty_like(selected), np.empty_like(selected)
    subject_records = []
    limitations = ["CSVの物理量・装置側の既適用変換は自動確認していません。as-recordedは追加log無し、reflectanceを明示した場合だけlog10(1/R)を適用します。",
                   "正規化母集団は各参加者の現在の全読込行です。論文の対象行・参加者・測定blockと同一かは自動確認しません。",
                   "本実装は独立Pythonによる論文条件プロファイルです。aquap2本体APIや元v53.2プログラムを実行した結果ではありません。",
                   "共通スコア・Taskモデルは探索的な記述です。分子種・反応速度・因果関係の測定や、参加者間のLME統計を実装するものではありません。"]
    for subject in dict.fromkeys(subjects):
        indices = np.flatnonzero(subjects == subject)
        baseline = np.flatnonzero((subjects == subject) & (phases == paper["baselineLabel"]))
        task = np.flatnonzero((subjects == subject) & (phases == paper["taskLabel"]))
        if len(baseline) < 5:
            raise ValueError(f"参加者「{subject}」のBaselineは5行以上必要です。")
        if len(task) < 6:
            raise ValueError(f"参加者「{subject}」のTaskは6行以上必要です。")
        mean = selected[indices].mean(axis=0)
        sd = selected[indices].std(axis=0, ddof=1)
        if not np.isfinite(sd).all() or np.any(sd <= np.finfo(float).eps * np.max(abs(selected[indices]), axis=0)):
            raise ValueError(f"参加者「{subject}」の座標に一定値があり、全読込行の座標z値を計算できません。")
        coordinates[indices] = (selected[indices] - mean) / sd
        centre = coordinates[baseline[-5:]].mean(axis=0)
        delta[indices] = coordinates[indices] - centre
        if len(baseline) > 5:
            limitations.append(f"参加者「{subject}」はBaseline{len(baseline)}行を正規化母集団に含み、中心には末尾5行だけを使っています。論文の対象行が5行なら、入力cohortを明示的に選び直してください。")
        subject_records.append({"id": str(subject), "rows": len(indices), "baselineRows": len(baseline), "taskRows": len(task), "postRows": int(len(indices) - len(baseline) - len(task)), "baselineIndices": baseline[-5:].tolist(), "taskIndices": task.tolist(), "normalizationIndices": indices.tolist(), "normalizerMean": mean.tolist(), "normalizerSd": sd.tolist(), "baselineCoordinateMean": centre.tolist()})
    times = _task_clock(df, paper, subjects, phases)
    mode = {"available": False, "source": "unavailable", "loading": None, "participantCount": 0, "loadedSubjects": len(subject_records), "energy": None, "reason": "単一参加者だけでは論文の共通loadingを再推定しません。外部参照を読込むか複数参加者を指定してください。"}
    if "loading" in paper:
        loading = paper["loading"]
        mode.update(available=True, source="external-loading", loading=loading["values"], participantCount=loading["participantCount"], energy=loading.get("energy"), referenceSource=loading["source"], reason=None)
        limitations.append("外部loadingの向き・尺度をそのまま使用します。入力C座標の定義と参照loadingの定義が一致することを確認してください。")
    elif len(subject_records) >= 2:
        loading, energy = _pooled_loading(coordinates, subjects, phases, paper["baselineLabel"], paper["taskLabel"])
        mode.update(available=True, source="loaded-subject-pooled-svd", loading=loading.tolist(), participantCount=len(subject_records), energy=energy, reason=None)
        limitations.append(f"共通loadingは現在読込んだ{len(subject_records)}参加者だけから再計算しました。論文の7参加者と同じ結果だと自動的には判断しません。")
    observed = np.full(len(df), np.nan)
    predicted = np.full(len(df), np.nan)
    fits = []
    if mode["available"]:
        projection = delta @ np.array(mode["loading"])
        for record in subject_records:
            indices, baseline, task = record["normalizationIndices"], record["baselineIndices"], record["taskIndices"]
            observed[indices] = projection[indices] - np.median(projection[baseline])
            fit = fit_paper_task(times[task], observed[task], observed[baseline], record["id"])
            fits.append(fit)
            if fit["status"] == "fitted":
                predicted[task] = [point["predicted"] for point in fit["points"]]
            if fit["reason"]:
                limitations.append(f"参加者「{record['id']}」: {fit['reason']}")
    # Reuse only the established generic PCA/table plumbing on the already
    # processed spectra. No current-profile preprocessing/Aquagram values survive.
    prepared = df.copy(deep=True)
    prepared.loc[:, columns] = processed
    prepared[paper["phaseColumn"]] = phases
    neutral = {"analysisProfile": "current", "analysisEngine": "python", "idColumn": config.get("idColumn"), "groupColumn": paper["phaseColumn"], "wavelengthColumns": columns, "range": [1300, 1600], "pipelineMode": "modern", "missing": "error", "scatter": "none", "smooth": False, "window": 3, "polyorder": 1, "derivative": 0, "pcaScale": False, "components": config.get("components", 3), "aquagramWavelengths": TARGETS.tolist(), "aquagramTolerance": float(np.max(abs(waves[positions] - TARGETS))) + 1e-9, "aquagramReference": "none", "pls": {"enabled": False}}
    result = wb.analyze(prepared, neutral)
    ids = result["spectra"]["ids"]
    result["spectra"]["raw"] = raw.tolist()
    applied = {**result["metadata"]["settings"], "analysisProfile": "paper-v1", "analysisEngine": "python", "scatter": "snv", "paper": paper, "aquagramWavelengths": TARGETS.tolist(), "aquagramReference": "group:" + paper["baselineLabel"], "pls": {"enabled": False}}
    execution = {"engine": "python", "preprocessingEngine": "python", "pcaEngine": "python", "aquagramEngine": "python", "implementationName": "Paper conditions / independent Python", "implementationVersion": VERSION, "api": "analyze_paper", "packageApiExecuted": False, "currentRunComparedWithR": False, "rRequired": False}
    groups = result["spectra"]["groups"]
    aq_groups = [{"name": group, "values": delta[np.array(groups) == group].mean(axis=0).tolist(), "n": groups.count(group)} for group in dict.fromkeys(groups)]
    result["aquagram"] = {"wavelengths": waves[positions].tolist(), "labels": LABELS, "groups": aq_groups, "reference": f"参加者ごとの{paper['baselineLabel']}末尾5行平均", "definition": DEFINITION, "mode": "paper-delta-C", "unit": "ΔC (subject-normalized)", "sdDdof": 1}
    result["metadata"].update(settings=applied, execution=execution, warnings=wb._import_notes(df) + limitations)
    if wb._is_artificial(df):
        result["metadata"]["warnings"].insert(0, wb.ARTIFICIAL + "の解析です。実測結果ではありません。")
    rows = [{"id": ids[i], "subject": str(subjects[i]), "phase": str(phases[i]), "timeSeconds": float(times[i]) if np.isfinite(times[i]) else None, "isTask": bool(phases[i] == paper["taskLabel"]), "coordinates": delta[i].tolist(), "modeObserved": float(observed[i]) if np.isfinite(observed[i]) else None, "modePredicted": float(predicted[i]) if np.isfinite(predicted[i]) else None} for i in range(len(df))]
    blocks = []
    block_indices = {}
    source_values = df["experiment_source_file"].tolist() if "experiment_source_file" in df else [None] * len(df)
    label_values = df["BlockLabel"].tolist() if "BlockLabel" in df else [None] * len(df)
    for i in range(len(df)):
        if phases[i] in {paper["baselineLabel"], paper["taskLabel"]}:
            continue
        source = str(source_values[i]) if pd.notna(source_values[i]) else None
        label = str(label_values[i]) if pd.notna(label_values[i]) else source or str(phases[i])
        key = (str(subjects[i]), str(phases[i]), source, label)
        block_indices.setdefault(key, []).append(i)
    for (subject, phase, source, label), indices in block_indices.items():
        values = observed[indices]
        blocks.append({"subject": subject, "phase": phase, "sourceFile": source, "label": label, "n": len(indices), "coordinateMean": delta[indices].mean(axis=0).tolist(), "modeMean": float(np.mean(values)) if np.isfinite(values).all() else None, "modeSd": float(np.std(values, ddof=1)) if len(values) > 1 and np.isfinite(values).all() else None})
    provenance = {"version": VERSION, "createdAt": datetime.now(timezone.utc).isoformat(), "implementation": "Independent Python paper-condition calculation; NumPy/SciPy; no R/aquap2 API execution", "aquap2Executed": False, "currentRunComparedWithR": False, "completePaperWorkflow": False,
                  "inputFingerprint": {"algorithm": "SHA-256", "selectedRawMatrix": hashlib.sha256(np.asarray(raw, dtype="<f8").tobytes(order="C")).hexdigest(), "selectedWavelengths": hashlib.sha256(np.asarray(waves, dtype="<f8").tobytes(order="C")).hexdigest(), "matrixEncoding": "row-major IEEE754 little-endian float64 before optional reflectance transform", "rows": len(df), "columns": columns, "normalizedInputCsvSha256": hashlib.sha256(wb._csv(df).encode("utf-8")).hexdigest(), "sourceBytesSha256": df.attrs.get("source_sha256") if re.fullmatch(r"[0-9a-f]{64}", str(df.attrs.get("source_sha256", ""))) else None},
                  "inputTransform": "CSV values unchanged; no additional log" if paper["inputKind"] == "as-recorded" else "-log10(R), explicitly requested positive reflectance values; physical units not inferred", "normalizationPopulation": "Every loaded row of each declared subject, including all loaded post blocks", "baselineSelection": "Last five matching Baseline rows in input order, following the retained MATLAB v1.3.4 reference", "rowSelection": "No rows excluded or reordered; cohort selection must be explicit before input", "taskClock": "Explicit selected clock; first Task value per subject is zero; Task input order strictly increasing; non-Task unreadable values retained as null", "timezonePolicy": "Offset-aware datetime converted to UTC; naive wall clocks treated consistently without inferring a timezone", "loadingDefinition": "Stack per-subject Task ΔC/sqrt(nTask); first right singular vector; sign so median(pooled @ loading)>=0. External loading keeps declared orientation.", "modeDefinition": "ΔC @ loading, then subtract median projection of the same five Baseline rows", "fitDefinition": "A*(1-exp(-max(t-d,0)/tau)); signed A, zero intercept; baseline-SD-scaled soft-L1; three transformed starts and Nelder-Mead. MATLAB and SciPy optimizer implementations differ.", "postBlocks": "Explicit file/BlockLabel records, unweighted block means and sample SD; minutes are not inferred from filenames; no LME", "physicalUnitsIndependentlyValidated": False}
    result["paper"] = {"profile": "paper-v1", "coordinateLabels": LABELS, "targetWavelengths": TARGETS.tolist(), "actualWavelengths": waves[positions].tolist(), "preprocessing": {"range": [1300, 1600], "channels": len(columns), "actualRange": [float(waves[0]), float(waves[-1])], "inputKind": paper["inputKind"], "snvDdof": 1, "columnSdDdof": 1, "smoothing": False, "normalizationPopulation": "all-loaded-rows-per-subject", "baselineRule": "last-five-baseline-rows-in-input-order"}, "timeAxis": {"kind": "seconds", "definition": provenance["taskClock"]}, "subjects": subject_records, "rows": rows, "mode": mode, "fits": fits, "blocks": blocks, "provenance": provenance, "limitations": limitations}
    # Preserve real source input; the generic PCA helper saw the SNV copy only.
    result["exports"]["data/input.csv"] = wb._csv(df)
    result["exports"]["README.txt"] = "論文条件プロファイル / independent Python\n" + DEFINITION + "\nPCAはnative SNVスペクトルの平均中心化です。共通モードSVDとは別の探索表示です。\n" + "\n".join(limitations) + "\n"
    if wb._is_artificial(df):
        result["exports"]["README.txt"] += wb.ARTIFICIAL + "です。実測結果ではありません。\n"
    metadata_df = df.copy()
    metadata_df["paper_subject"] = subjects
    metadata_df["paper_phase"] = phases
    metadata_df["paper_time_seconds"] = [float(t) if np.isfinite(t) else None for t in times]
    metadata_df["paper_series"] = [f"{subject} / {phase}" for subject, phase in zip(subjects, phases)]
    metadata_keys = ["paper_subject", "paper_phase", "paper_time_seconds", "paper_series"]
    metadata_df = metadata_df[metadata_keys + [column for column in metadata_df if column not in metadata_keys]]
    wb._attach_aquagram_samples(metadata_df, result, delta, DEFINITION)
    # Explicit time/series metadata remains available even with many imported
    # experiment_ metadata columns, while respecting the existing 64-column cap.
    saved_meta = result["aquagram"]["samples"]["metadata"]
    preferred = {key: [wb._aquagram_metadata_scalar(value) for value in metadata_df[key]] for key in metadata_keys}
    saved_meta = dict(list({**preferred, **{key: value for key, value in saved_meta.items() if key not in preferred}}.items())[:wb.AQUAGRAM_METADATA_COLUMNS])
    result["aquagram"]["samples"]["metadata"] = saved_meta
    sample_export = json.loads(result["exports"]["aquagram_samples.json"])
    sample_export["samples"]["metadata"] = saved_meta
    result["exports"]["aquagram_samples.json"] = _json(sample_export)
    def table(matrix):
        frame = pd.DataFrame(matrix, columns=LABELS)
        frame.insert(0, "phase", phases); frame.insert(0, "subject", subjects); frame.insert(0, "sample_id", ids)
        frame.insert(3, "task_relative_time_seconds", times)
        return frame
    result["exports"].update({"paper/normalized_coordinates.csv": wb._csv(table(coordinates)), "paper/delta_coordinates.csv": wb._csv(table(delta)), "paper/normalization.json": _json(subject_records), "paper/results.json": _json(result["paper"]), "paper/provenance.json": _json(provenance),
        "paper/common_mode.csv": wb._csv(pd.DataFrame({"sample_id": ids, "subject": subjects, "phase": phases, "task_relative_time_seconds": times, "mode_observed": observed, "mode_predicted_task_only": predicted})),
        "paper/task_fits.csv": wb._csv(pd.DataFrame([{k: v for k, v in fit.items() if k not in {"points", "bounds", "optimizer"}} for fit in fits])),
        "paper/post_blocks.csv": wb._csv(pd.DataFrame([{**{k: v for k, v in block.items() if k != "coordinateMean"}, **dict(zip(LABELS, block["coordinateMean"]))} for block in blocks])),
        "data/aquagram.csv": wb._csv(pd.DataFrame([{"group": group["name"], "n": group["n"], "coordinate": LABELS[j], "wavelength_nm": waves[positions[j]], "value": value} for group in aq_groups for j, value in enumerate(group["values"])])),
        "settings.json": _json({**applied, "_provenance": {"source": {"filename": df.attrs.get("source_name", "データ"), "artificial": wb._is_artificial(df)}, "requestedConfig": copy.deepcopy(config), "paper": provenance}})})
    if mode["available"]:
        result["exports"]["paper/reference_loading.csv"] = wb._csv(pd.DataFrame({"CoordinateIndex": range(1, 13), "Coordinate": LABELS, "CommonLoading": mode["loading"], "PooledModeEnergy": mode["energy"], "ParticipantCount": mode["participantCount"], "UsedForLoading": True}))
    return result


def paper_demo_dataset():
    """Seven deterministic artificial subjects; no private reference constants."""
    import workbench as wb
    waves = np.arange(1280.0, 1620.1, 5.0)
    records = []
    for subject in range(7):
        schedule = [("Baseline", -25 + i * 5, "Baseline") for i in range(5)]
        schedule += [("Task", float(i * 15), "Task") for i in range(21)]
        schedule += [("Recovery", float(390 + block * 120 + i * 5), f"Post-{block + 1}") for block in range(3) for i in range(5)]
        for row, (phase, time, block) in enumerate(schedule):
            response = (1 - np.exp(-max(time - 18, 0) / (55 + subject * 4))) if phase == "Task" else (.35 * np.exp(-max(time - 300, 0) / 180) if phase == "Recovery" else 0)
            signal = .2 + .00012 * (waves - 1300) + (.4 + .004 * subject + .025 * response) * np.exp(-.5 * ((waves - 1450) / 42) ** 2)
            signal += (.08 - .012 * response) * np.exp(-.5 * ((waves - 1370) / 23) ** 2)
            signal += .0004 * np.sin(waves / 17 + row * .71 + subject) + .0002 * np.cos(waves / 11 + row * .39)
            record = {"sample_id": f"PAPER-DEMO-{subject + 1:02d}-{row + 1:03d}", "subject": f"Artificial-{subject + 1}", "phase": phase, "time_seconds": time, "BlockLabel": block, "data_origin": wb.ARTIFICIAL}
            record.update({f"wl_{wave:g}": float(value) for wave, value in zip(waves, signal)})
            records.append(record)
    frame = pd.DataFrame(records)
    frame.attrs.update(source_name="論文条件・人工7参加者デモ.csv", artificial=True, source_sheet=None)
    return frame, wb._summary(frame, frame.attrs["source_name"], [], None)

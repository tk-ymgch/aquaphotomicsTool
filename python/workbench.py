"""Browser-compatible spectral analysis, independent of any user interface.

The three entry points are inspect_bytes, demo_dataset and analyze. All returned
objects contain only JSON-compatible values; raw tables remain in the worker.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import numpy as np
import pandas as pd

ENGINE_VERSION = "1.0.0"
MAX_MATRIX_ELEMENTS = 2_000_000
MAX_VARIABLES = 10_000
VARIABLE_LIMIT_MESSAGE = "解析する波長数は1万列までです。波長列の選択または波長範囲を減らしてください。"
ARTIFICIAL = "人工データ（実測値ではありません）"
GLOBAL_REFERENCE = "global"
AQUAGRAM_DEFINITION = (
    "前処理後の指定波長における（群平均 − 基準平均）÷ 全試料の標準偏差（ddof=0）。"
    "基準は全体平均または選択した対照群平均です。標準偏差が0の波長の値は0とします。"
    "分子種の同定・定量や温度校正を行う方式ではありません。"
)


def _filename(name: str) -> str:
    return re.split(r"[/\\]", str(name))[-1] or "データ"


def parse_wavelength(column: str) -> float | None:
    """Recognize complete wavelength labels, without matching sample_001 etc."""
    text = str(column).strip()
    number = r"([+]?(?:\d+(?:\.\d*)?|\.\d+))"
    patterns = [
        rf"{number}\s*(?:nm)?",
        rf"(?:wl|wavelength|wave|nm|x)[_\-\s]*{number}\s*(?:nm)?",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1))
            if np.isfinite(value) and value > 0:
                return value
    return None


def _headers(values: list[Any]) -> list[str]:
    columns = []
    seen = set()
    for value in values:
        if pd.isna(value):
            raise ValueError("列名に空欄があります。すべての列に名前を付けてください。")
        column = str(value).strip().lstrip("\ufeff")
        if not column:
            raise ValueError("列名に空欄があります。すべての列に名前を付けてください。")
        if column in seen:
            raise ValueError(f"列名「{column}」が重複しています。列名を一意にしてください。")
        seen.add(column)
        columns.append(column)
    if not columns:
        raise ValueError("列名が見つかりません。1行目を列名にしてください。")
    return columns


def _preview_value(value: Any) -> str | int | float | None:
    if pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return str(value)


def _suggest(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lower = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in lower:
            return lower[candidate]
    return None


def _is_artificial(df: pd.DataFrame) -> bool:
    if df.attrs.get("artificial", False):
        return True
    return "data_origin" in df.columns and len(df) > 0 and bool(
        df["data_origin"].astype(str).eq(ARTIFICIAL).all()
    )


def _summary(df: pd.DataFrame, name: str, sheets: list[str], sheet: str | None) -> dict:
    columns = list(df.columns)
    wavelengths = []
    for column in columns:
        wavelength = parse_wavelength(column)
        # Keep labeled spectral columns even when values are missing. The
        # analysis's explicit missing-data policy, not detection, handles them.
        if wavelength is not None:
            wavelengths.append({"column": column, "wavelength": wavelength})
            if len(wavelengths) > MAX_VARIABLES:
                raise ValueError(VARIABLE_LIMIT_MESSAGE)
    wavelengths.sort(key=lambda item: item["wavelength"])
    shown_name = name
    if _is_artificial(df) and "人工" not in name:
        shown_name = f"{name} — {ARTIFICIAL}"
    return {
        "name": shown_name,
        "artificial": _is_artificial(df),
        "columns": columns,
        "preview": [[_preview_value(v) for v in row] for row in df.head(12).itertuples(index=False, name=None)],
        "rowCount": int(len(df)),
        "sheets": sheets,
        "sheet": sheet,
        "suggestedId": _suggest(columns, ("sample_id", "sample", "id", "name", "試料id", "試料名", "サンプルid")),
        "suggestedGroup": _suggest(columns, ("group", "class", "condition", "treatment", "label", "群", "グループ", "条件")),
        "wavelengthColumns": wavelengths,
    }


def inspect_bytes(data: bytes, filename: str, sheet: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Read a UTF-8/CP932 CSV or an explicitly selected Excel worksheet."""
    name = _filename(filename)
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise ValueError("CSV、XLSX、XLSファイルを選択してください。")
    if not data:
        raise ValueError("ファイルが空です。データを含むファイルを選択してください。")
    sheets: list[str] = []
    selected_sheet: str | None = None
    try:
        if suffix == ".csv":
            text = None
            for encoding in ("utf-8-sig", "cp932"):
                try:
                    text = bytes(data).decode(encoding)
                    break
                except UnicodeDecodeError:
                    pass
            if text is None:
                raise ValueError("文字コードを読み取れません。CSVをUTF-8またはCP932で保存してください。")
            reader = csv.reader(io.StringIO(text))
            header = next(reader, [])
            columns = _headers(header)
            for record_index, record in enumerate(reader, start=2):
                if record and len(record) != len(columns):
                    raise ValueError(f"CSVの{record_index}行目で列数が一致しません。区切り文字と引用符を確認してください。")
            df = pd.read_csv(io.StringIO(text), header=0)
            if len(df.columns) != len(columns):
                raise ValueError("列名とデータの列数が一致しません。CSVの区切りを確認してください。")
            df.columns = columns
        else:
            engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
            with pd.ExcelFile(io.BytesIO(bytes(data)), engine=engine) as book:
                sheets = list(book.sheet_names)
                if not sheets:
                    raise ValueError("Excelにワークシートがありません。")
                selected_sheet = sheet if sheet is not None else sheets[0]
                if selected_sheet not in sheets:
                    raise ValueError(f"シート「{selected_sheet}」が見つかりません。シートを選び直してください。")
                raw = pd.read_excel(book, sheet_name=selected_sheet, header=None)
                if raw.empty:
                    raise ValueError("選択したシートが空です。")
                columns = _headers(raw.iloc[0].tolist())
                df = raw.iloc[1:].copy()
                df.columns = columns
                df.reset_index(drop=True, inplace=True)
    except ImportError as exc:
        label = "XLS" if suffix == ".xls" else "XLSX"
        raise ValueError(f"{label}の読み込みに必要なライブラリがありません。解析環境の読み込みをやり直してください。") from exc
    except ValueError as exc:
        # Preserve the actionable Japanese validation messages above, and wrap
        # library parsing messages so no raw Python error becomes the UI text.
        if re.search(r"[ぁ-んァ-ン一-龥]", str(exc)):
            raise
        raise ValueError("ファイルを読み込めません。形式、列名、Excelの保護設定を確認してください。") from exc
    except Exception as exc:
        raise ValueError("ファイルを読み込めません。形式、列の区切り、ファイルの破損を確認してください。") from exc
    df = df.dropna(how="all").reset_index(drop=True)
    if df.empty:
        raise ValueError("解析するデータ行がありません。1行目を列名、2行目以降を試料にしてください。")
    df.attrs.update(source_name=name, source_sheet=selected_sheet)
    df.attrs["artificial"] = _is_artificial(df)
    return df, _summary(df, name, sheets, selected_sheet)


def demo_dataset() -> tuple[pd.DataFrame, dict]:
    """Deterministic artificial spectra. No measured or molecular data are used."""
    rng = np.random.default_rng(20261021)
    wavelengths = np.arange(1300.0, 1600.1, 5.0)
    records = []
    for group_index in range(3):
        for sample_index in range(15):
            baseline = 0.19 + 0.00012 * (wavelengths - 1300)
            broad = (0.40 + 0.025 * group_index) * np.exp(-0.5 * ((wavelengths - 1450) / 42) ** 2)
            shoulder = (0.08 - 0.015 * group_index) * np.exp(-0.5 * ((wavelengths - 1370) / 23) ** 2)
            signal = (baseline + broad + shoulder) * rng.normal(1.0, 0.015)
            signal += rng.normal(0, 0.002, len(wavelengths)) + rng.normal(0, 0.003)
            row = {"sample_id": f"DEMO-{group_index * 15 + sample_index + 1:03d}",
                   "group": f"人工群 {chr(65 + group_index)}", "data_origin": ARTIFICIAL}
            row.update({f"wl_{wl:g}": float(value) for wl, value in zip(wavelengths, signal)})
            records.append(row)
    df = pd.DataFrame(records)
    df.attrs.update(source_name="人工デモデータ.csv", source_sheet=None, artificial=True)
    return df, _summary(df, f"人工デモデータ — {ARTIFICIAL}", [], None)


def _integer(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label}は{minimum}以上の整数で指定してください。")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label}は{minimum}以上の整数で指定してください。") from exc
    if not np.isfinite(number) or not number.is_integer() or number < minimum:
        raise ValueError(f"{label}は{minimum}以上の整数で指定してください。")
    return int(number)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label}は有限の数値で指定してください。")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{label}は有限の数値で指定してください。") from exc
    if not np.isfinite(number):
        raise ValueError(f"{label}は有限の数値で指定してください。")
    return number


def _scatter_correct(x: np.ndarray, mode: str) -> np.ndarray:
    if mode == "none":
        return x.copy()
    if mode == "snv":
        std = x.std(axis=1, ddof=0)
        if np.any(std == 0):
            raise ValueError("一定値のスペクトルがあるためSNVを計算できません。試料データまたは散乱補正を確認してください。")
        return (x - x.mean(axis=1, keepdims=True)) / std[:, None]
    if mode == "msc":
        reference = x.mean(axis=0)
        centered = reference - reference.mean()
        denominator = float(centered @ centered)
        if denominator == 0:
            raise ValueError("平均スペクトルが一定値のためMSCを計算できません。散乱補正を変更してください。")
        means = x.mean(axis=1)
        slopes = (x - means[:, None]) @ centered / denominator
        if np.any(~np.isfinite(slopes)) or np.any(np.abs(slopes) < 1e-12):
            raise ValueError("MSCの回帰傾きが0に近い試料があります。試料データまたは散乱補正を確認してください。")
        intercepts = means - slopes * reference.mean()
        return (x - intercepts[:, None]) / slopes[:, None]
    raise ValueError("散乱補正は「なし」「SNV」「MSC」から選択してください。")


def _labels(df: pd.DataFrame, column: str | None, role: str) -> list[str]:
    if column is None:
        return [f"S{i + 1:03d}" for i in range(len(df))] if role == "試料ID" else ["全試料"] * len(df)
    if not isinstance(column, str) or column not in df.columns:
        raise ValueError(f"{role}の列が見つかりません。列を選び直してください。")
    series = df[column]
    if series.isna().any() or series.astype(str).str.strip().eq("").any():
        raise ValueError(f"{role}の列に空欄があります。ラベルを入力してください。")
    return series.astype(str).tolist()


def _csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, lineterminator="\n")


def analyze(df: pd.DataFrame, config: dict) -> dict:
    """Apply a validated pipeline and return data, plots' arrays and text exports.

    Order: missing-data handling -> scatter correction -> uniform interpolation
    when SG is requested on uneven wavelengths -> SG smoothing/derivative.
    PCA always centers variables; optional scaling uses population SD (ddof=0).
    """
    # Loaded on demand: inspecting a file requires only NumPy and pandas in
    # Pyodide; the worker loads SciPy and scikit-learn before analysis.
    import scipy
    import sklearn
    from scipy.signal import savgol_filter
    from sklearn.decomposition import PCA

    if not isinstance(df, pd.DataFrame) or len(df) < 2:
        raise ValueError("解析には2試料以上が必要です。")
    if not isinstance(config, dict):
        raise ValueError("解析設定を読み取れません。設定を確認してください。")
    if not df.columns.is_unique:
        raise ValueError("列名が重複しています。列名を一意にしてください。")
    selected = config.get("wavelengthColumns")
    if not isinstance(selected, list) or len(selected) < 3 or any(not isinstance(c, str) for c in selected):
        raise ValueError("波長列を3列以上選択してください。")
    if len(set(selected)) != len(selected):
        raise ValueError("選択した波長列が重複しています。")
    entries = []
    for column in selected:
        if column not in df.columns:
            raise ValueError(f"波長列「{column}」が見つかりません。列を選び直してください。")
        wavelength = parse_wavelength(column)
        if wavelength is None:
            raise ValueError(f"列「{column}」から波長を取得できません。wl_1450などの列名にしてください。")
        entries.append((wavelength, column))
    entries.sort()
    if len(set(wl for wl, _ in entries)) != len(entries):
        raise ValueError("同じ波長を示す列が複数あります。波長が一意になるよう選択してください。")
    crop = config.get("range")
    if not isinstance(crop, (list, tuple)) or len(crop) != 2:
        raise ValueError("波長範囲の下限と上限を指定してください。")
    low, high = [_finite(value, "波長範囲") for value in crop]
    if low >= high:
        raise ValueError("波長範囲の下限は上限より小さくしてください。")
    entries = [(wl, column) for wl, column in entries if low <= wl <= high]
    if len(entries) < 3:
        raise ValueError("選択した波長範囲に3列以上の波長が必要です。")
    if len(entries) > MAX_VARIABLES:
        raise ValueError(VARIABLE_LIMIT_MESSAGE)
    if len(df) * len(entries) > MAX_MATRIX_ELEMENTS:
        raise ValueError("解析行列は200万要素（試料数×選択波長数）までです。試料数または波長列・範囲を減らしてください。")
    wavelengths = np.array([wl for wl, _ in entries], dtype=float)
    columns = [column for _, column in entries]
    ids = _labels(df, config.get("idColumn"), "試料ID")
    groups = _labels(df, config.get("groupColumn"), "群")
    group_names = list(dict.fromkeys(groups))
    warnings: list[str] = []
    artificial = _is_artificial(df)
    if artificial:
        warnings.append(f"この解析は{ARTIFICIAL}を使用しています。実験結果として解釈しないでください。")
    if len(set(ids)) != len(ids):
        raise ValueError("試料IDが重複しています。一意のID列を指定するか、試料IDの列を「行番号を使用」にしてください。")
    missing = config.get("missing", "error")
    if missing not in {"error", "median"}:
        raise ValueError("欠損処理は「エラー」または「列の中央値で補完」を選択してください。")
    try:
        x = df.loc[:, columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError("波長列を数値に変換できません。データ形式を確認してください。") from exc
    invalid = ~np.isfinite(x)
    imputed: dict[str, dict] = {}
    if invalid.any():
        if missing == "error":
            raise ValueError(f"波長列に欠損、非数値、または無限大が{int(invalid.sum())}個あります。データを修正するか中央値補完を選択してください。")
        for j, column in enumerate(columns):
            mask = invalid[:, j]
            if mask.all():
                raise ValueError(f"波長列「{column}」に有効な数値がありません。中央値補完はできません。")
            if mask.any():
                median = float(np.median(x[~mask, j]))
                x[mask, j] = median
                imputed[column] = {"count": int(mask.sum()), "median": median}
        warnings.append(f"欠損・非数値・無限大の{int(invalid.sum())}セルを各波長列の中央値で補完しました。")
    scatter = config.get("scatter", "none")
    if not isinstance(scatter, str):
        raise ValueError("散乱補正の設定を確認してください。")
    processed = _scatter_correct(x, scatter)
    smooth = config.get("smooth", False)
    scale_pca = config.get("pcaScale", False)
    if not isinstance(smooth, bool) or not isinstance(scale_pca, bool):
        raise ValueError("平滑化とPCAスケーリングの設定を確認してください。")
    derivative = _integer(config.get("derivative", 0), "微分次数", 0)
    if derivative not in {0, 1, 2}:
        raise ValueError("微分次数は0、1、2から選択してください。")
    window = _integer(config.get("window", 11), "SG窓幅", 3)
    polyorder = _integer(config.get("polyorder", 2), "SG多項式次数", 0)
    use_sg = smooth or derivative > 0
    interpolated = False
    raw = x.copy()
    original_wavelengths = wavelengths.copy()
    if use_sg:
        if window % 2 == 0 or window > len(wavelengths):
            raise ValueError(f"SG窓幅は3以上の奇数で、選択波長数（{len(wavelengths)}）以下にしてください。")
        if polyorder >= window or polyorder < derivative:
            raise ValueError("SG多項式次数は窓幅未満、かつ微分次数以上にしてください。")
        differences = np.diff(wavelengths)
        if not np.allclose(differences, differences[0], rtol=1e-6, atol=1e-9):
            interpolated = True
            uniform = np.linspace(wavelengths[0], wavelengths[-1], len(wavelengths))
            raw = np.array([np.interp(uniform, wavelengths, row) for row in x])
            processed = np.array([np.interp(uniform, wavelengths, row) for row in processed])
            wavelengths = uniform
            warnings.append("不等間隔の波長をSG処理前に同じ点数の等間隔格子へ線形補間しました。スペクトルの処理前表示も同じ格子です。元の値はinput.csvに保存されます。")
        processed = savgol_filter(processed, window, polyorder, deriv=derivative,
                                  delta=float(wavelengths[1] - wavelengths[0]), axis=1, mode="interp")
        if derivative > 0 and not smooth:
            warnings.append("微分はSavitzky–Golay法で計算しています。平滑化がオフでも微分用の多項式フィルターを適用します。")
    if not np.isfinite(processed).all():
        raise ValueError("前処理後に有限でない値が生じました。入力値と前処理設定を確認してください。")

    requested_components = _integer(config.get("components", 3), "PCA成分数", 1)
    components = min(requested_components, len(df) - 1, processed.shape[1])
    if components != requested_components:
        warnings.append(f"PCA成分数を試料数・変数数に合わせて{components}に制限しました。")
    pca_input = processed.copy()
    pca_std = pca_input.std(axis=0, ddof=0)
    constant = pca_std == 0
    if constant.any():
        warnings.append(f"前処理後に一定値となる波長が{int(constant.sum())}個あります。PCAでは平均中心化後に0として扱います。")
    if scale_pca:
        scales = np.where(constant, 1.0, pca_std)
        pca_input = (pca_input - pca_input.mean(axis=0)) / scales
    if not np.any(pca_input != pca_input[0]):
        raise ValueError("前処理後の試料間変動がすべて0のためPCAを計算できません。入力データと前処理を確認してください。")
    try:
        model = PCA(n_components=components, svd_solver="full")
        scores = model.fit_transform(pca_input)
    except Exception as exc:
        raise ValueError("PCAを計算できません。数値の大きさや前処理設定を確認してください。") from exc
    loadings = model.components_.T
    explained = model.explained_variance_ratio_
    if not np.isfinite(scores).all() or not np.isfinite(explained).all():
        raise ValueError("PCAの結果が有限値になりません。入力値の大きさや試料間変動を確認してください。")

    targets = config.get("aquagramWavelengths")
    if not isinstance(targets, list) or len(targets) < 3:
        raise ValueError("Aquagramの波長を3点以上指定してください。")
    targets = sorted(_finite(value, "Aquagramの波長") for value in targets)
    if len(set(targets)) != len(targets):
        raise ValueError("Aquagramの指定波長が重複しています。異なる波長を指定してください。")
    tolerance = _finite(config.get("aquagramTolerance", 2.5), "Aquagramの許容誤差")
    if tolerance < 0:
        raise ValueError("Aquagramの許容誤差は0以上にしてください。")
    positions = []
    mappings = []
    for target in targets:
        if target < wavelengths[0] or target > wavelengths[-1]:
            raise ValueError(f"Aquagramの指定波長 {target:g} nm は解析範囲外です。波長範囲または指定波長を変更してください。")
        index = int(np.argmin(np.abs(wavelengths - target)))
        actual = float(wavelengths[index])
        difference = abs(actual - target)
        if difference > tolerance + max(1.0, abs(target)) * 1e-12:
            raise ValueError(f"Aquagramの指定波長 {target:g} nm に許容誤差内の波長がありません。最近傍は {actual:g} nm です。")
        if index in positions:
            raise ValueError("Aquagramの複数の指定波長が同じ測定波長に対応しています。指定波長を離すかデータを確認してください。")
        positions.append(index)
        mappings.append({"requested": target, "actual": actual, "difference": difference})
    actual_targets = [float(wavelengths[i]) for i in positions]
    if any(item["difference"] > max(1.0, abs(item["requested"])) * 1e-12 for item in mappings):
        warnings.append("Aquagramは許容誤差内の最近傍波長を使用しています。実際の波長は軸とsettings.jsonに記録されています。")
    reference = config.get("aquagramReference", GLOBAL_REFERENCE)
    if not isinstance(reference, str):
        raise ValueError("Aquagramの基準を選択してください。")
    if reference.startswith("group:"):
        reference_group = reference[len("group:"):]
        if reference_group not in group_names:
            raise ValueError(f"Aquagramの対照群「{reference_group}」が見つかりません。基準を選び直してください。")
        reference_mask = np.array(groups) == reference_group
        reference_label = f"対照群: {reference_group}"
    elif reference in {GLOBAL_REFERENCE, "Global mean", "全体平均"}:
        reference = GLOBAL_REFERENCE
        reference_label = "全体平均"
        reference_mask = np.ones(len(df), dtype=bool)
    else:
        if reference not in group_names:
            raise ValueError(f"Aquagramの対照群「{reference}」が見つかりません。基準を選び直してください。")
        reference_mask = np.array(groups) == reference
        reference_label = f"対照群: {reference}"
    aq_x = processed[:, positions]
    aq_std = aq_x.std(axis=0, ddof=0)
    aq_constant = aq_std == 0
    if aq_constant.any():
        warnings.append("Aquagramの標準偏差が0の波長は、群平均差も0のため表示値を0としました。")
    denominator = np.where(aq_constant, 1.0, aq_std)
    reference_mean = aq_x[reference_mask].mean(axis=0)
    aq_groups = []
    aq_rows = []
    for group in group_names:
        mask = np.array(groups) == group
        values = (aq_x[mask].mean(axis=0) - reference_mean) / denominator
        values[aq_constant] = 0.0
        aq_groups.append({"name": group, "values": values.tolist(), "n": int(mask.sum())})
        aq_rows.extend({"group": group, "n": int(mask.sum()), "wavelength_nm": wl, "value": float(value)}
                       for wl, value in zip(actual_targets, values))
    if len(group_names) == 1:
        warnings.append("群が1つのため、この基準に対するAquagramの群平均差は0です。")

    applied = {
        "idColumn": config.get("idColumn"), "groupColumn": config.get("groupColumn"),
        "wavelengthColumns": columns, "range": [float(wavelengths[0]), float(wavelengths[-1])],
        "missing": missing, "scatter": scatter, "smooth": smooth, "window": window,
        "polyorder": polyorder, "derivative": derivative, "pcaScale": scale_pca,
        "components": components, "aquagramWavelengths": actual_targets,
        "aquagramReference": reference, "aquagramTolerance": tolerance,
    }
    pc_names = [f"PC{i + 1}" for i in range(components)]
    processed_df = pd.DataFrame(processed, columns=[f"wl_{wl:.12g}" for wl in wavelengths])
    processed_df.insert(0, "group", groups)
    processed_df.insert(0, "sample_id", ids)
    scores_df = pd.DataFrame(scores, columns=pc_names)
    scores_df.insert(0, "group", groups)
    scores_df.insert(0, "sample_id", ids)
    loadings_df = pd.DataFrame(loadings, columns=pc_names)
    loadings_df.insert(0, "wavelength_nm", wavelengths)
    provenance = {
        "schemaVersion": "1.0", "engineVersion": ENGINE_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "source": {"filename": df.attrs.get("source_name", "データ"),
                   "sheet": df.attrs.get("source_sheet"), "artificial": artificial},
        "requestedConfig": config,
        "pipeline": ["欠損処理", "散乱補正", "必要時に等間隔線形補間", "SG平滑化・微分"],
        "interpolated": interpolated, "originalWavelengths": original_wavelengths.tolist(),
        "appliedWavelengths": wavelengths.tolist(), "imputed": imputed,
        "sgApplied": use_sg, "sgMode": "interp", "snvDdof": 0,
        "mscReference": "欠損処理後の全試料平均スペクトル",
        "pcaCentered": True, "pcaScaleDdof": 0, "pcaMean": model.mean_.tolist(),
        "pcaProcessedMean": processed.mean(axis=0).tolist(),
        "pcaInputScales": np.where(constant, 1.0, pca_std).tolist() if scale_pca else [1.0] * len(columns),
        "aquagramDefinition": AQUAGRAM_DEFINITION,
        "aquagramMappings": mappings, "warnings": warnings,
        "versions": {"numpy": np.__version__, "pandas": pd.__version__,
                     "scipy": scipy.__version__, "scikit-learn": sklearn.__version__},
    }
    settings_export = {**applied, "_provenance": provenance}
    readme = (
        "Aquaphotomics Workbench 解析出力\n"
        + (f"\nこの出力は{ARTIFICIAL}の解析です。実験結果ではありません。\n" if artificial else "")
        + "\n1行が1試料、波長の単位はnmです。入力データはdata/input.csvに保存しています。\n"
        "data/preprocessed.csv: 欠損処理・散乱補正・必要時の補間・SG処理後の値。\n"
        "data/pca_scores.csv: 試料×成分。data/pca_loadings.csv: 波長×成分。\n"
        "data/pca_variance.csv: 寄与率（0〜1）と累積寄与率。\n"
        "PCAは常に平均中心化し、設定により各波長の標準偏差（ddof=0）でスケーリングします。\n"
        "微分を指定した場合は、平滑化スイッチの状態によらずSG多項式フィルターを適用します。\n"
        "不等間隔波長はSG前に同点数の等間隔格子へ線形補間します。補間は測定分解能を高めるものではありません。\n"
        f"\nAquagramの定義: {AQUAGRAM_DEFINITION}\n基準: {reference_label}\n"
        "settings.jsonの直下は適用設定、_provenanceは元設定・補間・補完値・実行版の記録です。\n"
        "この解析は探索的な表示であり、統計的有意差や未知試料への予測性能を評価しません。\n"
        + ("\n解析時の通知:\n" + "\n".join(f"- {warning}" for warning in warnings) + "\n" if warnings else "")
    )
    result = {
        "metadata": {"samples": int(len(df)), "variables": len(columns), "groups": group_names,
                     "range": applied["range"], "warnings": warnings, "settings": applied},
        "spectra": {"wavelengths": wavelengths.tolist(), "raw": raw.tolist(), "processed": processed.tolist(), "ids": ids, "groups": groups},
        "pca": {"scores": scores.tolist(), "loadings": loadings.tolist(), "explainedVariance": explained.tolist(), "ids": ids, "groups": groups},
        "aquagram": {"wavelengths": actual_targets, "labels": [f"{wl:g} nm" for wl in actual_targets],
                     "groups": aq_groups, "reference": reference_label, "definition": AQUAGRAM_DEFINITION},
        "exports": {
            "data/input.csv": _csv(df), "data/preprocessed.csv": _csv(processed_df),
            "data/pca_scores.csv": _csv(scores_df), "data/pca_loadings.csv": _csv(loadings_df),
            "data/pca_variance.csv": _csv(pd.DataFrame({"component": pc_names, "explained_variance_ratio": explained, "cumulative_ratio": np.cumsum(explained)})),
            "data/aquagram.csv": _csv(pd.DataFrame(aq_rows)),
            "settings.json": json.dumps(settings_export, ensure_ascii=False, indent=2, allow_nan=False),
            "README.txt": readme,
        },
    }
    return result

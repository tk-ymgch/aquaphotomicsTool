from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from scipy.signal import savgol_filter
from sklearn.cross_decomposition import PLSRegression
from sklearn.decomposition import PCA
from sklearn.preprocessing import LabelEncoder

APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / ".runtime"
SAMPLE_FILE = APP_DIR / "sample_data" / "sample_spectra.csv"
NAVY = "#1f2f54"
BLACK = "#000000"
WHITE = "#ffffff"
GRAY_50 = "#f4f5f7"
GRAY_100 = "#e5e7eb"
GRAY_300 = "#b8beca"
GRAY_500 = "#6b7280"
GRAY_700 = "#374151"
PALETTE = [NAVY, BLACK, GRAY_700, GRAY_500, GRAY_300]

st.set_page_config(
    page_title="Aquaphotomics Workbench",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_css() -> None:
    st.markdown(
        f"""
        <style>
        html, body, [data-testid="stAppViewContainer"] {{
            background: {WHITE};
            color: {BLACK};
        }}
        [data-testid="stSidebar"] {{
            background: {GRAY_50};
            border-right: 1px solid {GRAY_100};
        }}
        .block-container {{
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }}
        h1, h2, h3, h4 {{
            color: {NAVY};
            letter-spacing: -0.02em;
        }}
        .hero {{
            border: 1px solid {GRAY_100};
            border-radius: 22px;
            padding: 1.5rem 1.6rem;
            background: linear-gradient(180deg, {WHITE} 0%, {GRAY_50} 100%);
            margin-bottom: 1.2rem;
        }}
        .hero-title {{
            font-size: 2.3rem;
            line-height: 1.08;
            font-weight: 760;
            color: {NAVY};
            margin-bottom: .35rem;
        }}
        .hero-subtitle {{
            font-size: 1.02rem;
            color: {GRAY_700};
            max-width: 880px;
        }}
        .card {{
            border: 1px solid {GRAY_100};
            border-radius: 18px;
            padding: 1.1rem 1.15rem;
            background: {WHITE};
            box-shadow: 0 1px 2px rgba(0,0,0,.03);
        }}
        .mini-label {{
            color: {GRAY_500};
            font-size: .80rem;
            text-transform: uppercase;
            letter-spacing: .08em;
            margin-bottom: .2rem;
        }}
        .mini-value {{
            color: {BLACK};
            font-size: 1.45rem;
            font-weight: 720;
        }}
        .section-note {{
            color: {GRAY_500};
            font-size: .92rem;
        }}
        div.stButton > button:first-child,
        div.stDownloadButton > button:first-child {{
            border-radius: 999px;
            border: 1px solid {NAVY};
            background: {NAVY};
            color: {WHITE};
            font-weight: 650;
            padding: .55rem 1.1rem;
        }}
        div.stButton > button:first-child:hover,
        div.stDownloadButton > button:first-child:hover {{
            border-color: {BLACK};
            background: {BLACK};
            color: {WHITE};
        }}
        [data-testid="stMetricValue"] {{
            color: {NAVY};
        }}
        [data-testid="stDataFrame"] {{
            border: 1px solid {GRAY_100};
            border-radius: 14px;
        }}
        .status-pill {{
            display: inline-block;
            padding: .28rem .7rem;
            border-radius: 999px;
            border: 1px solid {GRAY_300};
            background: {WHITE};
            color: {GRAY_700};
            font-size: .85rem;
            margin-right: .35rem;
        }}
        .status-pill strong {{ color: {NAVY}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def parse_wavelength(name: str) -> float | None:
    text = str(name).strip()
    direct = re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text)
    if direct:
        return float(text)
    patterns = [
        r"(?:wl|wavelength|wave|nm|x)[_\- ]*([-+]?\d+(?:\.\d+)?)",
        r"([-+]?\d+(?:\.\d+)?)\s*(?:nm)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


@st.cache_data(show_spinner=False)
def load_table_from_bytes(data: bytes, name: str) -> pd.DataFrame:
    suffix = Path(name).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(data))
    try:
        return pd.read_csv(io.BytesIO(data))
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(data), encoding="cp932")


@st.cache_data(show_spinner=False)
def load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_FILE)


def detect_wavelength_columns(df: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    detected: list[tuple[str, float]] = []
    for col in df.columns:
        wl = parse_wavelength(col)
        if wl is None:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().mean() >= 0.75:
            detected.append((str(col), wl))
    detected.sort(key=lambda item: item[1])
    cols = [item[0] for item in detected]
    wavelengths = np.array([item[1] for item in detected], dtype=float)
    return cols, wavelengths


def default_column(options: list[str], candidates: list[str]) -> str:
    lower = {c.lower(): c for c in options}
    for candidate in candidates:
        if candidate in lower:
            return lower[candidate]
    for option in options:
        option_l = option.lower()
        if any(candidate in option_l for candidate in candidates):
            return option
    return options[0] if options else ""


def numeric_matrix(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
    x = df.loc[:, cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    for j in range(x.shape[1]):
        col = x[:, j]
        if np.all(np.isnan(col)):
            x[:, j] = 0.0
        else:
            x[np.isnan(col), j] = np.nanmean(col)
    return x


def snv(x: np.ndarray) -> np.ndarray:
    means = np.nanmean(x, axis=1, keepdims=True)
    stds = np.nanstd(x, axis=1, keepdims=True)
    stds[stds == 0] = 1.0
    return (x - means) / stds


def msc(x: np.ndarray) -> np.ndarray:
    ref = np.nanmean(x, axis=0)
    corrected = np.empty_like(x)
    a = np.vstack([ref, np.ones_like(ref)]).T
    for i, row in enumerate(x):
        try:
            slope, intercept = np.linalg.lstsq(a, row, rcond=None)[0]
            if abs(slope) < 1e-12:
                slope = 1.0
            corrected[i, :] = (row - intercept) / slope
        except np.linalg.LinAlgError:
            corrected[i, :] = row
    return corrected


def valid_window(window: int, n_features: int) -> int:
    if n_features < 3:
        return 0
    window = max(3, int(window))
    if window % 2 == 0:
        window += 1
    if window > n_features:
        window = n_features if n_features % 2 == 1 else n_features - 1
    return max(window, 3)


def preprocess_matrix(
    x: np.ndarray,
    wavelengths: np.ndarray,
    scatter: str,
    use_savgol: bool,
    sg_window: int,
    sg_polyorder: int,
    derivative_order: int,
) -> tuple[np.ndarray, np.ndarray]:
    out = np.array(x, dtype=float, copy=True)
    wl = np.array(wavelengths, dtype=float, copy=True)
    window = valid_window(sg_window, out.shape[1])
    if use_savgol or derivative_order > 0:
        if window >= 3:
            poly = min(max(1, int(sg_polyorder)), window - 1)
            deriv = min(max(0, int(derivative_order)), 2)
            delta = float(np.nanmedian(np.diff(wl))) if len(wl) > 1 else 1.0
            if not np.isfinite(delta) or delta == 0:
                delta = 1.0
            out = savgol_filter(out, window_length=window, polyorder=poly, deriv=deriv, delta=delta, axis=1, mode="interp")
    if scatter == "SNV":
        out = snv(out)
    elif scatter == "MSC":
        out = msc(out)
    return out, wl


def run_python_analysis(
    df: pd.DataFrame,
    sample_col: str,
    group_col: str,
    target_col: str,
    wl_cols: list[str],
    wavelengths: np.ndarray,
    scatter: str,
    use_savgol: bool,
    sg_window: int,
    sg_polyorder: int,
    derivative_order: int,
    aquagram_wavelengths: list[float],
    reference_mode: str,
    control_group: str,
) -> dict[str, Any]:
    x_raw = numeric_matrix(df, wl_cols)
    x_proc, wl_proc = preprocess_matrix(
        x_raw,
        wavelengths,
        scatter=scatter,
        use_savgol=use_savgol,
        sg_window=sg_window,
        sg_polyorder=sg_polyorder,
        derivative_order=derivative_order,
    )
    sample_ids = df[sample_col].astype(str).to_numpy() if sample_col else np.array([f"S{i + 1}" for i in range(len(df))])
    groups = df[group_col].astype(str).fillna("Unlabeled").to_numpy() if group_col else np.array(["All samples"] * len(df))

    ncomp = min(5, x_proc.shape[0] - 1, x_proc.shape[1])
    if ncomp >= 2:
        pca = PCA(n_components=ncomp)
        scores_np = pca.fit_transform(x_proc)
        loadings_np = pca.components_.T
        variance = pca.explained_variance_ratio_
    else:
        scores_np = np.zeros((x_proc.shape[0], 2))
        loadings_np = np.zeros((x_proc.shape[1], 2))
        variance = np.array([np.nan, np.nan])
        ncomp = 2

    score_cols = [f"PC{i + 1}" for i in range(ncomp)]
    scores = pd.DataFrame(scores_np[:, :ncomp], columns=score_cols)
    scores.insert(0, "group", groups)
    scores.insert(0, "sample_id", sample_ids)
    loadings = pd.DataFrame(loadings_np[:, :ncomp], columns=score_cols)
    loadings.insert(0, "wavelength", wl_proc)
    variance_df = pd.DataFrame({"component": score_cols, "explained_variance": variance[:ncomp]})

    processed = pd.DataFrame(x_proc, columns=[f"wl_{wl:g}" for wl in wl_proc])
    processed.insert(0, "group", groups)
    processed.insert(0, "sample_id", sample_ids)

    aquagram = compute_aquagram(x_proc, wl_proc, groups, aquagram_wavelengths, reference_mode, control_group)
    pls_outputs = run_pls(df, x_proc, target_col, sample_ids, groups) if target_col else {}

    return {
        "engine": "Python",
        "x_raw": x_raw,
        "x_processed": x_proc,
        "wavelengths": wl_proc,
        "sample_ids": sample_ids,
        "groups": groups,
        "scores": scores,
        "loadings": loadings,
        "variance": variance_df,
        "processed": processed,
        "aquagram": aquagram,
        "pls": pls_outputs,
        "aquap2_available": None,
        "aquap2_version": None,
    }


def run_pls(df: pd.DataFrame, x: np.ndarray, target_col: str, sample_ids: np.ndarray, groups: np.ndarray) -> dict[str, pd.DataFrame]:
    y_raw = df[target_col]
    y_numeric = pd.to_numeric(y_raw, errors="coerce")
    encoder_note = "numeric"
    if y_numeric.notna().mean() < 0.8:
        le = LabelEncoder()
        y = le.fit_transform(y_raw.astype(str))
        encoder_note = "label-encoded: " + ", ".join(f"{cls}={i}" for i, cls in enumerate(le.classes_))
    else:
        y = y_numeric.fillna(y_numeric.mean()).to_numpy(dtype=float)
    n_components = max(1, min(5, x.shape[1], x.shape[0] - 1))
    model = PLSRegression(n_components=n_components)
    try:
        model.fit(x, y)
        pred = model.predict(x).ravel()
        pred_df = pd.DataFrame({
            "sample_id": sample_ids,
            "group": groups,
            "target": y,
            "prediction": pred,
            "residual": y - pred,
        })
        coef_df = pd.DataFrame({
            "feature_index": np.arange(model.coef_.shape[0]) + 1,
            "coefficient": model.coef_.ravel(),
        })
        note_df = pd.DataFrame({"setting": ["target_encoding"], "value": [encoder_note]})
        return {"pls_predictions": pred_df, "pls_coefficients": coef_df, "pls_notes": note_df}
    except Exception as exc:  # pragma: no cover - defensive for user data
        return {"pls_error": pd.DataFrame({"message": [str(exc)]})}


def compute_aquagram(
    x: np.ndarray,
    wavelengths: np.ndarray,
    groups: np.ndarray,
    target_wavelengths: list[float],
    reference_mode: str,
    control_group: str,
) -> pd.DataFrame:
    if len(target_wavelengths) < 3:
        quantiles = np.linspace(0.05, 0.95, min(12, len(wavelengths)))
        target_wavelengths = [float(np.quantile(wavelengths, q)) for q in quantiles]
    positions: list[int] = []
    for target in target_wavelengths:
        if np.isfinite(target):
            positions.append(int(np.argmin(np.abs(wavelengths - target))))
    positions = sorted(set(positions), key=lambda idx: wavelengths[idx])
    if len(positions) < 3:
        positions = list(range(min(len(wavelengths), 3)))
    aq_x = x[:, positions]
    aq_wl = wavelengths[positions]
    if reference_mode == "Control group" and control_group and np.any(groups == control_group):
        ref = np.nanmean(aq_x[groups == control_group], axis=0)
    elif reference_mode == "None":
        ref = np.zeros(aq_x.shape[1])
    else:
        ref = np.nanmean(aq_x, axis=0)
    scale = np.nanstd(aq_x, axis=0)
    scale[~np.isfinite(scale) | (scale == 0)] = 1.0
    rows: list[dict[str, Any]] = []
    for group in pd.unique(groups):
        mean_vec = np.nanmean(aq_x[groups == group], axis=0)
        if reference_mode == "None":
            values = mean_vec
        else:
            values = (mean_vec - ref) / scale
        for wl, value in zip(aq_wl, values):
            rows.append({"group": group, "wavelength": float(wl), "value": float(value)})
    return pd.DataFrame(rows)


def style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor(WHITE)
    ax.grid(True, color=GRAY_100, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRAY_300)
    ax.spines["bottom"].set_color(GRAY_300)
    ax.tick_params(colors=GRAY_700)


def group_color_map(groups: np.ndarray | pd.Series | list[str]) -> dict[str, str]:
    unique = list(pd.unique(pd.Series(groups).astype(str)))
    return {group: PALETTE[i % len(PALETTE)] for i, group in enumerate(unique)}


def spectra_figure(wavelengths: np.ndarray, x: np.ndarray, groups: np.ndarray, max_lines: int = 90) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9.5, 4.8), dpi=140)
    colors = group_color_map(groups)
    step = max(1, int(np.ceil(x.shape[0] / max_lines)))
    for i in range(0, x.shape[0], step):
        ax.plot(wavelengths, x[i], color=colors[str(groups[i])], linewidth=0.85, alpha=0.32)
    handles = []
    for group, color in colors.items():
        handle, = ax.plot([], [], color=color, linewidth=2, label=str(group))
        handles.append(handle)
    ax.set_title("Spectra", color=NAVY, pad=12)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Signal")
    style_axis(ax)
    if handles:
        ax.legend(handles=handles, frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    return fig


def pca_figure(scores: pd.DataFrame, variance: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(7.2, 5.1), dpi=140)
    colors = group_color_map(scores["group"])
    for group, sub in scores.groupby("group", sort=False):
        ax.scatter(sub["PC1"], sub["PC2"], color=colors[str(group)], s=42, alpha=0.82, label=str(group), edgecolor=WHITE, linewidth=0.7)
    pc1 = variance.loc[variance["component"] == "PC1", "explained_variance"]
    pc2 = variance.loc[variance["component"] == "PC2", "explained_variance"]
    pc1_label = f"PC1 ({pc1.iloc[0] * 100:.1f}%)" if len(pc1) and np.isfinite(pc1.iloc[0]) else "PC1"
    pc2_label = f"PC2 ({pc2.iloc[0] * 100:.1f}%)" if len(pc2) and np.isfinite(pc2.iloc[0]) else "PC2"
    ax.axhline(0, color=GRAY_300, linewidth=0.8)
    ax.axvline(0, color=GRAY_300, linewidth=0.8)
    ax.set_title("PCA score plot", color=NAVY, pad=12)
    ax.set_xlabel(pc1_label)
    ax.set_ylabel(pc2_label)
    style_axis(ax)
    ax.legend(frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    return fig


def loading_figure(loadings: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9.5, 4.2), dpi=140)
    for idx, comp in enumerate([col for col in loadings.columns if col.startswith("PC")][:3]):
        ax.plot(loadings["wavelength"], loadings[comp], color=PALETTE[idx % len(PALETTE)], linewidth=1.4, label=comp)
    ax.axhline(0, color=GRAY_300, linewidth=0.8)
    ax.set_title("PCA loadings", color=NAVY, pad=12)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Loading")
    style_axis(ax)
    ax.legend(frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    return fig


def aquagram_figure(aquagram: pd.DataFrame) -> plt.Figure:
    fig = plt.figure(figsize=(7.2, 6.2), dpi=140)
    ax = fig.add_subplot(111, projection="polar")
    groups = list(pd.unique(aquagram["group"].astype(str)))
    wavelengths = sorted(aquagram["wavelength"].unique())
    theta = np.linspace(0, 2 * np.pi, len(wavelengths), endpoint=False)
    theta_closed = np.append(theta, theta[0])
    colors = group_color_map(groups)
    for group in groups:
        sub = aquagram[aquagram["group"].astype(str) == group].set_index("wavelength").reindex(wavelengths)
        values = sub["value"].to_numpy(dtype=float)
        values_closed = np.append(values, values[0])
        ax.plot(theta_closed, values_closed, color=colors[group], linewidth=1.6, label=group)
        ax.fill(theta_closed, values_closed, color=colors[group], alpha=0.06)
    ax.set_xticks(theta)
    ax.set_xticklabels([f"{wl:g}" for wl in wavelengths], fontsize=8, color=GRAY_700)
    ax.set_title("Aquagram", color=NAVY, pad=18)
    ax.grid(True, color=GRAY_100, linewidth=0.8)
    ax.spines["polar"].set_color(GRAY_300)
    ax.tick_params(colors=GRAY_700)
    ax.legend(loc="upper right", bbox_to_anchor=(1.24, 1.12), frameon=False, fontsize=8)
    fig.patch.set_facecolor(WHITE)
    fig.tight_layout()
    return fig


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def figure_bytes(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", facecolor=WHITE)
    buffer.seek(0)
    return buffer.getvalue()


def make_result_zip(result: dict[str, Any], figures: dict[str, plt.Figure]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ["processed", "scores", "loadings", "variance", "aquagram"]:
            if name in result and isinstance(result[name], pd.DataFrame):
                zf.writestr(f"tables/{name}.csv", csv_bytes(result[name]))
        for name, df in result.get("pls", {}).items():
            if isinstance(df, pd.DataFrame):
                zf.writestr(f"tables/{name}.csv", csv_bytes(df))
        for name, fig in figures.items():
            zf.writestr(f"figures/{name}.png", figure_bytes(fig))
        metadata = {
            "engine": result.get("engine"),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "aquap2_available": result.get("aquap2_available"),
            "aquap2_version": result.get("aquap2_version"),
        }
        zf.writestr("run_metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    buffer.seek(0)
    return buffer.getvalue()


def rscript_path() -> str | None:
    return shutil.which("Rscript")


def run_subprocess(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "AQUA_R_LIBS": str(APP_DIR / "r_libs")},
    )


def run_r_healthcheck() -> dict[str, Any]:
    path = rscript_path()
    if not path:
        return {"error": "Rscript was not found."}
    result = run_subprocess([path, str(APP_DIR / "r_backend" / "healthcheck.R")], timeout=45)
    if result.returncode != 0:
        return {"error": result.stderr or result.stdout}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": result.stdout or "No JSON output from R healthcheck."}


def write_r_config(path: Path, config: dict[str, str | int | float | list[Any]]) -> None:
    lines = []
    for key, value in config.items():
        if isinstance(value, list):
            encoded = "|".join(quote(str(v), safe="") for v in value)
        else:
            encoded = quote(str(value), safe="")
        lines.append(f"{key}={encoded}")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_r_analysis(
    df: pd.DataFrame,
    sample_col: str,
    group_col: str,
    wl_cols: list[str],
    wavelengths: np.ndarray,
    scatter: str,
    sg_window: int,
    derivative_order: int,
    aquagram_wavelengths: list[float],
    reference_mode: str,
    control_group: str,
) -> dict[str, Any]:
    path = rscript_path()
    if not path:
        raise RuntimeError("Rscript が見つかりません。Streamlit Cloudでは packages.txt の r-base を確認してください。")
    job_dir = RUNTIME_DIR / f"job_{int(time.time() * 1000)}"
    job_dir.mkdir(parents=True, exist_ok=True)
    input_csv = job_dir / "input.csv"
    config_txt = job_dir / "config.txt"
    output_dir = job_dir / "output"
    df.to_csv(input_csv, index=False)
    write_r_config(
        config_txt,
        {
            "sample_col": sample_col,
            "group_col": group_col,
            "wavelength_cols": wl_cols,
            "wavelength_values": [f"{v:g}" for v in wavelengths],
            "scatter": scatter,
            "sg_window": sg_window,
            "derivative": derivative_order,
            "aquagram_values": [f"{v:g}" for v in aquagram_wavelengths],
            "reference_mode": reference_mode,
            "control_group": control_group,
        },
    )
    result = run_subprocess([path, str(APP_DIR / "r_backend" / "run_analysis.R"), str(input_csv), str(config_txt), str(output_dir)], timeout=240)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    result_line = ""
    for line in result.stdout.splitlines():
        if line.startswith("RESULT|"):
            result_line = line
    if not result_line:
        raise RuntimeError("R backend returned no result line.\n" + result.stdout)
    parts = result_line.split("|")
    if len(parts) < 8:
        raise RuntimeError("Unexpected R backend output: " + result_line)
    _, processed_csv, scores_csv, loadings_csv, variance_csv, aquagram_csv, aq_available, aq_version = parts[:8]
    processed = pd.read_csv(processed_csv)
    scores = pd.read_csv(scores_csv)
    loadings = pd.read_csv(loadings_csv)
    variance = pd.read_csv(variance_csv)
    aquagram = pd.read_csv(aquagram_csv)
    wl_proc = loadings["wavelength"].to_numpy(dtype=float)
    x_proc = processed.iloc[:, 2:].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    groups = processed["group"].astype(str).to_numpy()
    sample_ids = processed["sample_id"].astype(str).to_numpy()
    return {
        "engine": "R backend",
        "x_raw": numeric_matrix(df, wl_cols),
        "x_processed": x_proc,
        "wavelengths": wl_proc,
        "sample_ids": sample_ids,
        "groups": groups,
        "scores": scores,
        "loadings": loadings,
        "variance": variance,
        "processed": processed,
        "aquagram": aquagram,
        "pls": {},
        "aquap2_available": aq_available == "TRUE",
        "aquap2_version": aq_version,
        "r_stdout": result.stdout,
        "r_stderr": result.stderr,
    }


def render_metric_card(label: str, value: str) -> None:
    st.markdown(f'<div class="card"><div class="mini-label">{label}</div><div class="mini-value">{value}</div></div>', unsafe_allow_html=True)


def parse_aquagram_input(text: str) -> list[float]:
    values: list[float] = []
    for token in re.split(r"[,\s]+", text.strip()):
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def render_intro() -> None:
    st.markdown(
        """
        <div class="hero">
          <div class="hero-title">Aquaphotomics Workbench</div>
          <div class="hero-subtitle">
            Spectral data import, preprocessing, PCA, PLS preview and aquagram visualization in a Streamlit Cloud-ready workspace.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def data_summary(df: pd.DataFrame, wl_cols: list[str], wavelengths: np.ndarray, group_col: str) -> None:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Samples", f"{len(df):,}")
    with c2:
        render_metric_card("Columns", f"{df.shape[1]:,}")
    with c3:
        render_metric_card("Wavelengths", f"{len(wl_cols):,}")
    with c4:
        if len(wavelengths):
            render_metric_card("Range", f"{wavelengths.min():g}–{wavelengths.max():g} nm")
        else:
            render_metric_card("Range", "—")
    if group_col:
        counts = df[group_col].astype(str).value_counts().reset_index()
        counts.columns = ["group", "n"]
        st.dataframe(counts, use_container_width=True, hide_index=True)


def select_wavelength_range(wavelengths: np.ndarray) -> tuple[float, float]:
    min_wl = float(np.nanmin(wavelengths))
    max_wl = float(np.nanmax(wavelengths))
    if min_wl == max_wl:
        return min_wl, max_wl
    return st.slider(
        "波長範囲",
        min_value=min_wl,
        max_value=max_wl,
        value=(min_wl, max_wl),
        step=max((max_wl - min_wl) / 300, 0.1),
    )


def main() -> None:
    apply_css()
    render_intro()

    with st.sidebar:
        st.header("Workflow")
        engine = st.radio("解析エンジン", ["Python preview", "R backend"], help="R backendはStreamlit Cloud側のRscriptを呼び出します。", horizontal=False)
        st.divider()
        uploaded = st.file_uploader("スペクトルデータ", type=["csv", "xlsx", "xls"], help="波長列は wl_1450, 1450, nm_1450 のような列名に対応します。")
        use_sample = st.checkbox("サンプルデータを使う", value=uploaded is None)
        st.download_button(
            "サンプルCSVをダウンロード",
            data=SAMPLE_FILE.read_bytes(),
            file_name="sample_spectra.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if uploaded is not None:
        try:
            df = load_table_from_bytes(uploaded.getvalue(), uploaded.name)
        except Exception as exc:
            st.error(f"ファイルを読み込めませんでした: {exc}")
            return
    elif use_sample:
        df = load_sample()
    else:
        st.info("CSVまたはExcelファイルをアップロードしてください。")
        return

    df.columns = [str(c) for c in df.columns]
    all_columns = list(df.columns)
    detected_cols, detected_wavelengths = detect_wavelength_columns(df)

    if len(detected_cols) < 3:
        st.error("波長列を3列以上検出できませんでした。列名を wl_1450 / 1450 / nm_1450 のようにしてください。")
        st.dataframe(df.head(20), use_container_width=True)
        return

    with st.sidebar:
        st.divider()
        st.subheader("列の設定")
        none_option = "—"
        sample_default = default_column(all_columns, ["sample_id", "sample", "id", "name"])
        group_default = default_column(all_columns, ["group", "class", "condition", "treatment", "label"])
        sample_col = st.selectbox("サンプルID", [none_option] + all_columns, index=([none_option] + all_columns).index(sample_default) if sample_default in all_columns else 0)
        group_col = st.selectbox("群・クラス", [none_option] + all_columns, index=([none_option] + all_columns).index(group_default) if group_default in all_columns else 0)
        numeric_candidates = [c for c in all_columns if c not in detected_cols and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.8]
        target_col = st.selectbox("PLS用の目的変数", [none_option] + numeric_candidates + [c for c in all_columns if c not in numeric_candidates and c not in detected_cols], index=0)
        sample_col = "" if sample_col == none_option else sample_col
        group_col = "" if group_col == none_option else group_col
        target_col = "" if target_col == none_option else target_col

        st.subheader("波長")
        min_range, max_range = select_wavelength_range(detected_wavelengths)
        range_mask = (detected_wavelengths >= min_range) & (detected_wavelengths <= max_range)
        wl_cols = [col for col, keep in zip(detected_cols, range_mask) if keep]
        wavelengths = detected_wavelengths[range_mask]
        st.caption(f"選択中: {len(wl_cols)} 列")

        st.subheader("前処理")
        scatter = st.selectbox("散乱補正", ["None", "SNV", "MSC"], index=1)
        use_savgol = st.checkbox("Savitzky-Golay 平滑化", value=True)
        sg_window = st.slider("SG window", min_value=3, max_value=max(3, min(51, len(wl_cols) if len(wl_cols) % 2 == 1 else len(wl_cols) - 1)), value=min(11, max(3, len(wl_cols) if len(wl_cols) % 2 == 1 else len(wl_cols) - 1)), step=2)
        sg_polyorder = st.slider("SG polyorder", min_value=1, max_value=5, value=2)
        derivative_order = st.selectbox("微分", [0, 1, 2], format_func=lambda x: "なし" if x == 0 else f"{x}次微分")

        st.subheader("Aquagram")
        default_aq = "1340, 1360, 1380, 1410, 1440, 1450, 1460, 1475, 1490, 1510, 1525, 1550"
        aq_text = st.text_area("使用波長", value=default_aq, height=80)
        reference_mode = st.selectbox("基準", ["Global mean", "Control group", "None"])
        groups_for_control = sorted(df[group_col].astype(str).dropna().unique().tolist()) if group_col else []
        control_group = st.selectbox("Control group", [""] + groups_for_control, index=0, disabled=reference_mode != "Control group")

        run_button = st.button("解析を実行", use_container_width=True)

    tab_analysis, tab_data, tab_r, tab_help = st.tabs(["解析", "データ", "R環境", "使い方"])

    with tab_data:
        st.subheader("データ概要")
        data_summary(df, wl_cols, wavelengths, group_col)
        st.markdown("<div class='section-note'>先頭20行</div>", unsafe_allow_html=True)
        st.dataframe(df.head(20), use_container_width=True)
        with st.expander("検出された波長列"):
            wave_df = pd.DataFrame({"column": detected_cols, "wavelength": detected_wavelengths})
            st.dataframe(wave_df, use_container_width=True, hide_index=True)

    with tab_r:
        st.subheader("R / aquap2 接続")
        st.markdown("Streamlit Cloud上では `packages.txt` でRを入れ、アプリから `Rscript` を呼び出します。")
        path = rscript_path()
        st.markdown(
            f"<span class='status-pill'>Rscript: <strong>{path or 'not found'}</strong></span>",
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("R環境チェック", use_container_width=True):
                with st.spinner("Rscriptを確認しています..."):
                    status = run_r_healthcheck()
                if "error" in status:
                    st.error(status["error"])
                else:
                    st.json(status)
        with c2:
            if st.button("aquap2をセットアップ", use_container_width=True):
                path = rscript_path()
                if not path:
                    st.error("Rscript が見つかりません。")
                else:
                    with st.spinner("Rパッケージをセットアップしています。初回は数分かかることがあります..."):
                        result = run_subprocess([path, str(APP_DIR / "r_backend" / "setup.R")], timeout=900)
                    if result.returncode == 0:
                        st.success("aquap2 setup finished")
                    else:
                        st.error("setup failed")
                    st.code((result.stdout or "") + "\n" + (result.stderr or ""), language="text")
        st.markdown(
            """
            <div class="card">
            <b>メモ</b><br>
            R backendは、汎用CSVを受け取ってR側で前処理・PCA・aquagramテーブル作成まで実行します。
            aquap2が入っている場合はR側で検出されます。研究室データのaquap2専用フォーマットに合わせる場合は、
            <code>r_backend/run_analysis.R</code> の入力変換部分を差し替えて使います。
            </div>
            """,
            unsafe_allow_html=True,
        )

    with tab_help:
        st.subheader("入力データ")
        st.markdown(
            """
            - 1行が1サンプルです。
            - サンプルID列、群・クラス列、任意のメタデータ列を含められます。
            - 波長列の名前は `wl_1450`, `1450`, `nm_1450` のように数値波長を含めてください。
            - CSV、XLSX、XLSに対応しています。R backendを使う場合も、内部でCSVに変換して渡します。
            """
        )
        st.subheader("Streamlit Cloudへの置き方")
        st.code(
            """repository/
  app.py
  requirements.txt
  packages.txt
  r_backend/
  sample_data/
  .streamlit/config.toml""",
            language="text",
        )
        st.markdown("GitHubに置いたあと、Streamlit Community Cloudで `app.py` をエントリーポイントにしてください。")

    with tab_analysis:
        st.subheader("解析")
        if len(wl_cols) < 3:
            st.warning("波長列を3列以上選択してください。")
            return
        if not run_button and "last_result" not in st.session_state:
            st.markdown(
                """
                <div class="card">
                左サイドバーで条件を確認し、<b>解析を実行</b> を押してください。
                サンプルデータを使うと、すぐに画面と出力形式を確認できます。
                </div>
                """,
                unsafe_allow_html=True,
            )
            return
        if run_button:
            aq_wavelengths = parse_aquagram_input(aq_text)
            try:
                with st.spinner("解析中..."):
                    if engine == "R backend":
                        result = run_r_analysis(
                            df=df,
                            sample_col=sample_col,
                            group_col=group_col,
                            wl_cols=wl_cols,
                            wavelengths=wavelengths,
                            scatter=scatter,
                            sg_window=sg_window if use_savgol else 0,
                            derivative_order=derivative_order,
                            aquagram_wavelengths=aq_wavelengths,
                            reference_mode=reference_mode,
                            control_group=control_group,
                        )
                    else:
                        result = run_python_analysis(
                            df=df,
                            sample_col=sample_col,
                            group_col=group_col,
                            target_col=target_col,
                            wl_cols=wl_cols,
                            wavelengths=wavelengths,
                            scatter=scatter,
                            use_savgol=use_savgol,
                            sg_window=sg_window,
                            sg_polyorder=sg_polyorder,
                            derivative_order=derivative_order,
                            aquagram_wavelengths=aq_wavelengths,
                            reference_mode=reference_mode,
                            control_group=control_group,
                        )
                st.session_state["last_result"] = result
            except Exception as exc:
                st.error(str(exc))
                return

        result = st.session_state.get("last_result")
        if not result:
            return

        st.markdown(
            f"<span class='status-pill'>Engine: <strong>{result.get('engine')}</strong></span>"
            f"<span class='status-pill'>Samples: <strong>{len(result['sample_ids'])}</strong></span>"
            f"<span class='status-pill'>Wavelengths: <strong>{len(result['wavelengths'])}</strong></span>",
            unsafe_allow_html=True,
        )
        if result.get("engine") == "R backend":
            st.caption(f"aquap2 detected by R backend: {result.get('aquap2_available')} / {result.get('aquap2_version')}")

        figs = {
            "spectra_processed": spectra_figure(result["wavelengths"], result["x_processed"], result["groups"]),
            "pca_scores": pca_figure(result["scores"], result["variance"]),
            "pca_loadings": loading_figure(result["loadings"]),
            "aquagram": aquagram_figure(result["aquagram"]),
        }

        fig_tab1, fig_tab2, fig_tab3, table_tab, export_tab = st.tabs(["Spectra", "PCA", "Aquagram", "Tables", "Export"])
        with fig_tab1:
            st.pyplot(figs["spectra_processed"], clear_figure=False, use_container_width=True)
        with fig_tab2:
            c1, c2 = st.columns([1, 1])
            with c1:
                st.pyplot(figs["pca_scores"], clear_figure=False, use_container_width=True)
            with c2:
                st.pyplot(figs["pca_loadings"], clear_figure=False, use_container_width=True)
            st.dataframe(result["variance"], use_container_width=True, hide_index=True)
        with fig_tab3:
            st.pyplot(figs["aquagram"], clear_figure=False, use_container_width=True)
            st.dataframe(result["aquagram"], use_container_width=True, hide_index=True)
        with table_tab:
            st.markdown("#### PCA scores")
            st.dataframe(result["scores"], use_container_width=True, hide_index=True)
            st.markdown("#### Processed spectra")
            st.dataframe(result["processed"].head(80), use_container_width=True, hide_index=True)
            if result.get("pls"):
                st.markdown("#### PLS preview")
                for name, table in result["pls"].items():
                    if isinstance(table, pd.DataFrame):
                        st.caption(name)
                        st.dataframe(table, use_container_width=True, hide_index=True)
        with export_tab:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.download_button("processed.csv", csv_bytes(result["processed"]), file_name="processed_spectra.csv", mime="text/csv", use_container_width=True)
            with c2:
                st.download_button("pca_scores.csv", csv_bytes(result["scores"]), file_name="pca_scores.csv", mime="text/csv", use_container_width=True)
            with c3:
                st.download_button("aquagram.csv", csv_bytes(result["aquagram"]), file_name="aquagram.csv", mime="text/csv", use_container_width=True)
            st.download_button(
                "結果一式をZIPでダウンロード",
                make_result_zip(result, figs),
                file_name="aquaphotomics_results.zip",
                mime="application/zip",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()

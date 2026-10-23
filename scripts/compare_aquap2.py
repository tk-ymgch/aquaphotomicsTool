#!/usr/bin/env python3
"""Compare installed aquap2::gdmm with Workbench on artificial data only.

This calls the real R engine; it never falls back to aquap2_reference.R or
reimplements aquap2. The input to R is the exact Python-preprocessed matrix.
Only centered, unscaled PCA and classic/classic-diff Aquagrams are compared.

Example (PowerShell; choose a new output directory):
  $env:AQUAP2_LIBRARY = (Resolve-Path qa/aquap2-runtime-v1.4/library).Path
  python scripts/compare_aquap2.py --rscript 'C:/Program Files/R/R-4.6.1/bin/Rscript.exe' --output qa/aquap2-package-comparison

Requires the normal Python analysis dependencies and an installed aquap2 plus
dependencies. Installation is separate and is never performed by this script.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PINNED_COMMIT = "d31c1231bf71f0e73f1a630a32934602782be488"
COORDINATES = [1340.0, 1365.0, 1375.0, 1385.0, 1410.0, 1425.0,
               1440.0, 1450.0, 1460.0, 1475.0, 1490.0, 1510.0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_workbench():
    spec = importlib.util.spec_from_file_location("aquap2_comparison_workbench", ROOT / "python" / "workbench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artificial_fixture(wb):
    """Unequal group sizes make accidental sample-count correction detectable."""
    df, _ = wb.demo_dataset()
    names = list(dict.fromkeys(df["group"].astype(str)))
    parts = [df.loc[df["group"] == name].iloc[:count] for name, count in zip(names, [9, 12, 15])]
    import pandas as pd
    fixture = pd.concat(parts, ignore_index=True)
    fixture.attrs.update(df.attrs)
    fixture.attrs["artificial"] = True
    if not wb._is_artificial(fixture):
        raise RuntimeError("人工データの識別を確認できません。比較を中止しました。")
    return fixture


def config_for(df, condition: str, reference: str, mode: str) -> dict:
    return {
        "idColumn": "sample_id", "groupColumn": "group",
        "wavelengthColumns": [str(name) for name in df.columns if str(name).startswith("wl_")],
        "range": [1300.0, 1600.0], "pipelineMode": mode, "missing": "error",
        "scatter": {"none": "none", "snv-sg": "snv", "msc-sg": "msc"}[condition],
        "smooth": condition != "none", "window": 11, "polyorder": 2, "derivative": 0,
        "pcaScale": False, "components": 5, "aquagramWavelengths": COORDINATES,
        "aquagramReference": reference, "aquagramTolerance": 0.0,
    }


def input_from_result(result: dict, reference: str) -> dict:
    return {
        "schemaVersion": 1,
        "matrix": result["spectra"]["processed"],
        "wavelengths": result["spectra"]["wavelengths"],
        "ids": result["spectra"]["ids"], "groups": result["spectra"]["groups"],
        "aquagram": {"wavelengths": result["aquagram"]["wavelengths"], "reference": reference},
        "pca": {"components": len(result["pca"]["explainedVariance"]), "scale": False},
    }


def require_runtime(output: dict) -> dict:
    runtime = output.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("R出力にruntime証跡がありません。")
    required = {"engine": "aquap2", "packageApiExecuted": True, "api": "aquap2::gdmm"}
    for key, value in required.items():
        if type(runtime.get(key)) is not type(value) or runtime.get(key) != value:
            raise ValueError(f"R出力の実パッケージ/API実行証跡が不正です: {key}")
    for key in ["aquap2Version", "rVersion"]:
        if not isinstance(runtime.get(key), str) or not runtime[key].strip():
            raise ValueError(f"R出力に版情報がありません: {key}")
    if runtime["aquap2Version"] != "0.4.5" or runtime.get("sourceCommit") != PINNED_COMMIT:
        raise ValueError("比較対象の固定版aquap2 0.4.5/source commitと一致しません。")
    if runtime.get("installedPackage") is not True:
        raise ValueError("インストール済みaquap2の実行証跡installedPackage=trueが必要です。")
    if runtime.get("sourceHarness") or runtime.get("sourceHarnessExecuted"):
        raise ValueError("source harnessの出力は実パッケージ比較に使用できません。")
    return runtime


def numeric(value: Any, shape: tuple[int, ...], label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"R出力の{label}が数値配列ではありません。") from exc
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"R出力の{label}の形または有限値を確認できません。期待形: {shape}")
    return array


def difference(actual: np.ndarray, expected: np.ndarray, atol: float, rtol: float) -> dict:
    delta = np.abs(actual - expected)
    allowance = atol + rtol * np.abs(expected)
    return {
        "values": int(actual.size), "maxAbsDiff": float(delta.max(initial=0.0)),
        "maxToleranceRatio": float((delta / allowance).max(initial=0.0)),
        "atol": atol, "rtol": rtol, "passed": bool(np.all(delta <= allowance)),
    }


def compare_result(native: dict, actual: dict, payload: dict, atol: float, rtol: float) -> dict:
    runtime = require_runtime(actual)
    n, p = np.asarray(payload["matrix"]).shape
    k = payload["pca"]["components"]
    pca = actual.get("pca", {})
    if pca.get("ids") != payload["ids"] or pca.get("groups") != payload["groups"]:
        raise ValueError("R PCAの試料ID/群/行順が入力と一致しません。")
    native_loadings = np.asarray(native["pca"]["loadings"], dtype=float)
    loadings = numeric(pca.get("loadings"), (p, k), "PCA loadings")
    scores = numeric(pca.get("scores"), (n, k), "PCA scores")
    variance = numeric(pca.get("explainedVariance"), (k,), "PCA explainedVariance")
    if (variance < 0).any() or (variance > 1 + 1e-12).any():
        raise ValueError("R PCA寄与率は0..1の比率である必要があります。")
    # Each corresponding PCA component has an arbitrary global sign. This
    # fixture has separated singular values, so a subspace rotation is not used.
    dots = np.sum(native_loadings * loadings, axis=0)
    signs = np.where(dots >= 0.0, 1.0, -1.0)
    checks = {
        "pcaScoresSignAligned": difference(scores * signs, np.asarray(native["pca"]["scores"]), atol, rtol),
        "pcaLoadingsSignAligned": difference(loadings * signs, native_loadings, atol, rtol),
        "pcaExplainedVariance": difference(variance, np.asarray(native["pca"]["explainedVariance"]), atol, rtol),
    }
    aq = actual.get("aquagram", {})
    if aq.get("wavelengths") != payload["aquagram"]["wavelengths"]:
        raise ValueError("R Aquagramの実波長/列順が入力と一致しません。")
    group_rows = aq.get("groups")
    if not isinstance(group_rows, list) or not all(isinstance(row, dict) for row in group_rows):
        raise ValueError("R Aquagram群別出力がありません。")
    actual_names = [row.get("name") for row in group_rows]
    expected_names = [row["name"] for row in native["aquagram"]["groups"]]
    if Counter(actual_names) != Counter(expected_names):
        raise ValueError("R Aquagramの群名がWorkbenchと一致しません。")
    by_name = {row["name"]: row for row in group_rows}
    r_values, w_values = [], []
    for row in native["aquagram"]["groups"]:
        other = by_name[row["name"]]
        if type(other.get("n")) not in (int, float) or other["n"] != row["n"]:
            raise ValueError("R Aquagramの群別試料数が入力と一致しません。")
        r_values.append(numeric(other.get("values"), (len(COORDINATES),), "Aquagram values"))
        w_values.append(row["values"])
    r_values, w_values = np.asarray(r_values), np.asarray(w_values)
    factor = math.sqrt((n - 1) / n)
    checks["aquagramAfterExplicitSdConversion"] = difference(r_values, w_values * factor, atol, rtol)
    # This unadjusted difference is informational, not a failed-equivalence test.
    raw_aq_diff = float(np.abs(r_values - w_values).max(initial=0.0))
    singular = np.linalg.svd(np.asarray(payload["matrix"]) - np.mean(payload["matrix"], axis=0), compute_uv=False)
    leading_gaps = (singular[:k] - singular[1:k + 1]) / singular[:k]
    if float(leading_gaps.min()) < 1e-5:
        raise ValueError("人工fixtureのPCA固有値が近接し、成分ごとの符号整列比較に適しません。")
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks, "pcaComponentSignsAppliedToR": signs.astype(int).tolist(),
        "pcaMinRelativeSingularGap": float(leading_gaps.min()),
        "aquagram": {"rDdof": 1, "workbenchDdof": 0,
                      "workbenchToAquap2Factor": factor,
                      "unadjustedMaxAbsDiffInformational": raw_aq_diff,
                      "groupOrderChanged": actual_names != expected_names,
                      "rReference": aq.get("reference"), "rDefinition": aq.get("definition")},
        "runtime": runtime, "warnings": actual.get("warnings", []),
    }


def run_r(executable: str, engine: Path, input_path: Path, output_path: Path,
          library: Path | None, runtime_root: Path, timeout: float) -> dict:
    environment = os.environ.copy()
    if os.name == "nt":
        # Some Python launchers inherit this POSIX-only locale. Windows R
        # rejects it and then cannot resolve an installed library in a Japanese
        # path. Let R use its native UTF-8 locale; change only this child process.
        for key in list(environment):
            if (key == "LANG" or key.startswith("LC_")) and environment[key] in {"C.UTF-8", "C.utf8"}:
                del environment[key]
    environment["AQUAP2_RUNTIME_ROOT"] = str(runtime_root)
    # aquap2 creates settings files. Set the isolated home before R startup,
    # including package loading, rather than changing it after library().
    environment["R_USER"] = str(runtime_root / "home")
    if library is not None:
        environment["AQUAP2_LIBRARY"] = str(library)
        environment["R_LIBS_USER"] = str(library)
    start = time.monotonic()
    result = subprocess.run([executable, "--vanilla", str(engine), str(input_path), str(output_path)],
                            cwd=ROOT, env=environment, capture_output=True, timeout=timeout, check=False)
    process = {
        "exitCode": result.returncode, "elapsedSeconds": round(time.monotonic() - start, 3),
        "stdoutBytes": len(result.stdout), "stdoutSha256": sha256(result.stdout),
        "stderrBytes": len(result.stderr), "stderrSha256": sha256(result.stderr),
    }
    write_json(output_path.with_name("process.json"), process)
    if result.returncode != 0:
        # R output can contain input values. Hash it instead of putting it in
        # a shared report or console; inspect the helper directly when debugging.
        raise RuntimeError(f"R helper実行が失敗しました（exit={result.returncode}）。source harnessへの代替実行は行いません。")
    if not output_path.is_file():
        raise RuntimeError("R helperが出力JSONを作成しませんでした。")
    return process


def versions() -> dict:
    output = {"python": platform.python_version()}
    for package in ["numpy", "pandas", "scipy", "scikit-learn"]:
        output[package] = importlib.metadata.version(package)
    return output


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rscript", default="Rscript", help="Rscript executable; no shell command is evaluated")
    p.add_argument("--r-engine", type=Path, default=ROOT / "scripts" / "aquap2_engine.R")
    p.add_argument("--r-library", type=Path, help="Isolated installed package library (or set AQUAP2_LIBRARY)")
    p.add_argument("--r-runtime", type=Path,
                   default=Path(os.environ.get("AQUAP2_RUNTIME_ROOT", str(ROOT / "qa" / "aquap2-runtime-v1.4"))),
                   help="Runtime root containing installation.json and isolated home/settings")
    p.add_argument("--output", type=Path, default=ROOT / "qa" / ("aquap2-package-" + datetime.now().strftime("%Y%m%d-%H%M%S")),
                   help="New directory for artificial fixture, input/output JSON and comparison report")
    p.add_argument("--report", type=Path, help="Optional separate JSON report path")
    p.add_argument("--conditions", nargs="+", choices=["none", "snv-sg", "msc-sg"], default=["none", "snv-sg", "msc-sg"])
    p.add_argument("--pipeline-mode", choices=["modern", "legacy-python"], default="modern")
    p.add_argument("--atol", type=float, default=1e-7)
    p.add_argument("--rtol", type=float, default=1e-6)
    p.add_argument("--timeout", type=float, default=180.0, help="Per R invocation, seconds")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not all(math.isfinite(v) and v > 0 for v in [args.atol, args.rtol, args.timeout]):
        raise SystemExit("許容誤差/timeoutは有限の正数にしてください。")
    executable = shutil.which(args.rscript)
    if executable is None and Path(args.rscript).is_file():
        executable = str(Path(args.rscript).resolve())
    if executable is None:
        raise SystemExit("Rscriptが見つかりません。--rscriptで実行ファイルを指定してください。")
    engine = args.r_engine.resolve()
    if not engine.is_file() or engine.name == "aquap2_reference.R":
        raise SystemExit("実aquap2エンジンが必要です。source harnessは比較に使用できません。")
    library = args.r_library.resolve() if args.r_library else None
    if library is not None and not library.is_dir():
        raise SystemExit("指定したインストール済みR libraryが存在しません。")
    runtime_root = args.r_runtime.resolve()
    if not (runtime_root / "home").is_dir():
        raise SystemExit("R隔離homeがありません。先にsetup_aquap2.Rでruntimeを導入してください。")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report_path = args.report.resolve() if args.report else output / "report.json"
    report: dict = {
        "schemaVersion": 1, "comparison": "installed-aquap2-public-api-vs-workbench",
        "createdAt": datetime.now(timezone.utc).isoformat(), "artificial": True,
        "passed": False, "pythonVersions": versions(),
        "workbenchSha256": sha256((ROOT / "python" / "workbench.py").read_bytes()),
        "rEngineSha256": sha256(engine.read_bytes()),
        "referenceSourceCommit": PINNED_COMMIT, "sourceHarnessUsed": False,
        "pipelineMode": args.pipeline_mode, "runs": [],
        "scope": ["同じ有限値のPython前処理済み行列を実aquap2::gdmmへ入力",
                  "平均中心化・分散スケーリングなしのPCAを対応成分の符号整列後に比較",
                  "classic/globalとclassic-diff/指定群をsample SDへの明示変換後に比較",
                  "群別試料数が異なる決定的人工fixture、正確に存在する12座標"],
        "excluded": ["実測利用者データ", "実温度校正/AUC/sfc/既定aucs.dceモード", "PLS/PLS-DA",
                     "aquap2自身の前処理とPython前処理の一般的互換性", "bootstrap/試料数補正/外れ値除外",
                     "描画の視覚比較", "ブラウザー/公開サーバーの実行検証"],
    }
    try:
        wb = load_workbench()
        df = artificial_fixture(wb)
        source = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
        (output / "artificial-input.csv").write_bytes(source)
        report["fixture"] = {"generator": "workbench.demo_dataset seed=20261021; first 9/12/15 rows per group",
                             "samples": len(df), "variables": 61, "groupSizes": [9, 12, 15],
                             "inputCsvSha256": sha256(source)}
        controls = list(dict.fromkeys(df["group"].astype(str)))
        references = [("global", "global"), ("control", "group:" + controls[1])]
        for condition in dict.fromkeys(args.conditions):
            for label, reference in references:
                run_dir = output / (condition + "-" + label)
                run_dir.mkdir()
                cfg = config_for(df, condition, reference, args.pipeline_mode)
                native = wb.analyze(df, cfg)
                payload = input_from_result(native, reference)
                matrix = np.asarray(payload["matrix"], dtype=float)
                if not np.isfinite(matrix).all() or (np.std(matrix, axis=0) == 0).any():
                    raise ValueError("比較fixtureは有限値・非定数列である必要があります。")
                input_path, output_path = run_dir / "input.json", run_dir / "output.json"
                write_json(input_path, payload)
                (run_dir / "workbench-settings.json").write_text(native["exports"]["settings.json"], encoding="utf-8")
                process = run_r(executable, engine, input_path, output_path, library, runtime_root, args.timeout)
                actual = json.loads(output_path.read_text(encoding="utf-8-sig"))
                comparison = compare_result(native, actual, payload, args.atol, args.rtol)
                comparison.update(condition=condition, reference=reference, process=process,
                                  inputSha256=sha256(input_path.read_bytes()),
                                  outputSha256=sha256(output_path.read_bytes()))
                report["runs"].append(comparison)
                print(f"{condition}/{label}: {'PASS' if comparison['passed'] else 'FAIL'}; "
                      f"maxAbsDiff={max(c['maxAbsDiff'] for c in comparison['checks'].values()):.3g}", flush=True)
        report["passed"] = bool(report["runs"]) and all(run["passed"] for run in report["runs"])
        report["checkCount"] = sum(len(run["checks"]) for run in report["runs"])
        report["maxAbsDiffAfterDeclaredConversions"] = max(
            check["maxAbsDiff"] for run in report["runs"] for check in run["checks"].values())
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
    write_json(report_path, report)
    if report_path != output / "report.json":
        write_json(output / "report.json", report)
    print(f"runs={len(report['runs'])}; passed={report['passed']}; report={report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

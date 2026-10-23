#!/usr/bin/env python3
"""Direct aquap2py vs installed aquap2 oracle, starting from identical raw X.

The public R gdmm applies native dpt.pre; no Python-preprocessed matrix is sent.
No source harness, fallback engine, network installation or real research data
is used. R is required only for this opt-in verification script, not aquap2py.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import aquap2py as ap
from compare_aquap2 import difference, sha256, versions, write_json


def fixture():
    rng = np.random.default_rng(20261023)
    w = np.arange(61) * 5.0 + 1300.25
    t = np.linspace(-1.5, 1.5, len(w))
    groups = ["global"] * 6 + ['対照, "群"'] * 8 + ["人工\nC"] * 10
    rows = []
    for i, group in enumerate(groups):
        gi = 0 if i < 6 else 1 if i < 14 else 2
        signal = (.3 + .2 * np.exp(-t * t / .6) + .02 * gi * np.exp(-(t - .7) ** 2 / .2))
        signal = signal * (0.9 + .006 * i) + .001 * i + .003 * np.sin(t * (i + 2))
        rows.append(signal + rng.normal(0, .0015, len(t)))
    ids = [f"{i + 1:04d}" for i in range(len(rows))]
    ids[2] = '引用, "ID"\n日本語'
    return np.array(rows), w, ids, groups


def cases():
    sg = lambda n=11, m=0: {"method": "sgolay", "window": n, "polyorder": 2, "derivative": m}
    return [
        ("raw-global", [], "global", False),
        ("raw-control-reserved-name", [], "group:global", False),
        ("snv-global", [{"method": "snv"}], "global", False),
        ("msc-control", [{"method": "msc"}], 'group:対照, "群"', False),
        ("sg21-default-m0", [sg(21)], "global", False),
        ("sg11-m1", [sg(11, 1)], "global", False),
        ("sg11-m2-control", [sg(11, 2)], 'group:対照, "群"', False),
        ("snv-then-sg", [{"method": "snv"}, sg()], "global", False),
        ("sg-then-snv", [sg(), {"method": "snv"}], 'group:対照, "群"', False),
        ("msc-then-sg", [{"method": "msc"}, sg()], "global", False),
        ("sg-then-msc", [sg(), {"method": "msc"}], 'group:対照, "群"', False),
        ("irregular-sg-then-snv", [sg(), {"method": "snv"}], "group:global", True),
    ]


def call_r(args, source: Path, destination: Path) -> dict:
    env = os.environ.copy()
    if os.name == "nt":
        for key in list(env):
            if (key == "LANG" or key.startswith("LC_")) and env[key] in {"C.UTF-8", "C.utf8"}:
                del env[key]
    env["AQUAP2_RUNTIME_ROOT"] = str(args.r_runtime)
    env["AQUAP2_LIBRARY"] = str(args.r_library or args.r_runtime / "library")
    env["R_USER"] = str(args.r_runtime / "home")
    start = time.monotonic()
    result = subprocess.run([args.rscript, "--vanilla", str(args.r_engine), str(source), str(destination)],
                            cwd=ROOT, env=env, capture_output=True, timeout=args.timeout, check=False)
    record = {"exitCode": result.returncode, "elapsedSeconds": round(time.monotonic() - start, 3),
              "stdoutBytes": len(result.stdout), "stdoutSha256": sha256(result.stdout),
              "stderrBytes": len(result.stderr), "stderrSha256": sha256(result.stderr)}
    write_json(destination.with_name("process.json"), record)
    if not destination.is_file():
        raise RuntimeError("実R oracleの出力がありません。インストール/起動環境を確認してください。")
    return record


def require_runtime(output):
    runtime = output.get("runtime") or {}
    if runtime.get("engine") != "aquap2" or runtime.get("installedPackage") is not True or runtime.get("api") != "aquap2::gdmm" or runtime.get("sourceHarnessUsed") is not False:
        raise ValueError("実aquap2パッケージ/APIの証跡を確認できません: " + str(output.get("error", {})))
    if runtime.get("aquap2Version") != "0.4.5" or runtime.get("sourceCommit") != ap.core.REFERENCE_COMMIT:
        raise ValueError("固定版aquap2の版/commitが一致しません。")
    return runtime


def compare(py, r, payload, args):
    runtime = require_runtime(r)
    if r.get("ok") is not True or runtime.get("packageApiExecuted") is not True:
        raise ValueError("実aquap2公開APIの計算が成功していません: " + str(r.get("error", {})))
    if r.get("ids") != payload["ids"] or r.get("groups") != payload["groups"] or r.get("wavelengths") != payload["wavelengths"]:
        raise ValueError("試料ID/群名/順序/波長の往復が一致しません。")
    checks = {"nativePreprocessing": difference(np.array(py["preprocessed"]), np.array(r["preprocessed"]), args.atol, args.rtol)}
    p, q = py["pca"], r["pca"]
    pl, rl = np.array(p["loadings"]), np.array(q["loadings"])
    if pl.shape != rl.shape or np.array(p["scores"]).shape != np.array(q["scores"]).shape:
        raise ValueError("PCA形状が一致しません。")
    signs = np.where(np.sum(pl * rl, axis=0) >= 0, 1.0, -1.0)
    checks["pcaScoresSignAligned"] = difference(np.array(p["scores"]), np.array(q["scores"]) * signs, args.atol, args.rtol)
    checks["pcaLoadingsSignAligned"] = difference(pl, rl * signs, args.atol, args.rtol)
    checks["pcaExplainedVariance"] = difference(np.array(p["explainedVariance"]), np.array(q["explainedVariance"]), args.atol, args.rtol)
    pa, ra = py["aquagram"], r["aquagram"]
    if pa["wavelengths"] != ra["wavelengths"] or pa["mode"] != ra["mode"] or ra.get("ddof") != 1:
        raise ValueError("Aquagramの実波長/モード/SD定義が一致しません。")
    by_group = {g["name"]: g for g in ra["groups"]}
    if set(by_group) != {g["name"] for g in pa["groups"]}:
        raise ValueError("Aquagram群名が一致しません。")
    pv, rv = [], []
    for group in pa["groups"]:
        other = by_group[group["name"]]
        if group["n"] != other["n"]:
            raise ValueError("Aquagram群別試料数が一致しません。")
        pv.append(group["values"]); rv.append(other["values"])
    checks["aquagramSameSampleSdNoConversion"] = difference(np.array(pv), np.array(rv), args.atol, args.rtol)
    if any(not np.isfinite(c["maxAbsDiff"]) for c in checks.values()):
        raise ValueError("比較に非有限値が生じました。")
    matrix = np.array(py["preprocessed"])
    singular = np.linalg.svd(matrix - matrix.mean(0), compute_uv=False)
    k = len(signs)
    gap = float(np.min((singular[:k] - singular[1:k + 1]) / singular[:k]))
    if gap < 1e-5:
        raise ValueError("成分の符号だけの比較には固有値が近接しています。")
    return {"passed": all(c["passed"] for c in checks.values()), "checks": checks,
            "componentSignsAppliedToR": signs.astype(int).tolist(), "minimumRelativeSingularGap": gap,
            "runtime": runtime, "pyProvenance": py["provenance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rscript", default=shutil.which("Rscript") or "Rscript")
    parser.add_argument("--r-engine", type=Path, default=ROOT / "scripts/aquap2py_oracle.R")
    parser.add_argument("--r-runtime", type=Path, default=ROOT / "qa/aquap2-runtime-v1.4")
    parser.add_argument("--r-library", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "qa" / ("aquap2py-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--report", type=Path, default=ROOT / "qa/v1.5-aquap2py-verification.json")
    parser.add_argument("--atol", type=float, default=1e-8)
    parser.add_argument("--rtol", type=float, default=1e-7)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--case", action="append", help="Optional named subset, for debugging; report records actual scope")
    args = parser.parse_args()
    if not all(np.isfinite(v) and v > 0 for v in [args.atol, args.rtol, args.timeout]):
        raise SystemExit("許容差とtimeoutは有限の正数にしてください。")
    args.r_runtime = args.r_runtime.resolve(); args.r_engine = args.r_engine.resolve()
    if args.r_library: args.r_library = args.r_library.resolve()
    executable = shutil.which(args.rscript)
    if executable is None and Path(args.rscript).is_file(): executable = str(Path(args.rscript).resolve())
    if executable is None: raise SystemExit("実Rscriptを--rscriptで指定してください。")
    args.rscript = executable
    output, report_path = args.output.resolve(), args.report.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"schemaVersion": 1, "comparison": "aquap2py-raw-input-vs-installed-aquap2-native-preprocessing",
              "createdAt": datetime.now(timezone.utc).isoformat(), "artificial": True, "passed": False,
              "aquap2pyVersion": ap.__version__, "pythonVersions": versions(), "sourceHarnessUsed": False,
              "rOracleSha256": sha256(args.r_engine.read_bytes()),
              "pythonSourceSha256": {p.name: sha256(p.read_bytes()) for p in (ROOT / "python/aquap2py").glob("*.py")},
              "inputPolicy": "same raw matrix to Python and R; R gdmm dpt.pre performs native SG/SNV/MSC",
              "scope": ["sample SD classic/classic-diff without SD conversion", "R-native preprocessing including SG endpoints/ts=1, m0/1/2 and both operation orders", "centered unscaled PCA with sign alignment", "unequal group sizes, reserved/Unicode/quoted/newline labels, unequal wavelength spacing without resampling"],
              "excluded": ["full R export/API compatibility", "temperature calibration/AUC/sfc", "PLS/classification/bootstrap", "all upstream defaults; AQ internal MSC is explicitly false and smoothing explicitly 3", "real research data and clinical/scientific validity", "generic missing-value recovery or implicit row removal"],
              "runs": [], "degenerateChecks": []}
    try:
        x, w, ids, groups = fixture()
        write_json(output / "artificial-fixture.json", {"matrix": x.tolist(), "wavelengths": w.tolist(), "ids": ids, "groups": groups})
        chosen = [case for case in cases() if not args.case or case[0] in args.case]
        if not chosen: raise ValueError("指定された比較条件がありません。")
        for name, steps, reference, irregular in chosen:
            run_dir = output / name; run_dir.mkdir()
            wave = 1300.25 + np.cumsum(np.resize([3, 5, 7, 4, 6], len(w))) if irregular else w.copy()
            targets = wave[[4, 9, 14, 20, 25, 30, 36, 41, 46, 50, 54, 58]]
            payload = {"schemaVersion": 1, "matrix": x.tolist(), "wavelengths": wave.tolist(), "ids": ids, "groups": groups,
                       "steps": steps, "pca": {"components": 5, "scale": False},
                       "aquagram": {"wavelengths": targets.tolist(), "reference": reference}, "aqSmoothN": 3}
            write_json(run_dir / "input.json", payload)
            py = ap.gdmm(ap.ttap(x, wave, ids, groups), steps=steps, components=5, aquagram_wavelengths=targets, reference=reference)
            process = call_r(args, run_dir / "input.json", run_dir / "output.json")
            r = json.loads((run_dir / "output.json").read_text(encoding="utf-8-sig"))
            result = compare(py, r, payload, args)
            result.update(name=name, requestedSteps=steps, reference=reference, irregularWavelengths=irregular, process=process,
                          inputSha256=sha256((run_dir / "input.json").read_bytes()), outputSha256=sha256((run_dir / "output.json").read_bytes()))
            write_json(run_dir / "python-output.json", py)
            report["runs"].append(result)
            print(f"{name}: {'PASS' if result['passed'] else 'FAIL'}; maxAbsDiff={max(v['maxAbsDiff'] for v in result['checks'].values()):.3g}", flush=True)
        if not args.case:
            bad = x.copy(); bad[0] = .1
            for name, data, steps in [("constant-snv", bad, [{"method": "snv"}]), ("identical-spectra", np.tile(x[0], (len(x), 1)), [])]:
                run_dir = output / name; run_dir.mkdir()
                payload = {"schemaVersion": 1, "matrix": data.tolist(), "wavelengths": w.tolist(), "ids": ids, "groups": groups,
                           "steps": steps, "pca": {"components": 5, "scale": False},
                           "aquagram": {"wavelengths": w[[4, 14, 25]].tolist(), "reference": "global"}, "aqSmoothN": 3}
                write_json(run_dir / "input.json", payload)
                try: ap.gdmm(ap.ttap(data, w, ids, groups), steps=steps, components=5, aquagram_wavelengths=w[[4, 14, 25]])
                except ValueError: python_rejected = True
                else: python_rejected = False
                process = call_r(args, run_dir / "input.json", run_dir / "output.json")
                r = json.loads((run_dir / "output.json").read_text(encoding="utf-8-sig")); runtime = require_runtime(r)
                report["degenerateChecks"].append({"name": name, "pythonRejected": python_rejected,
                    "rRejectedOrPostApiGuard": r.get("ok") is False and process["exitCode"] != 0,
                    "rApiAttempted": runtime.get("gdmmAttempted"), "rError": r.get("error"), "process": process})
        report["numericCheckCount"] = sum(len(run["checks"]) for run in report["runs"])
        report["maximumAbsoluteDifferences"] = {key: max(run["checks"][key]["maxAbsDiff"] for run in report["runs"]) for key in report["runs"][0]["checks"]}
        report["passed"] = all(r["passed"] for r in report["runs"]) and all(c["pythonRejected"] and c["rRejectedOrPostApiGuard"] for c in report["degenerateChecks"])
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        print("FAIL:", type(exc).__name__, str(exc), file=sys.stderr)
    write_json(report_path, report); write_json(output / "report.json", report)
    print(f"runs={len(report['runs'])}; passed={report['passed']}; report={report_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

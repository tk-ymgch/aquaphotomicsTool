#!/usr/bin/env python3
"""Opt-in real installed aquap2 gdmm PLSR oracle; artificial data only.

R receives raw X and applies its own public native DPT. aquap2py receives the
same raw X and its Python DPT. R is never a package runtime dependency.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from aquap2py.plsr import plsr, predict_plsr, REFERENCE_COMMIT
from aquap2py.preprocessing import preprocess
from compare_aquap2 import difference, write_json, versions


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture():
    rng = np.random.default_rng(20261025)
    w = 1300.25 + 5 * np.arange(31)
    t = np.linspace(-1, 1, len(w))
    z = rng.normal(0, 1, (29, 3))
    x = (.5 + .15 * np.exp(-t * t * 3))[None, :] + z[:, :1] * (.02 * t)[None, :]
    x += z[:, 1:2] * (.025 * np.cos(3 * t))[None, :] + z[:, 2:3] * (.01 * t * t)[None, :]
    x += rng.normal(0, .0015, x.shape)
    y = 10 + 2 * z[:, 0] - .7 * z[:, 1] + rng.normal(0, .35, len(x))
    groups = ["global"] * 6 + ['対照,"A"'] * 8 + ["人工\nB"] * 10
    ids = [f"{i:04d}" for i in range(24)]
    ids[2] = '引用,"ID"\n日本語'
    return x[:24], y[:24], w, ids, groups, x[24:], y[24:]


def cases():
    sg = lambda m=0: {"method": "sgolay", "window": 11, "polyorder": 2, "derivative": m}
    return [
        ("raw-fixed-loo", [], 2, "LOO"),
        ("raw-auto-loo", [], None, "LOO"),
        ("snv-fixed-loo", [{"method": "snv"}], 2, "LOO"),
        ("msc-fixed-loo", [{"method": "msc"}], 2, "LOO"),
        ("sg-m0-fixed-loo", [sg()], 2, "LOO"),
        ("sg-m1-fixed-loo", [sg(1)], 2, "LOO"),
        ("sg-m2-fixed-loo", [sg(2)], 2, "LOO"),
        ("sg-snv-auto-loo", [sg(), {"method": "snv"}], None, "LOO"),
        ("snv-sg-fixed-group", [{"method": "snv"}, sg()], 2, "group"),
        ("sg-msc-auto-group", [sg(), {"method": "msc"}], None, "group"),
        ("raw-auto-group", [], None, "group"),
        ("raw-fixed-loo-unknown-unlabelled", [], 2, "LOO"),
        ("random-kfold-fixed-explicit-replay", [], 2, 4),
    ]


def call_r(args, source, destination, home):
    home.mkdir(parents=True)
    env = os.environ.copy()
    for key in list(env):
        if key == "R_HOME" or ((key == "LANG" or key.startswith("LC_")) and env[key] in {"C.UTF-8", "C.utf8"}):
            del env[key]
    env["AQUAP2_RUNTIME_ROOT"] = str(args.r_runtime)
    env["AQUAP2_LIBRARY"] = str(args.r_library or args.r_runtime / "library")
    env["R_USER"] = str(home)
    start = time.monotonic()
    proc = subprocess.run([args.rscript, "--vanilla", str(args.r_engine), str(source), str(destination)],
                          cwd=ROOT, env=env, capture_output=True, timeout=args.timeout, check=False)
    record = {"exitCode": proc.returncode, "elapsedSeconds": round(time.monotonic() - start, 3),
              "stdoutBytes": len(proc.stdout), "stderrBytes": len(proc.stderr),
              "stdoutSha256": hashlib.sha256(proc.stdout).hexdigest(), "stderrSha256": hashlib.sha256(proc.stderr).hexdigest()}
    destination.with_name("stdout.log").write_bytes(proc.stdout)
    destination.with_name("stderr.log").write_bytes(proc.stderr)
    write_json(destination.with_name("process.json"), record)
    if not destination.is_file():
        raise RuntimeError("正式R oracle出力なし。installed runtimeを確認してください。")
    return record


def verify_runtime(r):
    runtime = r.get("runtime") or {}
    if r.get("ok") is not True or runtime.get("installedPackage") is not True or runtime.get("packageApiExecuted") is not True:
        raise ValueError("正式installed gdmm PLSR失敗: " + str(r.get("error", {})))
    if runtime.get("api") != "aquap2::gdmm" or runtime.get("aquap2Version") != "0.4.5" or runtime.get("sourceCommit") != REFERENCE_COMMIT or runtime.get("sourceHarnessUsed") is not False:
        raise ValueError("正式API/固定版の証跡が不一致です。")
    if runtime.get("algorithm") != "kernelpls" or runtime.get("scale") is not False or runtime.get("center") is not True or runtime.get("actualModelMethod") != "kernelpls" or runtime.get("actualModelCenter") is not True or runtime.get("actualModelScalePresent") is not False:
        raise ValueError("native PLSRのアルゴリズム定義が不一致です。")
    return runtime


def compare(py, r, processed, payload, unknown, args):
    runtime = verify_runtime(r)
    if r["ids"] != payload["ids"] or r["cvGroups"] != payload["cvGroups"]:
        raise ValueError("行ID/CV群の順序が一致しません。")
    checks = {"nativePreprocessing": difference(processed, np.array(r["preprocessed"]), args.atol, args.rtol)}
    for key in ("model", "modelPlus"):
        a, b = py[key], r[key]
        aseg, bseg = a["validation"]["segments"], b["validation"]["segments"]
        # aquap2 translates LOO to CV(n segments), so pls randomly orders the
        # singleton folds. That order has no numerical or membership effect.
        if payload["pls"]["validation"] == "LOO":
            aseg, bseg = sorted(aseg), sorted(bseg)
        if a["ncomp"] != b["ncomp"] or aseg != bseg:
            raise ValueError("成分数またはCV分割が一致しません: " + key)
        for field in ("coefficients", "intercepts", "fitted", "residuals", "xMean", "yMean"):
            checks[f"{key}.{field}"] = difference(np.asarray(a[field]), np.asarray(b[field]), args.atol, args.rtol)
        for field in ("pred", "PRESS", "PRESS0", "adj"):
            checks[f"{key}.validation.{field}"] = difference(np.asarray(a["validation"][field]), np.asarray(b["validation"][field]), args.atol, args.rtol)
        for field in ("rmseCalibration", "rmseCV", "rmseAdjCV", "r2Calibration", "r2CV"):
            checks[f"{key}.curve.{field}"] = difference(np.array([v[field] for v in a["curve"]]), np.array([v[field] for v in b["curve"]]), args.atol, args.rtol)
    if "selectionReplay" in r:
        ref = r["selectionReplay"]
        if ref["source"] != "public-pls-deterministic-replay-after-formal-gdmm":
            raise ValueError("成分選択の補足再生定義が不正です。")
        for trial in py["selection"]["trials"]:
            if trial["candidateComponents"] != ref["ncomp"] or trial["components"] != int(np.argmin(ref["rmseAdjCV"])) + 1:
                raise ValueError("自動成分選択が一致しません。")
        checks["selection.deterministicReplayAdjCV"] = difference(np.array(py["selection"]["trials"][0]["rmseAdjCV"]), np.array(ref["rmseAdjCV"]), args.atol, args.rtol)
    if r.get("unknown", {}).get("api") != "aquap2::plot_pls_indepPred":
        raise ValueError("未知データの公開API証跡がありません。")
    checks["unknown.publicApiPredictionProcessedX"] = difference(np.array(predict_plsr(py, unknown)), np.array(r["unknown"]["predicted"]), args.atol, args.rtol)
    return checks, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rscript", default="Rscript")
    parser.add_argument("--r-runtime", type=Path, default=ROOT / "qa/aquap2-runtime-v1.4")
    parser.add_argument("--r-library", type=Path)
    parser.add_argument("--r-engine", type=Path, default=ROOT / "scripts/plsr_oracle.R")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--case", action="append")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--atol", type=float, default=1e-8)
    parser.add_argument("--rtol", type=float, default=1e-8)
    args = parser.parse_args()
    for key in ("r_runtime", "r_engine", "output", "report"):
        setattr(args, key, getattr(args, key).resolve())
    if args.output.exists():
        raise ValueError("証拠の上書きを避けるため新規outputフォルダーを指定してください。")
    args.output.mkdir(parents=True)
    x, y, w, ids, groups, ux, uy = fixture()
    write_json(args.output / "fixture.json", {"artificial": True, "seed": 20261025, "matrix": x.tolist(), "target": y.tolist(), "wavelengths": w.tolist(), "ids": ids, "cvGroups": groups})
    records = []
    for name, steps, ncomp, validation in cases():
        if args.case and name not in args.case:
            continue
        directory = args.output / name; directory.mkdir()
        # Native prediction does not apply DPT. Supply an explicitly processed
        # X fixture to both predictors; this check is not a DPT prediction API.
        processed = preprocess(x, steps)
        unknown = preprocess(np.vstack([x, ux]), steps)[len(x):]
        samples = [str(i // 2) for i in range(len(x))] if isinstance(validation, int) else None
        payload = {"schemaVersion": 1, "artificial": True, "matrix": x.tolist(), "target": y.tolist(),
                   "wavelengths": w.tolist(), "ids": ids, "cvGroups": groups, "sampleIds": samples,
                   "steps": steps, "seed": 20261025, "pls": {"ncomp": ncomp, "validation": validation},
                   "unknown": {"matrix": unknown.tolist(), "observed": None if name.endswith("unknown-unlabelled") else uy.tolist()}}
        source, destination = directory / "input.json", directory / "r-output.json"
        write_json(source, payload)
        try:
            process = call_r(args, source, destination, directory / "r-home")
            r = json.loads(destination.read_text(encoding="utf-8"))
            verify_runtime(r)
            replay = [r["model"]["validation"]["segments"]] if isinstance(validation, int) else None
            py = plsr(processed, y, ncomp=ncomp, validation=validation, cv_groups=groups if validation == "group" else None,
                      sample_ids=samples, seed=payload["seed"], segments_schedule=replay)
            write_json(directory / "python-output.json", py)
            checks, runtime = compare(py, r, processed, payload, unknown, args)
            passed = all(v["passed"] for v in checks.values()) and process["exitCode"] == 0
            record = {"case": name, "passed": passed, "steps": steps, "validation": validation,
                      "ncompRequested": ncomp, "selectedComponents": py["selectedComponents"], "checks": checks,
                      "runtime": runtime, "rngScope": "conditional-on-exported-final-R-segments" if isinstance(validation, int) else "deterministic-native-partitions",
                      "inputSha256": sha(source), "rOutputSha256": sha(destination), "pythonOutputSha256": sha(directory / "python-output.json")}
        except Exception as exc:
            record = {"case": name, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        records.append(record)
        print(f"{name}: {'PASS' if record['passed'] else 'FAIL'}", flush=True)
        if not record["passed"]:
            print(record.get("error") or {k: v for k, v in record["checks"].items() if not v["passed"]}, flush=True)
    total = sum(len(r.get("checks", {})) for r in records)
    report = {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
              "passed": bool(records) and all(v["passed"] for v in records), "artificialOnly": True,
              "formalApi": "installed aquap2 0.4.5 public gdmm + plot_pls_indepPred",
              "sourceHarnessUsed": False, "rRuntimeRequiredByPythonPackage": False,
              "versions": versions(), "cases": records, "caseCount": len(records), "numericCheckCount": total,
              "tolerance": {"atol": args.atol, "rtol": args.rtol},
              "coreFiles": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p)} for p in [ROOT / "python/aquap2py/plsr.py", ROOT / "python/aquap2py/preprocessing.py", args.r_engine, Path(__file__)]],
              "scope": ["PLS1 kernelpls / center TRUE / scale FALSE", "native DPT applied to all X before CV", "LOO and leave-one-group-out fixed/automatic components", "training/CV/adjusted-CV all-component predictions/coefficient/error curves", "unknown already-processed-X public prediction", "random fixed-component CV conditional on concrete exported R segments"],
              "excluded": ["R-seed/random-sample parity", "random-CV automatic-selection history parity", "PLS-specific outlier exclusion", "missing-target omission", "other pls methods/multi-response PLS2", "nested-CV performance equivalence", "automatic DPT application to unknown spectra", "real measured user-data validation"]}
    report["looSegmentOrderPolicy"] = "Compare exact singleton memberships, ignoring R's randomized order of singleton folds; OOF row order is unchanged."
    write_json(args.output / "report.json", report); write_json(args.report, report)
    print(json.dumps({"passed": report["passed"], "cases": len(records), "checks": total, "report": str(args.report)}, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

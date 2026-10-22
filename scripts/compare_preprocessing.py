#!/usr/bin/env python3
"""Compare bounded Python spectral preprocessing with installed aquap2 APIs.

Inputs are generated artificial spectra. R is an opt-in verification oracle;
the distributed implementation has no R process or network dependency.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from aquap2py.preprocessing import preprocess_spectra
from compare_aquap2 import difference, sha256, write_json


def fixtures():
    rng = np.random.default_rng(20261024)
    regular = np.arange(61) * 5.0 + 1300.25
    irregular = 1300.25 + np.r_[0.0, np.cumsum(np.resize([4.1, 5.2, 6.3, 5.4], 60))]

    def matrix(waves):
        z = (waves - waves.mean()) / 80
        return np.array([(.4 + .2 * np.exp(-z*z) + .017 * np.sin((i + 1) * z / 3)) * (1 + i / 30)
                         + .002 * i * z + rng.normal(0, .0003, len(waves)) for i in range(8)])

    x, xi = matrix(regular), matrix(irregular)
    cases = []

    def add(name, steps, irregular_grid=False, short=False):
        waves, rows = (irregular, xi) if irregular_grid else (regular, x)
        if short:
            waves, rows = waves[[0, 30, 60]], rows[:, [0, 30, 60]]
        cases.append({"name": name, "matrix": rows.tolist(), "wavelengths": waves.tolist(), "steps": steps})

    add("detrend-full", [{"method": "detrend"}])
    add("detrend-source", [{"method": "detrend", "src": [1340.25, 1500.25]}])
    add("detrend-source-to-all", [{"method": "detrend", "src": [1340.25, 1500.25], "trg": "all"}])
    add("detrend-source-to-null-target", [{"method": "detrend", "src": [1340.25, 1500.25], "trg": None}])
    add("detrend-separate-target", [{"method": "detrend", "src": [1341.1, 1499.9], "trg": [1401.1, 1579.9]}])
    add("detrend-irregular", [{"method": "detrend", "src": [1350, 1500], "trg": "all"}], True)
    z = np.linspace(-1, 1, len(regular))
    effect1 = np.sin(z * 3) + z ** 2
    effects2 = np.column_stack([effect1, np.cos(z * 4) - z])
    add("emsc-one-effect", [{"method": "emsc", "vec_load": effect1[:, None].tolist()}])
    add("emsc-two-effects", [{"method": "emsc", "vec_load": effects2.tolist()}])
    add("snv-then-emsc", [{"method": "snv"}, {"method": "emsc", "vec_load": effect1[:, None].tolist()}])
    for order in range(1, 5):
        add(f"gap-m{order}-default", [{"method": "gap_derivative", "m": order}])
        add(f"gap-m{order}-w3-s3", [{"method": "gap_derivative", "m": order, "w": 3, "s": 3, "delta_w": 2.5}])
    add("gap-irregular-nominal-spacing", [{"method": "gap_derivative", "w": 5, "s": 3, "delta_w": 1}], True)
    add("gap-three-point-single-output", [{"method": "gap_derivative"}], short=True)
    for irregular_grid in (False, True):
        w = irregular if irregular_grid else regular
        targets = np.sort(np.r_[w[[0, -1]], (w[:-1] + w[1:]) / 2, w[::3]])
        targets = np.unique(targets)
        for method in ("linear", "constant", "nearest", "cubic", "spline"):
            add(f"resample-{method}-{'irregular' if irregular_grid else 'regular'}",
                [{"method": "resample", "interpolation": method, "target_wavelengths": targets.tolist()}], irregular_grid)
    add("resample-default-grid", [{"method": "resample"}])
    add("resample-grid-tby1p3", [{"method": "resample", "tby": 1.3, "interpolation": "linear"}])
    add("resample-three-point-cubic", [{"method": "resample", "target_wavelengths": [1300.25, 1375.25, 1450.25, 1525.25, 1600.25]}], short=True)
    add("detrend-snv-sgolay", [{"method": "detrend"}, {"method": "snv"}, {"method": "sgolay", "window": 11}])
    add("resample-gap-snv", [{"method": "resample", "tby": 2.0}, {"method": "gap_derivative", "m": 2, "s": 3}, {"method": "snv"}])
    add("gap-detrend", [{"method": "gap_derivative", "m": 1, "w": 3}, {"method": "detrend"}])
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rscript", default="Rscript")
    parser.add_argument("--r-runtime", type=Path, default=ROOT / "qa/aquap2-runtime-v1.4")
    parser.add_argument("--output", type=Path, default=ROOT / "qa/v1.7-preprocessing-oracle")
    parser.add_argument("--report", type=Path, default=ROOT / "qa/v1.7-preprocessing-verification.json")
    parser.add_argument("--atol", type=float, default=1e-9)
    parser.add_argument("--rtol", type=float, default=1e-8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = fixtures()
    payload = {"schemaVersion": 1, "artificialOnly": True, "cases": cases}
    source, destination = args.output / "input.json", args.output / "output.json"
    write_json(source, payload)
    env = os.environ.copy()
    for key in list(env):
        if (key == "LANG" or key.startswith("LC_")) and env[key] in {"C.UTF-8", "C.utf8"}:
            del env[key]
    env.update(AQUAP2_RUNTIME_ROOT=str(args.r_runtime.resolve()), AQUAP2_LIBRARY=str((args.r_runtime / "library").resolve()),
               R_USER=str((args.r_runtime / "home").resolve()))
    process = subprocess.run([args.rscript, "--vanilla", str(ROOT / "scripts/preprocessing_oracle.R"), str(source), str(destination)],
                             env=env, cwd=ROOT, capture_output=True, timeout=240, check=False)
    write_json(args.output / "process.json", {"exitCode": process.returncode, "stdoutSha256": sha256(process.stdout),
               "stderrSha256": sha256(process.stderr), "stdoutBytes": len(process.stdout), "stderrBytes": len(process.stderr)})
    (args.output / "stderr.log").write_bytes(process.stderr)
    oracle = json.loads(destination.read_text(encoding="utf-8"))
    runtime = oracle.get("runtime") or {}
    if not oracle.get("ok") or process.returncode or runtime.get("sourceHarnessUsed") is not False or not runtime.get("packageApiExecuted") or runtime.get("aquap2Version") != "0.4.5":
        raise RuntimeError("Installed public API oracle failed: " + str(oracle.get("error")))
    records = []
    outputs = {case["name"]: case for case in oracle["cases"]}
    for case in cases:
        py = preprocess_spectra(case["matrix"], case["wavelengths"], case["steps"])
        r = outputs[case["name"]]
        checks = {"matrix": difference(py["matrix"], np.array(r["matrix"]), args.atol, args.rtol),
                  "wavelengths": difference(py["wavelengths"], np.array(r["wavelengths"]), 1e-10, 1e-12)}
        records.append({"name": case["name"], "passed": all(x["passed"] for x in checks.values()), "checks": checks,
                        "rPublicApis": r["executed"], "rowAlignmentPreserved": r["rowAlignmentPreserved"],
                        "inputShape": list(np.asarray(case["matrix"]).shape), "outputShape": list(py["matrix"].shape)})
    report = {"schemaVersion": 1, "createdAt": datetime.now(timezone.utc).isoformat(), "passed": all(c["passed"] for c in records),
              "artificialOnly": True, "completeCompatibility": False, "conditions": len(records),
              "numericValuesCompared": sum(np.asarray(outputs[c["name"]][key]).size for c in cases for key in ("matrix", "wavelengths")),
              "atol": args.atol, "rtol": args.rtol, "runtime": runtime, "cases": records,
              "scope": "Matrix/wavelength binding of four public preprocessing functions; not R S4 metadata/exportModel equivalence",
              "guardDifferences": ["strict finite ascending positive wavelengths and no extrapolation", "singular EMSC/zero scale refused",
                 "empty/single-point detrend source/target refused", "gap order 1..4 and odd widths <=501", "resample output 2..10000 wavelengths and <=2M elements",
                 "no unknown-interpolation fallback and no unsorted/duplicate-grid averaging", "spline requires >=4 source points; R three-point spline is non-finite"],
              "sources": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p.read_bytes())} for p in [ROOT / "python/aquap2py/preprocessing.py", ROOT / "scripts/preprocessing_oracle.R", ROOT / "scripts/compare_preprocessing.py"]],
              "fixtureSha256": sha256(source.read_bytes()), "oracleOutputSha256": sha256(destination.read_bytes())}
    write_json(args.report, report)
    print(json.dumps({key: report[key] for key in ("passed", "conditions", "numericValuesCompared", "atol", "rtol")}))
    if not report["passed"]:
        raise SystemExit("Mismatches: " + ", ".join(c["name"] for c in records if not c["passed"]))


if __name__ == "__main__":
    main()

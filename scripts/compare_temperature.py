"""Opt-in comparison against installed public aquap2 temperature calibration APIs.

Artificial data only. Numerical tolerances are fixed before execution.
No R source harness or replacement/patch of installed functions is used.
"""
from __future__ import annotations

import argparse
import hashlib
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
from aquap2py.temperature import temperature_aquagram, temperature_calibration
from aquap2py.core import VERSION


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n",encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture():
    w=np.arange(1300.,1601.)
    g=lambda center,width:np.exp(-.5*((w-center)/width)**2)
    def spectrum(t,j=0,group=0):
        z=t-30
        return .06+.00002*(w-1300)+(.35+.003*z+.00012*z*z)*g(1445,65)+(.13-.0021*z+.00005*z**3)*g(1370,20)+(.09+.0014*z)*g(1510,24)+(.03+.0007*z*z)*g(1410,12)+(.06+.003*z)*g(1411,6)+j*.00001*np.sin(w/21)+group*.0003*g(1475,15)
    temp=np.repeat(np.arange(20.,41.),3)
    cal=np.array([spectrum(t,i%3) for i,t in enumerate(temp)])
    groups=["global"]*3+['対照, "群"']*4+["処理\n群"]*5
    x=np.array([spectrum(29+(i+1)/20,i+1,groups.index(name)) for i,name in enumerate(groups)])
    return x,w,groups,cal,temp


def run_r(args, folder, payload):
    write(folder/"input.json",payload)
    env=os.environ.copy()
    if os.name=="nt":
        for key in list(env):
            if key in {"LANG","LANGUAGE"} or key.startswith("LC_"):
                del env[key]
    home=folder/"home";home.mkdir()
    env["R_USER"]=str(home);env["HOME"]=str(home)
    env["AQUAP2_RUNTIME_ROOT"]=str(args.r_runtime)
    env["AQUAP2_LIBRARY"]=str(args.r_library or args.r_runtime/"library")
    start=time.monotonic()
    result=subprocess.run([args.rscript,"--vanilla",str(args.r_engine),str(folder/"input.json"),str(folder/"output.json")],cwd=ROOT,env=env,capture_output=True,timeout=args.timeout,check=False)
    process={"exitCode":result.returncode,"elapsedSeconds":round(time.monotonic()-start,3),
             "stdoutBytes":len(result.stdout),"stderrBytes":len(result.stderr),
             "stdoutSha256":hashlib.sha256(result.stdout).hexdigest(),"stderrSha256":hashlib.sha256(result.stderr).hexdigest()}
    write(folder/"process.json",process)
    if not (folder/"output.json").is_file():
        raise RuntimeError("R oracle did not write a result.")
    output=json.loads((folder/"output.json").read_text(encoding="utf-8-sig"))
    runtime=output.get("runtime") or {}
    if not output.get("ok") or result.returncode or runtime.get("api")!="aquap2::gdmm" or runtime.get("installedPackage") is not True or runtime.get("packageApiExecuted") is not True or runtime.get("sourceHarnessUsed") is not False or runtime.get("sourceCommit")!="d31c1231bf71f0e73f1a630a32934602782be488":
        raise RuntimeError("Installed public oracle failed: "+str(output.get("error")))
    return output,process


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rscript",default=shutil.which("Rscript") or "C:/Program Files/R/R-4.6.1/bin/x64/Rscript.exe")
    parser.add_argument("--r-runtime",type=Path,default=ROOT/"qa/aquap2-runtime-v1.4")
    parser.add_argument("--r-library",type=Path)
    parser.add_argument("--r-engine",type=Path,default=ROOT/"scripts/temperature_oracle.R")
    parser.add_argument("--output",type=Path,default=ROOT/"qa/v1.6-temperature-oracle-verified")
    parser.add_argument("--report",type=Path,default=ROOT/"qa/v1.6-temperature-verification.json")
    parser.add_argument("--timeout",type=float,default=90)
    parser.add_argument("--atol",type=float,default=1e-8)
    parser.add_argument("--rtol",type=float,default=1e-7)
    args=parser.parse_args()
    if not all(np.isfinite(v) and v>0 for v in (args.timeout,args.atol,args.rtol)):raise SystemExit("Positive finite tolerances/timeouts required.")
    args.r_runtime=args.r_runtime.resolve();args.r_engine=args.r_engine.resolve()
    args.output=args.output.resolve();args.report=args.report.resolve()
    if args.r_library:args.r_library=args.r_library.resolve()
    if not str(args.output).startswith(str(ROOT/"qa/v1.6-temperature-")):raise SystemExit("Output must be in qa/v1.6-temperature-*.")
    args.output.mkdir(parents=True,exist_ok=False)
    x,w,groups,cal,temp=fixture()
    base={"schemaVersion":1,"matrix":x.tolist(),"wavelengths":w.tolist(),"groups":groups,
          "calibration":{"matrix":cal.tolist(),"wavelengths":w.tolist(),"temperatures":temp.tolist()}}
    write(args.output/"artificial-fixture.json",base)
    report={"schemaVersion":1,"passed":False,"artificial":True,"sourceHarnessUsed":False,"aquap2pyVersion":VERSION,
            "reference":{"version":"0.4.5","commit":"d31c1231bf71f0e73f1a630a32934602782be488"},
            "pythonSourceSha256":digest(ROOT/"python/aquap2py/temperature.py"),"rOracleSha256":digest(args.r_engine),
            "pythonDependencySourceSha256":{name:digest(ROOT/"python/aquap2py"/name) for name in ("core.py","preprocessing.py")},
            "scope":"All 10 non-classic modes, two fixed coordinate systems, observed endpoints/Texp only; curated artificial calibration, no random balancing/bootstrap.",
            "excluded":["unobserved-temperature robust LOESS","full R defaults/metadata/outlier-detection","real data/scientific validity","bootstrap/CI/balancing"],
            "runs":[],"guards":[]}
    modes=["sfc","sfc-diff","aucs","aucs-diff","aucs.tn","aucs.tn-diff","aucs.tn.dce","aucs.tn.dce-diff","aucs.dce","aucs.dce-diff"]
    cases=[(coord,mode,False,[28,32],30) for coord in ("ot1.12","ot1.15") for mode in modes]
    cases += [("ot1.12","sfc",True,[28,32],30),("ot1.12","sfc-diff",True,[28,32],30),
              ("ot1.12","aucs.dce",False,None,30),("ot1.12","aucs.tn.dce",False,"symm@2",30),
              ("ot1.15","aucs",False,[28,32],30),("ot1.15","aucs.tn.dce",False,[28,32],30)]
    try:
        for i,(coord,mode,msc,tc,te) in enumerate(cases):
            folder=args.output/f"{i+1:02d}-{coord}-{mode}";folder.mkdir()
            cfg={"coordinateSystem":coord,"mode":mode,"tCalib":tc,"tExp":te,"reference":groups[0] if mode.endswith("-diff") else None,
                 "smoothN":21,"calibrationSmoothN":17,"msc":msc,"targets":None}
            irregular=i>=24
            keep=np.array([j%7 not in {1,5} for j in range(len(w))]) if irregular else np.ones(len(w),dtype=bool)
            mx,mw=x[:,keep],w[keep]
            model=temperature_calibration(cal,w,temp,coordinate_system=coord)
            py=temperature_aquagram(mx,mw,groups,model,mode=mode,t_calib=tc,t_exp=te,reference=cfg["reference"],msc=msc)
            r,process=run_r(args,folder,{**base,"matrix":mx.tolist(),"wavelengths":mw.tolist(),"config":cfg})
            write(folder/"python-output.json",py)
            by_group={g["name"]:g for g in r["result"]["groups"]}
            if set(by_group)!={g["name"] for g in py["groups"]}:raise ValueError("Group labels changed.")
            a,b=[],[]
            for group in py["groups"]:
                other=by_group[group["name"]]
                if other["n"]!=group["n"]:raise ValueError("Group counts changed.")
                a.extend(group["values"]);b.extend(other["values"])
            a,b=np.asarray(a),np.asarray(b)
            if a.shape!=b.shape or not np.isfinite(b).all():raise ValueError("Invalid oracle output shape/finiteness.")
            delta=np.abs(a-b);tolerance=args.atol+args.rtol*np.abs(b)
            check={"name":folder.name,"mode":mode,"coordinateSystem":coord,"msc":msc,"tCalib":tc,"tExp":te,"irregularWavelengths":irregular,
                   "passed":bool(np.all(delta<=tolerance)),"values":len(a),"maxAbsDiff":float(delta.max()),
                   "maxToleranceRatio":float(np.max(delta/tolerance)),"atol":args.atol,"rtol":args.rtol,
                   "runtime":r["runtime"],"inputSha256":digest(folder/"input.json"),"outputSha256":digest(folder/"output.json"),"process":process}
            if not mode.startswith("sfc") and py["labels"]!=r["result"]["labels"]:raise ValueError("Coordinate labels changed.")
            report["runs"].append(check)
            print(folder.name+": "+("PASS" if check["passed"] else "FAIL")+f" max={check['maxAbsDiff']:.3g}",flush=True)
        for name,kwargs in [("unobserved-endpoint",{"t_calib":[28.25,32.25]}),("unobserved-Texp",{"t_exp":30.25}),
                            ("bootstrap",{"boot_ci":True}),("balancing",{"nr_corr":True})]:
            try:temperature_aquagram(x,w,groups,model,**{"t_calib":[28,32],"t_exp":30,**kwargs})
            except ValueError as e:report["guards"].append({"name":name,"rejected":True,"reason":str(e)})
            else:report["guards"].append({"name":name,"rejected":False})
        report["maximumAbsoluteDifference"]=max(r["maxAbsDiff"] for r in report["runs"])
        report["numericValuesCompared"]=sum(r["values"] for r in report["runs"])
        report["passed"]=all(r["passed"] for r in report["runs"]) and all(g["rejected"] for g in report["guards"])
    except Exception as e:
        report["error"]={"type":type(e).__name__,"message":str(e)}
        print("FAIL: "+str(e),file=sys.stderr)
    write(args.report,report);write(args.output/"report.json",report)
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())

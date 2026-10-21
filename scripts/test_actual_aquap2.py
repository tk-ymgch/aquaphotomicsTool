"""Opt-in installed aquap2 smoke; no HTTP server and no production measurements."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly run the local R package')
    parser.add_argument('--rscript', default='C:/Program Files/R/R-4.6.1/bin/x64/Rscript.exe')
    parser.add_argument('--runtime-root', type=Path)
    args = parser.parse_args()
    if not args.run:
        print('Skipped: pass --run to execute the installed local aquap2 runtime.')
        return
    project = Path(__file__).resolve().parent.parent
    runtime = (args.runtime_root or project / 'qa/aquap2-runtime-v1.4').resolve()
    library = runtime / 'library'
    receipt = runtime / 'installation.json'
    if not receipt.is_file() or not library.is_dir():
        raise SystemExit('Run scripts/setup_aquap2.R first.')
    run = runtime / 'smoke' / f'run-{time.time_ns()}'
    for folder in ('home', 'settings', 'jobs', 'temp'):
        (run / folder).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(receipt, run / 'installation.json')
    env = os.environ.copy()
    if os.name == 'nt':
        for key in list(env):
            if key.startswith('LC_') or key in ('LANG', 'LANGUAGE'):
                env.pop(key)
    rscript = Path(args.rscript).resolve()
    r_home = rscript.parent.parent.parent if rscript.parent.name.lower() == 'x64' else rscript.parent.parent
    env.update(AQUAP2_RUNTIME_ROOT=str(run), AQUAP2_LIBRARY=str(library), R_USER=str(run / 'home'),
               R_LIBS_USER=str(library), R_HOME=str(r_home), TMPDIR=str(run / 'temp'))
    env.pop('AQUAP2_KEEP_EVIDENCE', None)
    engine = project / 'scripts/aquap2_engine.R'
    checks: list[dict] = []

    def invoke(label: str, payload: dict | None = None, expected_ok: bool = True) -> dict:
        command = [str(rscript), '--vanilla', str(engine)]
        output = run / f'{label}-output.json'
        if payload is None:
            command += ['--health']
        else:
            path = run / f'{label}-input.json'
            path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            command += [str(path), str(output)]
        result = subprocess.run(command, env=env, capture_output=True, timeout=90, check=False)
        (run / f'{label}-stderr.log').write_bytes(result.stderr)
        if payload is None:
            data = json.loads(result.stdout.decode('utf-8'))
            output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            assert result.stdout == b'', f'{label}: analysis logs reached stdout'
            data = json.loads(output.read_text(encoding='utf-8'))
        assert bool(data['ok']) is expected_ok, (label, data)
        assert (result.returncode == 0) is expected_ok, (label, result.returncode)
        assert not list((run / 'jobs').glob('request-*')), f'{label}: request artifacts retained'
        assert str(run).lower() not in json.dumps(data).lower(), f'{label}: runtime path exposed'
        checks.append({'name': label, 'ok': True, 'exit': result.returncode,
                       'packageApiExecuted': data.get('runtime', {}).get('packageApiExecuted', False)})
        return data

    health = invoke('health')
    assert health['runtime']['installedPackage'] is True
    assert health['runtime']['packageApiExecuted'] is False
    assert health['runtime']['aquap2Version'] == '0.4.5'
    wls = [1342, 1364.25, 1374, 1384, 1412, 1426, 1440, 1452, 1462, 1476, 1488, 1512]
    matrix = [[1 + .03*i + .007*j + .002*i*j + .004*math.sin(i*j)
               for j in range(1, 13)] for i in range(1, 10)]
    ids = ['001', 'NA', '引用,"ID"', '日本語4', '005', '006', '007', '008', '009']
    groups = ['Z群'] * 3 + ['全体平均'] * 3 + ['group:予約語'] * 3
    payload = {'schemaVersion': 1, 'matrix': matrix, 'wavelengths': wls, 'ids': ids, 'groups': groups,
               'aquagram': {'wavelengths': wls, 'reference': 'global'},
               'pca': {'components': 8, 'scale': False}}
    global_result = invoke('global', payload)
    assert global_result['pca']['ids'] == ids and global_result['pca']['groups'] == groups
    assert global_result['runtime']['packageApiExecuted'] is True
    assert global_result['aquagram']['mode'] == 'classic'
    assert global_result['aquagram']['wavelengths'] == wls
    n, p = len(matrix), len(wls)
    means = [sum(row[j] for row in matrix) / n for j in range(p)]
    sample_sd = [math.sqrt(sum((row[j]-means[j])**2 for row in matrix)/(n-1)) for j in range(p)]
    maximum_aq_error = 0.0
    for group in global_result['aquagram']['groups']:
        selected = [row for row, label in zip(matrix, groups) if label == group['name']]
        assert group['n'] == len(selected)
        for j, value in enumerate(group['values']):
            expected = (sum(row[j] for row in selected)/len(selected)-means[j])/sample_sd[j]
            maximum_aq_error = max(maximum_aq_error, abs(value-expected))
    assert maximum_aq_error < 1e-12
    scores, loadings = global_result['pca']['scores'], global_result['pca']['loadings']
    reconstruction_error = max(abs(sum(scores[i][k]*loadings[j][k] for k in range(8))
                                   - (matrix[i][j]-means[j])) for i in range(n) for j in range(p))
    assert reconstruction_error < 1e-12
    assert abs(sum(global_result['pca']['explainedVariance'])-1) < 1e-12
    control_payload = json.loads(json.dumps(payload))
    control_payload['aquagram']['reference'] = 'group:全体平均'
    control_result = invoke('control', control_payload)
    assert control_result['aquagram']['mode'] == 'classic-diff'
    control_values = next(g['values'] for g in global_result['aquagram']['groups'] if g['name'] == '全体平均')
    for group in control_result['aquagram']['groups']:
        original = next(g['values'] for g in global_result['aquagram']['groups'] if g['name'] == group['name'])
        assert max(abs(a-(b-c)) for a, b, c in zip(group['values'], original, control_values)) < 1e-12
    for label, change in [('none', lambda d: d['aquagram'].update(reference='none')),
                          ('pca-scale', lambda d: d['pca'].update(scale=True)),
                          ('missing-wavelength', lambda d: d['aquagram'].update(wavelengths=[1, 2, 3])),
                          ('pls', lambda d: d.update(pls={'enabled': True}))]:
        invalid = json.loads(json.dumps(payload)); change(invalid)
        error = invoke(label, invalid, expected_ok=False)
        assert error['error']['code'] == 'UNSUPPORTED_INPUT'
    evidence = {'schemaVersion': 1, 'status': 'pass', 'actualInstalledPackage': True,
                'api': 'aquap2::gdmm', 'runtime': global_result['runtime'], 'checks': checks,
                'maximumAquagramFormulaError': maximum_aq_error,
                'pcaReconstructionError': reconstruction_error,
                'normalRequestJobsRetained': 0, 'artificialOnly': True,
                'engineSha256': hashlib.sha256(engine.read_bytes()).hexdigest(),
                'installationReceiptSha256': hashlib.sha256(receipt.read_bytes()).hexdigest(),
                'artifacts': str(run.relative_to(project)).replace('\\', '/')}
    destination = project / 'qa/v1.4-runtime-smoke.json'
    destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'status': 'pass', 'checks': len(checks), 'maximumAquagramFormulaError': maximum_aq_error,
                      'pcaReconstructionError': reconstruction_error, 'evidence': str(destination)}, ensure_ascii=True))


if __name__ == '__main__':
    main()

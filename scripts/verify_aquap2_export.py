"""Recompute a UI-exported hybrid result from its saved input and conditions."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wb', ROOT / 'python/workbench.py')
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)


def verify(path):
    checks = {}
    with zipfile.ZipFile(path) as z:
        settings = json.loads(z.read('settings.json'))
        runtime = json.loads(z.read('aquap2_runtime.json'))
        assert runtime['installedPackage'] and runtime['packageApiExecuted']
        assert runtime['api'] == 'aquap2::gdmm'
        assert runtime['aquagramSdDdof'] == 1
        assert settings['_provenance']['aquap2_not_executed'] is False
        document = json.loads(z.read('analysis-settings.json'))
        assert document['config']['analysisEngine'] == 'aquap2'
        assert not any(key in document['config'] for key in ('endpoint','token','authorization'))
        checks['actualPackageProvenance'] = True
        source, name = next((p, p.split('/')[-1]) for p in z.namelist() if p.startswith('data/input.'))
        df, _ = wb.inspect_bytes(z.read(source), name, settings['_provenance'].get('source', {}).get('sheet'))
        baseline = wb.analyze(df, settings['_provenance']['requestedConfig'])
        def table(name): return pd.read_csv(io.BytesIO(z.read(name)))
        pre = table('data/preprocessed.csv').select_dtypes(include='number').to_numpy()
        expected = pd.read_csv(io.StringIO(baseline['exports']['data/preprocessed.csv'])).select_dtypes(include='number').to_numpy()
        np.testing.assert_allclose(pre, expected, atol=1e-10, rtol=1e-10)
        checks['preprocessingMaximumDifference'] = float(np.max(np.abs(pre-expected)))
        scores = table('data/pca_scores.csv').filter(regex=r'^PC\d+$').to_numpy()
        loads = table('data/pca_loadings.csv').filter(regex=r'^PC\d+$').to_numpy()
        expected_scores = np.asarray(baseline['pca']['scores'])
        expected_loads = np.asarray(baseline['pca']['loadings'])
        signs = np.where(np.sum(loads * expected_loads, axis=0) < 0, -1, 1)
        for key, saved, expected in [('pcaScores', scores*signs, expected_scores), ('pcaLoadings', loads*signs, expected_loads),
            ('pcaVariance',table('data/pca_variance.csv')['explained_variance_ratio'].to_numpy(),np.asarray(baseline['pca']['explainedVariance']))]:
            np.testing.assert_allclose(saved,expected,atol=1e-7,rtol=1e-6)
            checks[key+'MaximumDifference'] = float(np.max(np.abs(saved-expected)))
        aq = table('data/aquagram.csv')
        native_aq = pd.read_csv(io.StringIO(baseline['exports']['data/aquagram.csv']))
        assert list(aq['group']) == list(native_aq['group'])
        np.testing.assert_array_equal(aq['wavelength_nm'],native_aq['wavelength_nm'])
        factor = np.sqrt((len(df)-1)/len(df))
        np.testing.assert_allclose(aq['value'],native_aq['value']*factor,atol=1e-7,rtol=1e-6)
        checks['aquagramMaximumDifferenceAfterSdConversion'] = float(np.max(np.abs(aq['value']-native_aq['value']*factor)))
        comparison = table('data/aquap2_vs_python_aquagram.csv')
        np.testing.assert_allclose(comparison['difference_from_expected'],aq['value']-native_aq['value']*factor,atol=1e-10)
        checks['comparisonRows'] = len(comparison)
        pngs = [p for p in z.namelist() if p.endswith('.png')]
        assert len(pngs) >= 6 and all(z.read(p).startswith(b'\x89PNG\r\n\x1a\n') for p in pngs)
        checks['figures'] = len(pngs)
    return {'schemaVersion':1,'passed':True,'scope':'saved UI ZIP replay; centered PCA sign aligned; Aquagram SD definition converted',
            'aquap2Version':runtime['aquap2Version'],'rVersion':runtime['rVersion'],'checks':checks}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=verify(args.archive)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))

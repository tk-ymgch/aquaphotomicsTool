"""Exercise the loopback HTTP boundary without installing or mocking aquap2 internals."""
import copy
import importlib.util
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest

spec = importlib.util.spec_from_file_location('aqua_bridge', Path(__file__).resolve().parents[1] / 'bridge/serve.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
ORIGIN = 'https://aquaphotomics-workbench.tkymgch.chatgpt.site'
PAGES_ORIGIN = 'https://aquaphotomics-workbench.pages.dev'
JOB = {'schemaVersion':1, 'matrix':[[1,2,4],[2,1,3],[3,4,2]], 'wavelengths':[1300,1400,1500],
       'ids':['001','002','003'], 'groups':['群 A','対照','群 A'],
       'aquagram':{'wavelengths':[1300,1400,1500],'reference':'global'},'pca':{'components':2,'scale':False}}


class FakeRuntime:
    def __init__(self): self.jobs=[]
    def health(self): return {'schemaVersion':1,'available':True,'engine':'aquap2','aquap2Version':'test','rVersion':'test','api':'aquap2::gdmm'}
    def analyze(self, job):
        self.jobs.append(job)
        return {'accepted':True}


@pytest.fixture
def service():
    runtime = FakeRuntime()
    server = bridge.BridgeServer(('127.0.0.1',0), runtime)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    def call(path, body=None, headers=None, method=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path, data=data,
            headers={'Origin':ORIGIN,'X-Aquaphotomics-Client':'1','Content-Type':'application/json',**(headers or {})},method=method)
        try: response=urllib.request.urlopen(request,timeout=3)
        except urllib.error.HTTPError as exc: response=exc
        with response:
            payload=response.read()
            return response.status, dict(response.headers),json.loads(payload) if payload else None
    yield server,runtime,call
    server.shutdown();server.server_close();worker.join(3)


def test_loopback_origin_host_and_custom_header_are_required(service):
    _,_,call=service
    assert call('/health')[0]==200
    for headers in [{'Origin':'https://malicious.example'}, {'Origin':'null'}, {'Host':'rebinding.example'}, {'X-Aquaphotomics-Client':''}]:
        status,h,_=call('/health',headers=headers)
        assert status==403
        if headers.get('Origin') in {'https://malicious.example','null'}: assert 'Access-Control-Allow-Origin' not in h
    with pytest.raises(ValueError): bridge.BridgeServer(('0.0.0.0',0),FakeRuntime())


def test_preflight_allows_only_the_expected_protocol(service):
    _,_,call=service
    status,h,_=call('/analyze',method='OPTIONS',headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,authorization,x-aquaphotomics-client'})
    assert status==204 and h['Access-Control-Allow-Origin']==ORIGIN and h['Access-Control-Allow-Private-Network']=='true'
    assert call('/analyze',method='OPTIONS',headers={'Access-Control-Request-Method':'DELETE'})[0]==403
    assert call('/analyze',method='OPTIONS',headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'x-code'})[0]==403


@pytest.mark.parametrize('origin', [ORIGIN, PAGES_ORIGIN])
def test_published_origins_support_preflight_session_and_analysis(service, origin):
    _,runtime,call=service
    headers={'Origin':origin}
    status,h,health=call('/health',headers=headers)
    assert status==200 and h['Access-Control-Allow-Origin']==origin
    assert health['engine']=='aquap2'
    status,h,_=call('/analyze',method='OPTIONS',headers={**headers,
        'Access-Control-Request-Method':'POST',
        'Access-Control-Request-Headers':'content-type,authorization,x-aquaphotomics-client'})
    assert status==204 and h['Access-Control-Allow-Origin']==origin
    assert h['Access-Control-Allow-Private-Network']=='true'
    status,h,session=call('/session',{'client':'aquaphotomics-workbench'},headers)
    assert status==200 and h['Access-Control-Allow-Origin']==origin
    status,h,result=call('/analyze',JOB,{**headers,'Authorization':'Bearer '+session['token']})
    assert status==200 and h['Access-Control-Allow-Origin']==origin
    assert result=={'accepted':True} and runtime.jobs==[JOB]


@pytest.mark.parametrize('origin', [
    'https://unrelated-project.pages.dev',
    'https://preview.aquaphotomics-workbench.pages.dev',
    'https://aquaphotomics-workbench.pages.dev.evil.example',
])
def test_other_pages_origins_cannot_connect_or_create_sessions(service, origin):
    server,runtime,call=service
    headers={'Origin':origin}
    requests=[('/health',None,None),
              ('/session',{'client':'aquaphotomics-workbench'},None),
              ('/analyze',None,'OPTIONS')]
    for path,body,method in requests:
        status,h,_=call(path,body,headers,method)
        assert status==403 and 'Access-Control-Allow-Origin' not in h
    assert server.sessions=={} and runtime.jobs==[]


def test_session_expiry_and_no_auth_analysis(service):
    server,runtime,call=service
    assert call('/analyze',JOB)[0]==401
    assert call('/session',{'client':'other'})[0]==400
    status,h,session=call('/session',{'client':'aquaphotomics-workbench'})
    assert status==200 and h['Cache-Control']=='no-store'
    token=session['token']; assert len(token)>=32
    headers={'Authorization':'Bearer '+token}
    assert call('/analyze',JOB,headers)[0]==200
    assert runtime.jobs[0]['ids']==['001','002','003']
    server.sessions[token]=time.monotonic()-1
    assert call('/analyze',JOB,headers)[0]==401


@pytest.mark.parametrize('change',[
    {'matrix':[[1,2,3]]}, {'matrix':[[1,2],[1,2],[1,2]]}, {'wavelengths':[1400,1300,1500]},
    {'ids':['x','x','z']}, {'groups':['A']}, {'pca':{'components':1,'scale':True}},
    {'aquagram':{'wavelengths':[1300,1400,1500],'reference':'none'}},
    {'aquagram':{'wavelengths':[1300,1400,1499],'reference':'global'}},
])
def test_unsupported_inputs_fail_before_runtime(change):
    with pytest.raises(bridge.InputError): bridge.validate_job({**copy.deepcopy(JOB),**change})


def test_untrusted_code_paths_and_unknown_settings_are_never_forwarded(service):
    _,runtime,call=service
    _,_,session=call('/session',{'client':'aquaphotomics-workbench'})
    job={**JOB,'rscript':'evil.R','code':'system("bad")','output':'outside','pca':{**JOB['pca'],'extra':'ignored'}}
    assert call('/analyze',job,{'Authorization':'Bearer '+session['token']})[0]==200
    assert runtime.jobs[0]==JOB


def test_non_finite_values_and_body_limit():
    job=copy.deepcopy(JOB);job['matrix'][0][0]=float('nan')
    with pytest.raises(bridge.InputError):bridge.validate_job(job)
    job=copy.deepcopy(JOB);job['matrix'][0][0]=True
    with pytest.raises(bridge.InputError):bridge.validate_job(job)


def test_wrong_content_type_and_unknown_routes(service):
    _,_,call=service
    assert call('/session',{'client':'aquaphotomics-workbench'},{'Content-Type':'text/plain'})[0]==400
    assert call('/file')[0]==404
    assert call('/install',{})[0]==404


def test_r_health_contract_and_http_evidence_is_never_enabled(monkeypatch, tmp_path):
    import subprocess
    package = {'engine':'aquap2','aquap2Version':'0.4.5','rVersion':'R test',
               'api':'aquap2::gdmm','installedPackage':True}
    monkeypatch.setenv('AQUAP2_KEEP_EVIDENCE','1')
    runtime = bridge.Runtime('Rscript', tmp_path / 'library')
    assert 'AQUAP2_KEEP_EVIDENCE' not in runtime.env()
    monkeypatch.setattr(bridge.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a,0,json.dumps({'ok':True,'runtime':package}).encode(),b''))
    assert runtime.health()['aquap2Version']=='0.4.5'
    runtime._health=None
    package['installedPackage']=False
    with pytest.raises(RuntimeError): runtime.health()

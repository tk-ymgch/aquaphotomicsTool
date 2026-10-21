"""Loopback-only aquap2 bridge. Never accepts R code, file paths or install commands."""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 8 * 1024 * 1024
SESSION_SECONDS = 30 * 60
ORIGINS = frozenset({
    'https://aquaphotomics-workbench.tkymgch.chatgpt.site',
    'http://127.0.0.1:4173', 'http://127.0.0.1:4174', 'http://127.0.0.1:5173',
})


class InputError(ValueError):
    pass


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{name}の範囲を確認してください。')
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_job(value):
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        raise InputError('解析要求の形式を確認してください。')
    matrix = value.get('matrix')
    if not isinstance(matrix, list):
        raise InputError('前処理後の数値行列が必要です。')
    n = integer(len(matrix), 3, 500, '試料数')
    waves = value.get('wavelengths')
    if not isinstance(waves, list):
        raise InputError('波長が必要です。')
    p = integer(len(waves), 3, 2000, '波長数')
    if n * p > 100_000:
        raise InputError('aquap2接続は10万行列要素までです。')
    if not all(finite(w) and w > 0 for w in waves) or any(b <= a for a, b in zip(waves, waves[1:])):
        raise InputError('波長は重複のない昇順の正数にしてください。')
    if any(not isinstance(row, list) or len(row) != p or not all(finite(x) for x in row) for row in matrix):
        raise InputError('数値行列は有限値だけを含む長方形にしてください。')
    for key in ('ids', 'groups'):
        labels = value.get(key)
        if not isinstance(labels, list) or len(labels) != n or any(not isinstance(x, str) or not x or len(x) > 4096 or '\x00' in x for x in labels):
            raise InputError('試料IDと群名の形式を確認してください。')
    if len(set(value['ids'])) != n:
        raise InputError('試料IDは重複しない値にしてください。')
    aq, pca = value.get('aquagram'), value.get('pca')
    if not isinstance(aq, dict) or not isinstance(pca, dict):
        raise InputError('PCAとAquagramの条件を指定してください。')
    targets = aq.get('wavelengths')
    if not isinstance(targets, list) or not 3 <= len(targets) <= min(24, p) or any(not finite(w) or w not in waves for w in targets) or len(set(targets)) != len(targets):
        raise InputError('aquap2には実際に測定した重複のない3〜24波長を渡してください。')
    reference = aq.get('reference')
    if not isinstance(reference, str) or (reference != 'global' and (not reference.startswith('group:') or reference[6:] not in value['groups'])):
        raise InputError('aquap2接続は全体平均または指定対照群のclassicに対応します。')
    components = integer(pca.get('components'), 1, min(10, n - 1, p), 'PCA成分数')
    if pca.get('scale') is not False:
        raise InputError('aquap2接続のPCAは平均中心化のみです。波長ごとの標準化を解除してください。')
    # Strip all undeclared input. Nothing from an HTTP request becomes code or a path.
    return {'schemaVersion': 1, 'matrix': matrix, 'wavelengths': waves,
            'ids': value['ids'], 'groups': value['groups'],
            'aquagram': {'wavelengths': targets, 'reference': reference},
            'pca': {'components': components, 'scale': False}}


class Runtime:
    def __init__(self, rscript, library, helper=None):
        self.rscript = rscript
        self.library = str(Path(library).resolve())
        self.helper = str(Path(helper or ROOT / 'scripts/aquap2_engine.R').resolve())
        self.lock = threading.Lock()
        self._health = None
        self._checked = 0.0

    def env(self):
        env = os.environ.copy()
        env['AQUAP2_LIBRARY'] = self.library
        env['AQUAP2_RUNTIME_ROOT'] = str(Path(self.library).parent)
        env.pop('AQUAP2_KEEP_EVIDENCE', None)  # HTTP input is temporary, even in a QA shell.
        isolated_home = Path(self.library).parent / 'home'
        isolated_home.mkdir(parents=True, exist_ok=True)
        env['R_USER'] = str(isolated_home)
        executable = Path(shutil.which(self.rscript) or self.rscript).resolve()
        if executable.parent.name.lower() == 'bin':
            env['R_HOME'] = str(executable.parent.parent)
        for key in list(env):
            if key == 'LANG' or key.startswith('LC_'):
                env.pop(key, None)
        return env

    def health(self):
        if self._health and time.monotonic() - self._checked < 60:
            return self._health
        run = subprocess.run([self.rscript, '--vanilla', self.helper, '--health'],
                             env=self.env(), capture_output=True, timeout=45, check=False)
        if run.returncode:
            raise RuntimeError('aquap2実行環境を確認できません。セットアップとR libraryを確認してください。')
        try:
            value = json.loads(run.stdout.decode('utf-8-sig'))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError('R環境の応答形式を確認できません。') from exc
        runtime = value.get('runtime', {})
        if value.get('ok') is not True or runtime.get('engine') != 'aquap2' or not runtime.get('aquap2Version') or runtime.get('installedPackage') is not True or runtime.get('api') != 'aquap2::gdmm':
            raise RuntimeError('aquap2パッケージを読み込めません。')
        self._health = {key: runtime[key] for key in ('engine', 'aquap2Version', 'rVersion', 'api') if key in runtime}
        self._health.update({'schemaVersion': 1, 'available': True,
            'capabilities': {'pca': True, 'classic': True, 'classicDiff': True,
                             'pls': False, 'temperatureCalibration': False}})
        self._checked = time.monotonic()
        return self._health

    def analyze(self, job):
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('別のR解析を実行中です。完了後に再実行してください。')
        try:
            with tempfile.TemporaryDirectory(prefix='aquap2-job-') as temporary:
                folder = Path(temporary)
                source, destination = folder / 'input.json', folder / 'output.json'
                source.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding='utf-8')
                run = subprocess.run([self.rscript, '--vanilla', self.helper, str(source), str(destination)],
                                     cwd=folder, env=self.env(), capture_output=True, timeout=180, check=False)
                if run.returncode or not destination.is_file():
                    raise RuntimeError('aquap2の解析に失敗しました。対応する計算条件と接続先のR環境を確認してください。')
                if destination.stat().st_size > 16 * 1024 * 1024:
                    raise RuntimeError('Rからの応答が大きすぎます。')
                result = json.loads(destination.read_text(encoding='utf-8-sig'))
                runtime = result.get('runtime', {})
                if runtime.get('engine') != 'aquap2' or runtime.get('packageApiExecuted') is not True or runtime.get('api') != 'aquap2::gdmm':
                    raise RuntimeError('aquap2本体の実行記録を確認できません。')
                # Reject NaN/Infinity and never expose stdout/stderr or temporary paths.
                json.dumps(result, allow_nan=False)
                return result
        finally:
            self.lock.release()


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, runtime, origins=ORIGINS):
        if address[0] != '127.0.0.1':
            raise ValueError('The bridge binds only to 127.0.0.1')
        self.runtime, self.origins = runtime, frozenset(origins)
        self.sessions = {}
        self.session_lock = threading.Lock()
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'AquaphotomicsBridge/1'
    protocol_version = 'HTTP/1.0'

    def log_message(self, *_):
        pass  # Request bodies, IDs, paths and bearer values are never logged.

    def reply(self, status, value=None):
        data = b'' if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        origin = self.headers.get('Origin')
        if origin in self.server.origins:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Aquaphotomics-Client')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def permitted(self, preflight=False):
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in expected or self.headers.get('Origin') not in self.server.origins:
            self.reply(403, {'error': 'この接続元は許可されていません。'})
            return False
        if not preflight and self.headers.get('X-Aquaphotomics-Client') != '1':
            self.reply(403, {'error': 'Workbenchの接続テストから接続してください。'})
            return False
        return True

    def do_OPTIONS(self):
        if self.permitted(preflight=True):
            requested = {x.strip().lower() for x in self.headers.get('Access-Control-Request-Headers', '').split(',') if x.strip()}
            if self.headers.get('Access-Control-Request-Method') not in {'GET', 'POST'} or not requested <= {'content-type', 'authorization', 'x-aquaphotomics-client'}:
                self.reply(403, {'error': '許可されていないリクエストです。'})
            else:
                self.reply(204)

    def do_GET(self):
        if not self.permitted():
            return
        if self.path != '/health':
            return self.reply(404, {'error': 'Not found'})
        try:
            self.reply(200, self.server.runtime.health())
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            self.reply(503, {'error': 'R/aquap2環境を確認できません。ローカルサービスの設定を確認してください。'})

    def read_json(self):
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise InputError('application/jsonで送信してください。')
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError as exc:
            raise InputError('要求のサイズを確認してください。') from exc
        if not 0 <= length <= MAX_BODY:
            raise InputError('送信データは8 MiB以下にしてください。')
        self.connection.settimeout(15)
        return json.loads(self.rfile.read(length).decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(InputError('有限値が必要です。')))

    def authenticated(self):
        token = self.headers.get('Authorization', '')
        now = time.monotonic()
        with self.server.session_lock:
            self.server.sessions = {key: expiry for key, expiry in self.server.sessions.items() if expiry > now}
            return any(hmac.compare_digest(token, 'Bearer ' + key) for key in self.server.sessions)

    def do_POST(self):
        if not self.permitted():
            return
        try:
            if self.path == '/session':
                if self.read_json() != {'client': 'aquaphotomics-workbench'}:
                    raise InputError('接続要求の形式を確認してください。')
                self.server.runtime.health()
                token = secrets.token_urlsafe(32)
                with self.server.session_lock:
                    now = time.monotonic()
                    self.server.sessions = {key: expiry for key, expiry in self.server.sessions.items() if expiry > now}
                    if len(self.server.sessions) >= 32:
                        return self.reply(429, {'error': '接続数が上限に達しました。時間をおいて再接続してください。'})
                    self.server.sessions[token] = now + SESSION_SECONDS
                return self.reply(200, {'token': token, 'expiresIn': SESSION_SECONDS})
            if self.path != '/analyze':
                return self.reply(404, {'error': 'Not found'})
            if not self.authenticated():
                return self.reply(401, {'error': 'R接続の有効期限が切れました。接続テストから再接続してください。'})
            result = self.server.runtime.analyze(validate_job(self.read_json()))
            self.reply(200, result)
        except InputError as exc:
            self.reply(400, {'error': str(exc)[:500]})
        except (ValueError, UnicodeError):
            self.reply(400, {'error': '数値行列と対応する解析条件を確認してください。'})
        except BlockingIOError:
            self.reply(409, {'error': 'Rで別の解析を実行中です。完了後に再実行してください。'})
        except subprocess.TimeoutExpired:
            self.reply(504, {'error': 'R解析が3分を超えたため停止しました。データを小さくしてください。'})
        except (RuntimeError, OSError):
            self.reply(503, {'error': 'aquap2解析を実行できませんでした。ローカルR環境と設定を確認してください。'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--rscript', default=shutil.which('Rscript') or 'Rscript')
    parser.add_argument('--library', default=os.environ.get('AQUAP2_LIBRARY', str(ROOT / 'qa/aquap2-runtime-v1.4/library')))
    args = parser.parse_args()
    server = BridgeServer(('127.0.0.1', args.port), Runtime(args.rscript, args.library))
    print(f'Aquaphotomics R bridge: http://127.0.0.1:{server.server_port} (loopback only)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

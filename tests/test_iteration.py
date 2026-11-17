"""Confirmed user decision matrix, not fabricated YouTrack acceptance IDs. No paid calls."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import app as module
import config
from core import Store
from providers import ProviderError, Providers
from test_acceptance import completed, upload, wav

ROOT = Path(__file__).resolve().parents[1]


def isolated(tmp_path, yaml_text='models: {}\nlimits: {}\n', dotenv='', env=None, code=None):
    for name in ('config.py', 'providers.py'):
        shutil.copyfile(ROOT / name, tmp_path / name)
    (tmp_path / 'service.yaml').write_text(yaml_text)
    # Synthetic test-only file, never the real project .env or any existing secret.
    (tmp_path / '.env').write_text(dotenv)
    return subprocess.run([sys.executable, '-c', code or
        'import config,json; print(json.dumps(config.CONFIG))'], cwd=tmp_path,
        env={'PATH': os.defpath, **(env or {})}, text=True, capture_output=True)


def test_dotenv_loaded_before_configuration_and_shell_wins(tmp_path):
    result = isolated(tmp_path, dotenv='FLF_MAX_JOBS=7\nFLF_MAX_QUEUE=5\nCLOVASTUDIO_MODEL=HCX-SHARED\n')
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data['limits']['max_jobs'] == 7 and data['models']['chat'] == 'HCX-SHARED'
    result = isolated(tmp_path, dotenv='FLF_MAX_JOBS=7\nFLF_MAX_QUEUE=5\n', env={'FLF_MAX_JOBS': '9'})
    assert json.loads(result.stdout)['limits']['max_jobs'] == 9


def test_distinct_yaml_models_override_shared_env(tmp_path):
    result = isolated(tmp_path, 'models: {summary: HCX-SUM, chat: HCX-CHAT}\nlimits: {}',
                      dotenv='CLOVASTUDIO_MODEL=HCX-SHARED\n')
    assert json.loads(result.stdout)['models'] == {'summary':'HCX-SUM', 'chat':'HCX-CHAT'}
    result = isolated(tmp_path, 'models: {summary: null, chat: HCX-CHAT}\nlimits: {}',
                      env={'CLOVASTUDIO_MODEL':'HCX-FALLBACK'})
    assert json.loads(result.stdout)['models']['summary'] == 'HCX-FALLBACK'


@pytest.mark.parametrize('name', list(config.LIMITS))
def test_every_limit_yaml_and_environment_is_connected(tmp_path, monkeypatch, name):
    env_name, default = config.LIMITS[name]
    monkeypatch.delenv(env_name, raising=False)
    value = default + 1
    path = tmp_path / 'service.yaml'
    extra = ', speech_wait_seconds: 8000' if name == 'max_seconds' else ''
    path.write_text(f'models: {{}}\nlimits: {{{name}: {value}{extra}}}')
    assert config.load_config(path)['limits'][name] == value
    monkeypatch.setenv(env_name, str(value + 1))
    loaded = config.load_config(path)
    assert loaded['limits'][name] == value + 1
    monkeypatch.setattr(config, 'CONFIG', loaded)
    assert config.limit(name) == value + 1


@pytest.mark.parametrize('text', [
    'models: [bad]', 'models: {chat: false}', 'models: {chat: ../secret-value}',
    'limits: {unknown: 1}', 'limits: {max_jobs: 0}', 'limits: {max_jobs: true}',
    'limits: {max_jobs: 1.2}', 'limits: {lease_seconds: 50, heartbeat_seconds: 30}',
    'limits: {max_db_bytes: 1}', 'secret: never-print-this', 'models: ['])
def test_invalid_yaml_fails_without_values(tmp_path, text):
    result = isolated(tmp_path, text)
    assert result.returncode != 0
    assert 'never-print-this' not in result.stderr and 'secret-value' not in result.stderr


def test_live_missing_secrets_reports_names_only(tmp_path):
    result = isolated(tmp_path, dotenv='CLOVA_SPEECH_SECRET_KEY=test-only-private-value\n', # pragma: allowlist secret -- synthetic fixture, not a credential
                      code="from providers import Providers; Providers('live')")
    assert result.returncode != 0
    assert 'CLOVA_SPEECH_INVOKE_URL' in result.stderr
    assert 'test-only-private-value' not in result.stderr


def test_live_uses_only_canonical_names_and_validates_endpoints(monkeypatch):
    for name in config.REQUIRED:
        monkeypatch.setenv(name, 'fake-only')
    monkeypatch.setenv('CLOVA_SPEECH_INVOKE_URL', 'https://speech.invalid/domain')
    monkeypatch.setenv('NCLOUD_OBJECT_STORAGE_ENDPOINT', 'https://storage.invalid')
    monkeypatch.setenv('NCLOUD_OBJECT_STORAGE_INPUT_PREFIX', 'flf/input')
    monkeypatch.setenv('NCLOUD_OBJECT_STORAGE_OUTPUT_PREFIX', 'flf/output')
    monkeypatch.setenv('FLF_PUBLIC_BASE_URL', 'https://callback.invalid')
    assert Providers('live').mode == 'live'
    monkeypatch.setenv('NCLOUD_OBJECT_STORAGE_ENDPOINT', 'http://private-value.invalid')
    with pytest.raises(ValueError, match='NCLOUD_OBJECT_STORAGE_ENDPOINT') as error:
        Providers('live')
    assert 'private-value' not in str(error.value)


def test_model_specific_outbound_urls(monkeypatch):
    monkeypatch.setenv('CLOVASTUDIO_API_KEY', 'fake-only')
    monkeypatch.setitem(config.CONFIG, 'models', {'summary':'HCX-SUM', 'chat':'HCX-CHAT'})
    p = Providers('demo'); p.mode = 'live'; urls = []
    def request(method, url, **kw):
        urls.append(url)
        return {'status':{'code':'20000'}, 'result':{'finishReason':'stop', 'message':{'content':'answer'}}}
    monkeypatch.setattr(p, 'request', request)
    p.studio('summarize', {'source':'lecture'})
    p.studio('answer', {'question':'question', 'summary':'lecture summary'})
    assert urls[0].endswith('/HCX-SUM') and urls[1].endswith('/HCX-CHAT')


def test_upload_request_id_independent_new_uploads_and_replay_after_end(client):
    args = dict(files={'audio':('lecture.wav', wav())}, data={'consent':'true'},
                headers={'X-FLF-Upload-ID':'upload-intent-000001'})
    a = client.post('/api/jobs', **args).json()
    assert client.post('/api/jobs', **args).json()['id'] == a['id']
    assert upload(client).json()['id'] != a['id']
    changed = {**args, 'files':{'audio':('lecture.wav', wav()+b'\0\0')}}
    assert client.post('/api/jobs', **changed).status_code == 400
    assert client.post('/api/jobs/'+a['id']+'/end').status_code == 200
    assert client.post('/api/jobs', **args).status_code == 400


def expire(job_id):
    with module.store.connect() as c:
        c.execute("UPDATE jobs SET payload=json_set(payload,'$.leaseUntil',?) WHERE id=?", (time.time()-1, job_id))


def test_cookie_lease_refresh_restart_and_shared_tabs(client, monkeypatch):
    response = client.get('/api/session')
    assert 'max-age' not in response.headers.get('set-cookie', '').lower()
    j = upload(client).json(); url = '/api/jobs/'+j['id']
    before = module.store.get(j['id'])['leaseUntil']
    client.get('/api/session'); client.get(url)
    assert module.store.get(j['id'])['leaseUntil'] == before
    monkeypatch.setattr(module, 'store', Store(module.store.root))
    assert client.get(url).status_code == 200
    assert client.post(url+'/heartbeat').status_code == 200
    assert module.store.get(j['id'])['leaseUntil'] >= before
    # A second tab uses the same cookie; explicit end invalidates BOTH tabs.
    same_cookie = dict(client.cookies)
    assert client.post(url+'/end').json()['ended']
    client.cookies.update(same_cookie)
    assert client.get(url).status_code in (404, 410)
    assert client.post(url+'/heartbeat').status_code in (404, 410)


def test_expired_session_cannot_renew_and_caches_deleted(client):
    j = completed(client); url = '/api/jobs/'+j['id']
    client.post(url+'/chat', json={'text':'에너지', 'requestId':'expiry-chat-00001'})
    path = Path(module.store.get(j['id'])['path'])
    expire(j['id'])
    assert client.post(url+'/heartbeat').status_code in (404,410)
    deadline = time.time()+3
    while module.store.get(j['id']) and time.time()<deadline:
        time.sleep(.05)
    assert not module.store.get(j['id']) and not path.exists()
    with module.store.connect() as c:
        for table in ('jobs', 'calls', 'chat_requests', 'deletions'):
            assert c.execute('SELECT count(*) FROM '+table).fetchone()[0] == 0


def test_end_during_paid_chat_hides_and_clears_immediately(client, monkeypatch):
    j = completed(client); url = '/api/jobs/'+j['id']; internal = module.store.get(j['id'])
    internal['mode'] = 'live'; module.store.save(internal)
    monkeypatch.setattr(module.provider, 'mode', 'live')
    entered, release = threading.Event(), threading.Event()
    def studio(*args):
        entered.set(); assert release.wait(5); return 'private-answer'
    monkeypatch.setattr(module.provider, 'studio', studio)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, url+'/chat', json={'text':'에너지', 'requestId':'end-chat-0000001'})
        assert entered.wait(3)
        try:
            assert client.post(url+'/end').status_code == 202
            assert client.get(url).status_code == 410
            tombstone = module.store.get(j['id'])
            assert all(key not in tombstone for key in ('transcript','summary','translation','history','token'))
            assert not Path(internal['path']).exists()
            with module.store.connect() as c:
                assert c.execute('SELECT count(*) FROM calls').fetchone()[0] == 0
                assert c.execute('SELECT count(*) FROM chat_requests').fetchone()[0] == 0
        finally:
            release.set()
        assert future.result().status_code in (404,410)


def test_object_storage_legacy_cleanup_and_no_private_error(monkeypatch, caplog):
    p = Providers('demo'); recorded = []
    job = {'id':'test-id', 'objects':{'bucket':'fake-bucket', 'endpoint':'https://storage.invalid',
            'input':'flf/input/test-id/audio', 'output':'flf/output/test-id/result.json'}}
    class Storage:
        def delete_object(self, **kwargs): recorded.append(('delete', kwargs))
        def get_paginator(self, name): return self
        def paginate(self, **kwargs):
            return [{'Versions':[{'Key':kwargs['Prefix'], 'VersionId':'v1'},
                                 {'Key':kwargs['Prefix']+'-other', 'VersionId':'must-not-delete'}]}]
    monkeypatch.setattr(p, 'storage', lambda endpoint=None: Storage())
    p.cleanup(job)
    assert not [r for r in recorded if r[0]=='put']
    deletes = [r[1] for r in recorded if r[0]=='delete']
    assert len(deletes) == 4 and all('must-not-delete' != r.get('VersionId') for r in deletes)
    def denied(*args, **kw): raise RuntimeError('private credential must never appear')
    monkeypatch.setattr(p, 'storage', denied)
    with pytest.raises(ProviderError) as e: p.cleanup(job)
    assert e.value.code == 'OBJECT_STORAGE_DELETE_PENDING'
    assert 'private credential' not in caplog.text and 'private credential' not in str(e.value)


def test_external_delete_failure_is_durable_and_restart_recovers(client, monkeypatch):
    j = upload(client).json(); internal = module.store.get(j['id'])
    internal['objects'] = {'bucket':'fake-bucket', 'endpoint':'https://storage.invalid',
                           'input':'flf/input/id/audio', 'output':'flf/output/id/result.json'}
    module.store.save(internal)
    def denied(job): raise ProviderError('OBJECT_STORAGE_DELETE_PENDING')
    monkeypatch.setattr(module.provider, 'cleanup', denied)
    assert client.post('/api/jobs/'+j['id']+'/end').status_code == 202
    assert module.store.get(j['id'])['deleting']
    assert not Path(internal['path']).exists()
    monkeypatch.setattr(module, 'store', Store(module.store.root))
    deleted = []
    monkeypatch.setattr(module.provider, 'cleanup', lambda job: deleted.append(job['objects']))
    # Advance persisted cleanup retry schedule without sleeping through backoff.
    with module.store.connect() as c:
        c.execute("UPDATE jobs SET payload=json_set(payload,'$.cleanupAfter',0) WHERE id=?", (j['id'],))
    deadline = time.time()+3
    while module.store.get(j['id']) and time.time()<deadline: time.sleep(.05)
    assert deleted == [internal['objects']] and module.store.get(j['id']) is None


def test_reaper_expires_local_state_while_provider_is_blocked(client, monkeypatch):
    j = completed(client); internal = module.store.get(j['id']); url = '/api/jobs/'+j['id']
    internal['mode'] = 'live'; module.store.save(internal)
    monkeypatch.setattr(module.provider, 'mode', 'live')
    entered, release = threading.Event(), threading.Event()
    def studio(*args):
        entered.set(); assert release.wait(5); return 'answer'
    monkeypatch.setattr(module.provider, 'studio', studio)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, url+'/chat', json={'text':'에너지','requestId':'reaper-chat-00001'})
        assert entered.wait(3)
        try:
            expire(j['id'])
            deadline = time.time()+2
            while Path(internal['path']).exists() and time.time()<deadline: time.sleep(.05)
            assert not Path(internal['path']).exists()
            assert module.store.get(j['id'])['deleting']
            assert client.get(url).status_code == 410
        finally:
            release.set()
        assert future.result().status_code == 410


def test_legacy_data_preserved_not_auto_run_until_adopted(client):
    j = upload(client).json()
    with module.store.connect() as c:
        c.execute("UPDATE jobs SET payload=json_remove(payload,'$.leaseUntil') WHERE id=?", (j['id'],))
    module.worker_tick()
    assert module.store.get(j['id']) and Path(module.store.get(j['id'])['path']).exists()
    assert client.post('/api/jobs/'+j['id']+'/heartbeat').status_code == 410
    assert client.post('/api/jobs/'+j['id']+'/adopt').status_code == 200
    assert module.store.get(j['id'])['leaseUntil'] > time.time()


def test_configurable_call_and_chat_caps_are_enforced(client, monkeypatch):
    j = completed(client); internal = module.store.get(j['id'])
    monkeypatch.setenv('FLF_MAX_CALLS', '1')
    with pytest.raises(ProviderError, match='JOB_CALL_CAP'):
        module.store.call(internal, 'new-call', lambda: 'must-not-run')
    monkeypatch.setenv('FLF_MAX_CHAT_REQUESTS', '1')
    url = '/api/jobs/'+j['id']+'/chat'
    assert client.post(url, json={'text':'에너지','requestId':'cap-chat-00000001'}).status_code == 200
    assert client.post(url, json={'text':'에너지','requestId':'cap-chat-00000002'}).status_code == 429


def test_stage_no_redundant_storage_copies_or_paid_resubmission(tmp_path, monkeypatch):
    s = Store(tmp_path); path = tmp_path/'audio.wav'; path.write_bytes(wav())
    j = s.create('owner', 'digest', 'demo', path)
    j['objects'] = {'bucket':'fake-bucket', 'input':'flf/input/id/audio', 'output':'flf/output/id/result.json'}
    s.save(j); p = Providers('demo'); puts=[]; submissions=[]
    monkeypatch.setattr(p, 'storage', lambda *a: pytest.fail('must not retain separate OBS copies'))
    original = p.submit
    monkeypatch.setattr(p, 'submit', lambda path: submissions.append(path) or original(path))
    s.run(j, p)
    assert j['state'] == 'COMPLETED' and puts == [] and len(submissions) == 1
    recovered = Store(tmp_path); recovered.run(recovered.get(j['id']), p)
    assert len(submissions) == 1


def test_secure_session_cookie_host_and_no_store_contract(client, monkeypatch):
    client.cookies.clear(); monkeypatch.setenv('FLF_SECURE_COOKIE','1')
    response = client.get('/api/session')
    cookie = response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
    assert 'max-age' not in cookie and 'expires=' not in cookie
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/session', headers={'Host':'attacker.invalid'}).status_code == 400


def test_deployment_static_contract_and_documented_variables():
    nginx = (ROOT/'deploy/nginx.conf.example').read_text()
    assert 'listen 10000;' in nginx and 'listen 443 ssl;' in nginx
    assert '308 https://101.79.23.235$request_uri' in nginx
    assert 'proxy_pass http://127.0.0.1:10001' in nginx
    assert '222.108.72.113/32' in (ROOT/'deploy/access-evaluator.conf.example').read_text()
    service = (ROOT/'deploy/flf.service.example').read_text()
    for required in ('User=flf', 'Restart=on-failure', '--port 10001', '--forwarded-allow-ips 127.0.0.1', 'FLF_SECURE_COOKIE=1'):
        assert required in service
    readme = (ROOT/'README.md').read_text()
    for name in config.REQUIRED + ('CLOVASTUDIO_MODEL',):
        assert name in readme
    for name, (env_name, _) in config.LIMITS.items():
        assert env_name in readme and name in (ROOT/'service.yaml').read_text()


def publication_paths():
    # Metadata only: never open actual .env, ignored data, credentials, or media.
    result = subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],
                            cwd=ROOT, check=True, capture_output=True)
    return [name for name in result.stdout.decode().split('\0') if name]


def test_publication_excludes_environment_templates_and_runtime_material():
    # Requirement explicitly withdrawn, not fulfilled via an alternative template path.
    forbidden = re.compile(r'^(?:\.?env[._-](?:example|sample|template)|'
                           r'environment[._-](?:example|sample|template))(?:\..*)?$', re.I)
    for path in publication_paths():
        name = Path(path).name
        assert not forbidden.fullmatch(name), path
        assert name != '.env', 'actual .env must never be a publication candidate'
        assert not set(Path(path).parts) & {'data','.venv','__pycache__','.pytest_cache'}
        assert Path(path).suffix.lower() not in {'.sqlite3','.db','.log','.key','.pem'}


def test_actual_env_is_git_ignored_without_reading_it():
    result = subprocess.run(['git','check-ignore','--no-index','--quiet','.env'], cwd=ROOT)
    assert result.returncode == 0
    assert '.env' not in publication_paths()


def test_readme_manual_environment_contract_without_copyable_template():
    text = (ROOT/'README.md').read_text()
    for key in config.REQUIRED + ('CLOVASTUDIO_MODEL','FLF_MODE','FLF_DATA','FLF_CONFIG',
                                 'FLF_ALLOWED_HOSTS','FLF_SECURE_COOKIE','FLF_TRANSLATION_LABEL',
                                 'FLF_PUBLIC_BASE_URL','TMPDIR'):
        assert '`'+key+'`' in text
    assert '직접 준비' in text and '0600' in text and 'python-dotenv' in text
    assert '셸/프로세스 환경 > `.env`' in text
    assert '역할별 YAML 모델 > 공통 환경 fallback' in text
    assert '환경 변수 > YAML > 코드 기본값' in text
    assert '현재 live 시작 검증은 OBS 변수도 모두 필수로 검사' in text
    assert 'FLF_MODE=demo .venv/bin/uvicorn' in text
    assert 'FLF_MODE=live .venv/bin/uvicorn' in text
    for block in re.findall(r'```[^\n]*\n(.*?)```', text, re.S):
        assert not re.search(r'^\s*cp\b.*(?:\.env|environment[_-])', block, re.M)
        # Normal launch commands are allowed; standalone env assignments are not a substitute template.
        assert not re.search(r'^\s*(?:export\s+)?(?:FLF_|CLOVA|PAPAGO_|NCLOUD_|TMPDIR\b)'
                             r'[A-Z0-9_]*=[^\s]*\s*$', block, re.M)

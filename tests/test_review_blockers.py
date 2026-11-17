"""Reviewer/PM blocker regressions. All provider I/O is mocked; no live calls."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx
import pytest
import app as module
import config
from core import Store
from providers import ProviderError, Providers
from test_acceptance import completed, upload, wav
from test_iteration import expire, isolated

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=4):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError('condition timed out')


def test_subprocess_crash_prejob_file_reconciled_at_actual_startup(tmp_path):
    env = {'PATH':os.defpath, 'FLF_MODE':'demo', 'FLF_DATA':str(tmp_path),
           'FLF_CONFIG':str(ROOT/'service.yaml')}
    crash = '''import io,os
from types import SimpleNamespace
from starlette.datastructures import UploadFile
import app
app.validate_audio=lambda *args: os._exit(73)
app.save_upload(SimpleNamespace(cookies={'flf_session':'a'*64},headers={}),
    UploadFile(file=io.BytesIO(b'test-only-staged-media'),filename='lecture.wav'),True)
'''
    result = subprocess.run([sys.executable, '-c', crash], cwd=ROOT, env=env, capture_output=True)
    assert result.returncode == 73
    s = Store(tmp_path)
    with s.connect() as c:
        rows = c.execute('SELECT path FROM upload_staging').fetchall()
        assert len(rows) == 1 and c.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    orphan = Path(rows[0][0]); assert orphan.exists()
    valid = tmp_path/'valid.wav'; valid.write_bytes(wav())
    kept = s.create('owner','digest','demo',valid)
    legacy = tmp_path/'unregistered-legacy.wav'; legacy.write_bytes(b'preserve-existing-data')
    restart = '''from fastapi.testclient import TestClient
import app
with TestClient(app.app) as client:
    with app.store.connect() as c:
        assert c.execute('SELECT count(*) FROM upload_staging').fetchone()[0]==0
'''
    result = subprocess.run([sys.executable, '-c', restart], cwd=ROOT, env=env, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert not orphan.exists() and valid.exists() and legacy.exists() and s.get(kept['id'])


def test_runtime_staging_reconciliation_never_unlinks_active_validator(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = module.validate_audio
    def validate(*args):
        entered.set(); assert release.wait(5); return real(*args)
    monkeypatch.setattr(module, 'validate_audio', validate)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(upload, client)
        assert entered.wait(3)
        try:
            with module.mutex:
                paths = set(module.active_staging)
                module.store.reconcile_staging(module.active_staging)
            assert paths and all(Path(path).exists() for path in paths)
            assert sum(module.upload_reservations.values()) == 1
        finally:
            release.set()
        j = future.result().json()
    assert Path(module.store.get(j['id'])['path']).exists()
    with module.store.connect() as c:
        assert c.execute('SELECT count(*) FROM upload_staging').fetchone()[0] == 0


def test_expired_b_external_cleanup_completes_while_a_stt_is_blocked(client, monkeypatch):
    a = upload(client).json(); entered, release = threading.Event(), threading.Event()
    poll = module.provider.poll
    def blocked(token):
        entered.set(); assert release.wait(7); return poll(token)
    monkeypatch.setattr(module.provider, 'poll', blocked)
    client.post('/api/jobs/'+a['id']+'/submit'); assert entered.wait(3)
    try:
        b = upload(client).json(); internal = module.store.get(b['id'])
        internal['objects'] = {'bucket':'mock-bucket','input':'flf/input/B/audio','output':'flf/output/B/result.json'}
        module.store.save(internal)
        external = {internal['objects']['input'], internal['objects']['output']}
        def cleanup(job):
            if job.get('objects'):
                external.discard(job['objects']['input']); external.discard(job['objects']['output'])
        monkeypatch.setattr(module.provider, 'cleanup', cleanup)
        expire(b['id'])
        wait_for(lambda: module.store.get(b['id']) is None)
        assert not external and not Path(internal['path']).exists()
        assert not release.is_set() and module.store.get(a['id'])['state'] == 'STT_RUNNING'
    finally:
        release.set()


def test_end_during_legacy_put_is_fenced_until_late_write_then_cleanup(client, monkeypatch):
    b = upload(client).json(); internal = module.store.get(b['id'])
    internal['objects'] = {'bucket':'mock-bucket','input':'flf/input/B/audio','output':'flf/output/B/result.json'}
    module.store.save(internal)
    entered, release = threading.Event(), threading.Event(); external=set()
    real = module.store.run
    def run(job, provider, stop):
        if job['id'] != b['id']:
            return real(job, provider, stop)
        # Inject an already-in-flight historical PUT at the guarded provider boundary.
        # New production jobs no longer issue these redundant PUTs.
        entered.set(); assert release.wait(5)
        external.add(job['objects']['input'])
        job['summary'] = 'must-not-resurrect'; module.store.save(job)
    monkeypatch.setattr(module.store, 'run', run)
    def cleanup(job):
        external.discard(job['objects']['input']); external.discard(job['objects']['output'])
    monkeypatch.setattr(module.provider, 'cleanup', cleanup)
    client.post('/api/jobs/'+b['id']+'/submit'); assert entered.wait(3)
    try:
        result = client.post('/api/jobs/'+b['id']+'/end')
        assert result.status_code == 202 and module.store.get(b['id'])['deleting']
        assert not Path(internal['path']).exists()
        module.cleanup_tick()
        assert module.store.get(b['id']) is not None, 'cannot finalize before in-flight PUT finishes'
    finally:
        release.set()
    wait_for(lambda: module.store.get(b['id']) is None)
    assert not external and client.get('/api/jobs/'+b['id']).status_code == 404


def callback_job(client, monkeypatch, submit=None):
    p = module.provider; demo = Providers('demo'); captured=[]
    monkeypatch.setattr(p, 'mode', 'live')
    def accepted(path, callback_url=None):
        captured.append(callback_url); return 'provider-token'
    monkeypatch.setattr(p, 'submit', submit or accepted)
    monkeypatch.setattr(p, 'translate', demo.translate)
    monkeypatch.setattr(p, 'studio', demo.studio)
    monkeypatch.setattr(p, 'poll', lambda *a: pytest.fail('new live job must receive callback, not poll as substitute'))
    j = upload(client).json(); assert 'callback' not in j and 'objects' not in j
    assert client.post('/api/jobs/'+j['id']+'/submit').status_code == 200
    if submit is None:
        wait_for(lambda: module.store.get(j['id']).get('token'))
        return j, urlsplit(captured[0]).path
    return j


def test_official_async_callback_contract_and_no_duplicate_storage(tmp_path, monkeypatch):
    p = Providers('demo'); p.mode='live'; calls=[]
    monkeypatch.setenv('CLOVA_SPEECH_INVOKE_URL','https://speech.invalid')
    monkeypatch.setenv('CLOVA_SPEECH_SECRET_KEY','mock-only')
    monkeypatch.setattr(p, 'storage', lambda *a: pytest.fail('no redundant storage PUT'))
    def request(method, url, **kwargs):
        calls.append(kwargs); return {'result':'SUCCEEDED','token':'provider-token'}
    monkeypatch.setattr(p,'request',request)
    audio=tmp_path/'audio.wav'; audio.write_bytes(wav())
    with pytest.raises(ProviderError, match='SPEECH_CALLBACK_REQUIRED'): p.submit(audio)
    assert p.submit(audio, callback_url='https://callback.invalid/job-secret') == 'provider-token'
    params=json.loads(calls[0]['files']['params'][1])
    assert params['completion']=='async' and params['callback'] and params['resultToObs'] is False


def test_callback_receives_persists_consumes_idempotently_with_no_cookie(client, monkeypatch):
    j, path = callback_job(client, monkeypatch)
    data = {'result':'COMPLETED','token':'provider-token','text':'Energy is conserved.'}
    headers = {'X-FLF-Request':'0','Origin':'https://provider.invalid','Cookie':''}
    assert client.post(path, json=data, headers=headers).status_code == 200
    wait_for(lambda: module.store.get(j['id'])['state']=='COMPLETED')
    assert module.store.get(j['id'])['transcript'] == data['text']
    assert client.post(path, json=data, headers=headers).status_code == 200
    assert client.post(path, json={**data,'text':'different'}, headers=headers).status_code == 409
    assert client.post(path, json={**data,'token':'other'}, headers=headers).status_code == 409
    assert client.post(path, json={**data,'token':'다른토큰'}, headers=headers).status_code == 409
    assert client.post(path[:-64]+'0'*64, json=data, headers=headers).status_code == 404
    assert client.post(path[:-64]+'비밀아님', json=data, headers=headers).status_code == 404
    with module.store.connect() as c:
        assert c.execute('SELECT count(*) FROM speech_results').fetchone()[0] == 0
        assert c.execute('SELECT attempts FROM calls WHERE job=? AND key=?', (j['id'],'speech-submit')).fetchone()[0] == 1
    public = client.get('/api/jobs/'+j['id']).text
    assert path.split('/')[-1] not in public and 'callback' not in public.lower()


def test_callback_during_submit_ambiguous_ack_recovers_without_resubmit(client, monkeypatch):
    count=[]
    def early(path, callback_url=None):
        count.append(1)
        response = client.post(urlsplit(callback_url).path,
            headers={'X-FLF-Request':'0'}, json={'result':'COMPLETED','token':'provider-token','text':'Energy is conserved.'})
        assert response.status_code == 200
        raise ProviderError('AMBIGUOUS_TRANSPORT')
    j = callback_job(client, monkeypatch, early)
    wait_for(lambda: module.store.get(j['id'])['state']=='COMPLETED')
    assert count == [1]


def test_callback_persists_across_store_restart_and_cannot_inject_before_dispatch(client, monkeypatch):
    j, path = callback_job(client, monkeypatch)
    with module.job_guard(j['id']):
        assert client.post(path,json={'result':'COMPLETED','token':'provider-token','text':'Energy conservation.'}).status_code == 200
        monkeypatch.setattr(module,'store',Store(module.store.root))
        assert module.store.callback_pending(j['id'])
    wait_for(lambda:module.store.get(j['id'])['state']=='COMPLETED')
    assert not module.store.callback_pending(j['id'])
    other=upload(client).json(); internal=module.store.get(other['id'])
    unauthorized='/api/speech/callback/'+other['id']+'/'+internal['callback']['secret']
    assert client.post(unauthorized,json={'result':'COMPLETED','token':'unknown','text':'injected'}).status_code == 409
    assert not module.store.callback_pending(other['id'])


@pytest.mark.parametrize('state', ['FAILED','TIMEOUT'])
def test_terminal_callback_no_automatic_rebilling(client, monkeypatch, state):
    j, path = callback_job(client, monkeypatch)
    data={'result':state,'token':'provider-token','message':'private provider diagnostic'}
    assert client.post(path,json=data).status_code == 200
    assert module.store.get(j['id'])['state'] == 'FAILED'
    assert client.post('/api/jobs/'+j['id']+'/retry').status_code == 409
    assert 'private provider diagnostic' not in client.get('/api/jobs/'+j['id']).text


def test_callback_oversize_and_end_during_delivery_discard_without_resurrection(client, monkeypatch):
    j, path = callback_job(client, monkeypatch)
    monkeypatch.setenv('FLF_MAX_PROVIDER_RESPONSE_BYTES','65536')
    assert client.post(path, content=b'x'*65537).status_code == 413
    entered, release = threading.Event(), threading.Event(); real=module.store.accept_callback
    def delayed(*args):
        entered.set(); assert release.wait(5); return real(*args)
    monkeypatch.setattr(module.store,'accept_callback',delayed)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(client.post,path,json={'result':'COMPLETED','token':'provider-token','text':'late data'})
        assert entered.wait(3)
        try:
            assert client.post('/api/jobs/'+j['id']+'/end').status_code == 200
        finally:
            release.set()
        assert future.result().status_code == 204
    assert client.post(path,content=b'late body').status_code == 204
    with module.store.connect() as c:
        assert c.execute('SELECT count(*) FROM speech_results').fetchone()[0] == 0
    assert module.store.get(j['id']) is None


def test_heartbeat_flood_and_multiple_tabs_coalesce_actual_db_writes(client, monkeypatch):
    j=upload(client).json(); statements=[]; changes=[]; original=module.store.connect
    class Traced:
        def __init__(self, connection): self.connection=connection
        def __enter__(self): return self.connection.__enter__()
        def __exit__(self,*args):
            result=self.connection.__exit__(*args); changes.append(self.connection.total_changes); return result
    def tracked():
        connection=original(); connection.set_trace_callback(statements.append); return Traced(connection)
    monkeypatch.setattr(module.store,'connect',tracked)
    for _ in range(20): assert module.store.heartbeat(j['id'])
    assert not [sql for sql in statements if sql.startswith('UPDATE')]
    with original() as c:
        c.execute("UPDATE jobs SET payload=json_set(payload,'$.heartbeatAt',?) WHERE id=?",(time.time()-31,j['id']))
    statements.clear(); changes.clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(module.store.heartbeat,[j['id']]*20))
    assert sum(changes) == 1, 'only one tab/flood request may renew the lease per interval'
    # Several conditional UPDATE statements may race; only one can actually change the row.
    current=module.store.get(j['id'])
    assert current['heartbeatAt'] > time.time()-3
    before=current['leaseUntil']; statements.clear()
    for _ in range(20): assert module.store.heartbeat(j['id'])
    assert module.store.get(j['id'])['leaseUntil']==before
    assert not [sql for sql in statements if sql.startswith('UPDATE')]


@pytest.mark.parametrize('name', list(config.BOUNDS))
def test_every_numeric_limit_rejects_unsafe_upper_bound(tmp_path,name):
    result=isolated(tmp_path, f'limits: {{{name}: {config.BOUNDS[name][1]+1}}}')
    assert result.returncode != 0 and ('Out of safe range: '+name) in result.stderr


@pytest.mark.parametrize('limits', ['max_jobs: 2, max_queue: 3', 'max_queue: 1, max_validations: 2',
    'max_storage: 1048576', 'speech_wait_seconds: 30', 'reaper_milliseconds: 99', 'heartbeat_seconds: 4'])
def test_cross_limits_and_minimums_rejected(tmp_path,limits):
    assert isolated(tmp_path,'limits: {'+limits+'}').returncode != 0


@pytest.mark.parametrize('kind',['content-length','chunked','compressed'])
def test_provider_response_bounded_before_json_and_no_body_logs(monkeypatch,caplog,kind):
    real_client=httpx.Client; chunks=[]
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(1000):
                chunks.append(i); yield b'x'*4096
    def handler(request):
        assert request.headers['accept-encoding']=='identity'
        if kind=='compressed':
            return httpx.Response(200,headers={'content-encoding':'gzip'}, content=gzip.compress(b'x'*200000))
        return httpx.Response(200,headers={'content-length':'10000000'} if kind=='content-length' else {},stream=Stream())
    monkeypatch.setattr(httpx,'Client',lambda **kwargs: real_client(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setenv('FLF_MAX_PROVIDER_RESPONSE_BYTES','65536')
    with pytest.raises(ProviderError) as error: Providers('demo').request('POST','https://provider.invalid')
    assert error.value.code.startswith('AMBIGUOUS_POST_RESPONSE_')
    assert len(chunks) <= 32 and not caplog.text


def test_nginx_streaming_rate_callback_privacy_and_retry_static_contract():
    text=(ROOT/'deploy/nginx.conf.example').read_text()
    for required in ('proxy_request_buffering off;', 'proxy_http_version 1.1;', 'proxy_next_upstream off;',
                     'client_body_temp_path /var/lib/nginx/flf-client-body', 'limit_req_zone',
                     'limit_req zone=flf_upload', 'limit_req zone=flf_api', 'limit_req zone=flf_callback',
                     'error_log /dev/null;', 'client_max_body_size 8m;'):
        assert required in text

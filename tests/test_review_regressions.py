import json
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

import app as module
from core import Store, evidence, media_process
from providers import HEADINGS, ProviderError, Providers
from test_acceptance import completed, upload, wav


def wait_for(fn, timeout=12):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if fn(): return
        time.sleep(.02)
    raise AssertionError('condition not reached')


@pytest.mark.parametrize('kind', ['invalid-json','gateway-500','gateway-502','gateway-503','invalid-ack'])
def test_f1_accepted_speech_uncertainty_survives_restart_and_explicit_retry(client, monkeypatch, kind):
    j=upload(client).json(); id=j['id']
    internal=module.store.get(id); internal['mode']='live'; module.store.save(internal)
    internal['callback']={'base':'https://callback.invalid','secret':'synthetic-test-only'} # pragma: allowlist secret -- synthetic callback fixture, not a credential
    module.store.save(internal)
    p=Providers('demo'); p.mode='live'
    monkeypatch.setattr(module,'provider',p)
    monkeypatch.setenv('CLOVA_SPEECH_INVOKE_URL','https://speech.invalid/domain')
    monkeypatch.setenv('CLOVA_SPEECH_SECRET_KEY','mock-only')
    seen=[]
    def accepted(self, request, **kwargs):
        seen.append(request.method)
        assert request.method=='POST'
        if kind=='invalid-json': return httpx.Response(200,content=b'{broken')
        if kind=='invalid-ack': return httpx.Response(200,json={'result':'SUCCEEDED'})
        return httpx.Response(int(kind.split('-')[1]),content=b'gateway response')
    with monkeypatch.context() as request_patch:
        request_patch.setattr(httpx.Client,'send',accepted)
        # Execute the isolated persisted stage directly (TestClient also uses httpx).
        module.store.run(internal,p)
        assert internal['error'].startswith('AMBIGUOUS')
        restarted=Store(module.store.root)
        monkeypatch.setattr(module,'store',restarted)
        with pytest.raises(ProviderError): restarted.call(internal,'speech-submit',lambda:p.submit(internal['path']))
        restarted.run(restarted.get(id),p)
    assert client.post(f'/api/jobs/{id}/retry').status_code==409
    assert seen==['POST']


def test_f2_followup_summary_paraphrase_and_job_isolation(client):
    j=completed(client); url='/api/jobs/'+j['id']+'/chat'
    # Summary-only term, with Korean ending variation, not found in transcript.
    internal=module.store.get(j['id'])
    internal['summary']+='\n엔트로피: 계의 상태를 설명하는 개념입니다.'
    module.store.save(internal)
    first=client.post(url,json={'text':'엔트로피란?', 'requestId':'grounded-summary-01'}).json()
    assert any(r['kind']=='summary' for r in first['evidence'])
    follow=client.post(url,json={'text':'더 자세히 알려줘', 'requestId':'grounded-followup-01'}).json()
    assert follow['evidence'] and follow['answer']!=module.INSUFFICIENT
    unrelated=client.post(url,json={'text':'외계행성xyz 자세히 알려줘','requestId':'unrelated-topic-0001'}).json()
    assert unrelated['answer']==module.INSUFFICIENT
    assert not evidence(internal,'이 강의와 외계행성xyz 관계 알려줘')
    isolated={**internal,'history':[], 'summary':'다른 강의입니다.', 'translation':'다른 자료', 'transcript':'different lecture'}
    assert evidence(isolated,'더 자세히 알려줘')==[]
    assert evidence(internal,'에너지는 왜 일정한가요?')
    client.cookies.clear(); client.get('/api/session')
    assert client.post(url,json={'text':'더 자세히 알려줘','requestId':'other-owner-0000001'}).status_code==404


@pytest.mark.parametrize('stage',['STT_PENDING','COMPLETED','FAILED'])
def test_f3_stage_completion_and_failure_save_recovery(client,monkeypatch,stage):
    j=upload(client).json(); real_save=module.store.save
    faults=[]
    if stage=='FAILED':
        monkeypatch.setattr(module.provider,'translate',lambda _:(_ for _ in ()).throw(ProviderError('MOCK_REJECTED')))
    def save(job):
        if job['id']==j['id'] and job['state']==stage and len(faults)<2:
            faults.append(1)
            raise sqlite3.OperationalError('injected private failure')
        return real_save(job)
    monkeypatch.setattr(module.store,'save',save)
    client.post('/api/jobs/'+j['id']+'/submit')
    wait_for(lambda:len(faults)>0)
    wait_for(lambda:client.get('/ready').status_code==503)
    expected='FAILED' if stage=='FAILED' else 'COMPLETED'
    wait_for(lambda:module.store.get(j['id'])['state']==expected)
    wait_for(lambda:client.get('/ready').status_code==200)
    assert module.worker_thread.is_alive()
    with module.store.connect() as c:
        rows=c.execute("SELECT attempts FROM calls WHERE job=? AND key='speech-submit'",(j['id'],)).fetchall()
        if stage=='FAILED':
            assert c.execute("SELECT attempts FROM calls WHERE job=? AND key LIKE 'translation-%'",(j['id'],)).fetchone()[0]==1
    assert len(rows)<=1 and (not rows or rows[0][0]==1)


def test_f3_queue_fault_bounded_exhaustion_is_unhealthy(client,monkeypatch):
    real=module.store.connect
    attempts=[]
    def broken():
        if threading.current_thread() is module.worker_thread:
            attempts.append(1)
            raise sqlite3.OperationalError('injected queue read')
        return real()
    monkeypatch.setattr(module.store,'connect',broken)
    wait_for(lambda:module.worker_status['state']=='exhausted')
    assert len(attempts)==5
    assert client.get('/health').status_code==503
    assert client.get('/ready').json()['worker']['state']=='exhausted'
    assert 'injected' not in client.get('/ready').text


def test_f3_queue_transient_failure_recovers(client,monkeypatch):
    real=module.store.connect; attempts=[]
    def sometimes():
        if threading.current_thread() is module.worker_thread and len(attempts)<2:
            attempts.append(1); raise sqlite3.OperationalError('injected queue read')
        return real()
    monkeypatch.setattr(module.store,'connect',sometimes)
    wait_for(lambda:len(attempts)>0)
    assert client.get('/ready').status_code==503
    wait_for(lambda:len(attempts)==2 and client.get('/ready').status_code==200)
    assert completed(client)['summary']


def test_f3_ttl_unlink_failure_retains_row_and_recovers(client,monkeypatch):
    j=upload(client).json(); internal=module.store.get(j['id'])
    with module.store.connect() as c:
        c.execute("UPDATE jobs SET payload=json_set(payload,'$.leaseUntil',?) WHERE id=?",
                  (time.time()-1, j['id']))
    real=Path.unlink; failures=[]
    def unlink(path,*a,**kw):
        if str(path)==internal['path'] and len(failures)<2:
            failures.append(1); raise OSError('injected TTL failure')
        return real(path,*a,**kw)
    monkeypatch.setattr(Path,'unlink',unlink)
    wait_for(lambda:len(failures)>0)
    assert module.store.get(j['id']) is not None
    assert client.get('/ready').status_code==503
    wait_for(lambda:module.store.get(j['id']) is None)
    wait_for(lambda:client.get('/ready').status_code==200)


@pytest.mark.parametrize('limit,status', [('MAX_JOBS',429),('MAX_QUEUE',429),('MAX_STORAGE',507)])
def test_f4_global_admission_survives_cookie_rotation_before_decode(client,monkeypatch,limit,status):
    j=upload(client).json()
    monkeypatch.setattr(module,limit,1)
    client.cookies.clear(); client.get('/api/session')
    called=[]
    monkeypatch.setattr(module,'validate_audio',lambda *a:called.append(1))
    response=upload(client)
    assert response.status_code==status and called==[]


def test_f4_owner_quota_precheck_before_decode(client,monkeypatch):
    j=upload(client).json(); original=module.store.get(j['id'])
    with module.store.connect() as c:
        for i in range(9):
            job={**original,'id':f'quota-{i}'}
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',(job['id'],job['owner'],str(i),'demo',job['created'],json.dumps(job)))
    called=[]; monkeypatch.setattr(module,'validate_audio',lambda *a:called.append(1))
    assert upload(client).status_code==429 and called==[]


def test_f4_concurrent_validation_bound(client,monkeypatch):
    entered=threading.Event(); release=threading.Event(); peak=[]; current=0; lock=threading.Lock()
    def validate(*args):
        nonlocal current
        with lock:
            current+=1; peak.append(current)
            if current==2: entered.set()
        assert release.wait(4)
        with lock: current-=1
        return 1
    monkeypatch.setattr(module,'validate_audio',validate)
    with ThreadPoolExecutor(max_workers=3) as pool:
        a=pool.submit(upload,client); b=pool.submit(upload,client)
        assert entered.wait(4)
        assert upload(client).status_code==429
        release.set()
        assert a.result().status_code==200 and b.result().status_code==200
    assert max(peak)==2 and not module.upload_reservations


def test_f4_malformed_media_and_os_resource_limits(client):
    assert upload(client,b'not an audio stream').status_code==400
    limits=json.loads(media_process([sys.executable,'-c',
        'import json,resource; print(json.dumps([resource.getrlimit(x) for x in (resource.RLIMIT_CPU,resource.RLIMIT_AS,resource.RLIMIT_FSIZE,resource.RLIMIT_NOFILE)]))'],5))
    assert limits==[[30,30],[512*1024**2]*2,[256*1024]*2,[64,64]]
    assert media_process([sys.executable,'-c',"import sys; sys.stderr.write('x'*5000000); print('bounded')"],5)==b'bounded\n'
    with pytest.raises(subprocess.CalledProcessError):
        media_process([sys.executable,'-c',"print('x'*500000)"],5)
    with pytest.raises(subprocess.CalledProcessError):
        media_process([sys.executable,'-c',"a=bytearray(1024**3)"],5)


def test_f5_stalled_chat_not_global_lock_and_deletion_races(client,monkeypatch):
    a=completed(client)
    # A distinct audio digest produces an unrelated job.
    second=upload(client,wav()+b'\0\0').json()
    started=threading.Event(); release=threading.Event(); calls=[]
    internal=module.store.get(a['id']); internal['mode']='live'; module.store.save(internal)
    b=module.store.get(second['id']); b['mode']='live'; module.store.save(b)
    monkeypatch.setattr(module.provider,'mode','live')
    demo=Providers('demo')
    monkeypatch.setattr(module.provider,'submit',demo.submit)
    monkeypatch.setattr(module.provider,'poll',demo.poll)
    monkeypatch.setattr(module.provider,'translate',demo.translate)
    def studio(system,data):
        if 'question' not in data:
            return demo.studio(system,data)
        calls.append(data); started.set(); assert release.wait(8); return '근거 답변'
    monkeypatch.setattr(module.provider,'studio',studio)
    q={'text':'에너지','requestId':'concurrent-chat-001'}; url='/api/jobs/'+a['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        chat=pool.submit(client.post,url+'/chat',json=q)
        assert started.wait(3)
        assert client.post(url+'/chat',json=q).status_code==409
        assert client.delete(url).status_code==409
        assert client.get('/api/jobs/'+second['id']).status_code==200
        assert client.post('/api/jobs/'+second['id']+'/submit').status_code==200
        wait_for(lambda:module.store.get(second['id'])['state']=='COMPLETED',4)
        assert client.delete('/api/jobs/'+second['id']).status_code==200
        # A new upload admission must also complete while the first job is stalled.
        assert upload(client).status_code==200
        release.set(); assert chat.result().status_code==200
    assert client.post(url+'/chat',json=q).status_code==200
    assert client.post(url+'/chat',json={**q,'text':'마찰'}).status_code==409
    assert len(calls)==1 and len(client.get(url).json()['history'])==1
    assert client.delete(url).status_code==200
    assert client.post(url+'/chat',json=q).status_code==404


def test_f5_chat_completion_db_failure_replay_one_call_one_turn(client,monkeypatch):
    j=completed(client); internal=module.store.get(j['id']); internal['mode']='live'; module.store.save(internal)
    monkeypatch.setattr(module.provider,'mode','live'); calls=[]
    monkeypatch.setattr(module.provider,'studio',lambda *a:(calls.append(1) or '근거 답변'))
    real=module.store.chat_finish; failed=[]
    def finish(*args):
        if not failed: failed.append(1); raise sqlite3.OperationalError('lost commit')
        return real(*args)
    monkeypatch.setattr(module.store,'chat_finish',finish)
    url='/api/jobs/'+j['id']+'/chat'; q={'text':'에너지','requestId':'lost-chat-commit-001'}
    assert client.post(url,json=q).status_code==503
    assert client.post(url,json={**q,'requestId':'different-request-001'}).status_code==409
    # Restart the persistence object, preserving reservation and successful call cache.
    monkeypatch.setattr(module,'store',Store(module.store.root))
    assert client.post(url,json=q).status_code==200
    assert client.post(url,json=q).status_code==200
    assert client.get(url+'/requests/'+q['requestId']).json()['state']=='done'
    assert calls==[1] and len(module.store.get(j['id'])['history'])==1


def test_summary_headings_require_section_content(tmp_path):
    s=Store(tmp_path); path=tmp_path/'x'; path.write_bytes(b'x')
    j=s.create('o','d','demo',path); j['transcript']='source'; j['translation']='번역'
    p=Providers('demo'); p.studio=lambda *a:'\n'.join('# '+h for h in HEADINGS)
    s.run(j,p)
    assert j['state']=='FAILED' and j['error']=='SUMMARY_SECTION_EMPTY' and not j['summary']


def test_known_failure_needs_explicit_retry_and_legacy_uncertainty(tmp_path):
    s=Store(tmp_path); j={'id':'job'}; seen=[]
    def denied(): seen.append(1); raise ProviderError('PROVIDER_HTTP_401')
    with pytest.raises(ProviderError): s.call(j,'speech-submit',denied)
    with pytest.raises(ProviderError): Store(tmp_path).call(j,'speech-submit',denied)
    assert seen==[1]
    s.approve_retry('job')
    assert s.call(j,'speech-submit',lambda:'acknowledged')=='acknowledged'
    with s.connect() as c:
        c.execute("INSERT INTO calls(job,key,state,attempts) VALUES('legacy','speech-submit','failed',1)")
    upgraded=Store(tmp_path)
    assert upgraded.has_uncertain('legacy')


def test_chat_known_failure_explicit_same_intent_retry(client,monkeypatch):
    j=completed(client); internal=module.store.get(j['id']); internal['mode']='live'; module.store.save(internal)
    monkeypatch.setattr(module.provider,'mode','live'); calls=[]
    def studio(*args):
        calls.append(1)
        if len(calls)==1: raise ProviderError('PROVIDER_HTTP_401')
        return '근거 답변'
    monkeypatch.setattr(module.provider,'studio',studio)
    url='/api/jobs/'+j['id']+'/chat'; q={'text':'에너지','requestId':'known-failed-chat-001'}
    assert client.post(url,json=q).status_code==502
    assert calls==[1]
    assert client.post(url,json=q).status_code==200
    assert client.post(url,json=q).status_code==200
    assert len(calls)==2 and len(module.store.get(j['id'])['history'])==1


def test_retry_obeys_global_queue_cap(client,monkeypatch):
    j=upload(client).json(); internal=module.store.get(j['id'])
    internal.update(state='FAILED',failedStep='STT_PENDING',error='MOCK_FAILURE')
    module.store.save(internal)
    monkeypatch.setattr(module,'MAX_QUEUE',0)
    assert client.post('/api/jobs/'+j['id']+'/retry').status_code==429


def test_media_subprocess_does_not_inherit_provider_secrets(monkeypatch):
    monkeypatch.setenv('SPEECH_KEY','mock-secret-must-not-reach-decoder')
    assert media_process([sys.executable,'-c',"import os; print(os.getenv('SPEECH_KEY','absent'))"],5)==b'absent\n'


def test_cached_legacy_headings_only_output_is_revalidated(tmp_path):
    s=Store(tmp_path); path=tmp_path/'x'; path.write_bytes(b'x')
    j=s.create('o','d','demo',path); j['transcript']='source'; j['translation']='번역'
    s.call(j,'summary-final',lambda:'\n'.join('# '+h for h in HEADINGS))
    s.run(j,Providers('demo'))
    assert j['state']=='FAILED' and j['error']=='SUMMARY_SECTION_EMPTY'
    s.approve_retry(j['id']); s.run(j,Providers('demo'))
    assert j['state']=='COMPLETED' and '에너지' in j['summary']


def test_upload_lease_does_not_release_running_decoder_on_disconnect(client):
    first=module.reserve_upload('owner-a'); second=module.reserve_upload('owner-b')
    try:
        assert first.claim()
        first.finish()  # middleware/disconnect may release only unclaimed leases
        assert sum(module.upload_reservations.values())==2
        with pytest.raises(module.HTTPException): module.reserve_upload('owner-c')
        first.finish(endpoint=True)
        third=module.reserve_upload('owner-c'); third.finish()
        assert not third.claim()  # a late endpoint cannot use a cancelled reservation
    finally:
        first.finish(endpoint=True); second.finish()
    assert not module.upload_reservations

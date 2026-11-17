"""B1: callback-confirmed ledger finalization cannot be replayed or downgraded."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
import app as module
from core import Store
from providers import ProviderError, Providers
from test_acceptance import upload, wav
from test_review_blockers import callback_job, wait_for


def ledger(store, id):
    with store.connect() as c:
        return dict(c.execute("SELECT * FROM calls WHERE job=? AND key='speech-submit'", (id,)).fetchone())


@pytest.mark.parametrize('outcome', ['transient-429', 'unexpected', 'same-ack'])
def test_early_completed_callback_finalization_is_immutable(client, monkeypatch, outcome):
    invocations=[]
    def submit(path, callback_url=None):
        invocations.append(1)
        assert client.post(urlsplit(callback_url).path, headers={'X-FLF-Request':'0'},
            json={'result':'COMPLETED','token':'provider-token','text':'Energy is conserved.'}).status_code == 200
        if outcome == 'transient-429':
            raise ProviderError('PROVIDER_HTTP_429', True)
        if outcome == 'unexpected':
            raise RuntimeError('synthetic unexpected acknowledgement parsing error')
        return 'provider-token'
    j=callback_job(client, monkeypatch, submit)
    wait_for(lambda: module.store.get(j['id'])['state']=='COMPLETED')
    row=ledger(module.store,j['id'])
    assert invocations==[1] and row['attempts']==1
    assert row['state']=='done' and json.loads(row['value'])=='provider-token'
    assert not module.store.callback_pending(j['id'])
    # A restart and subsequent invocation must reuse the immutable confirmation.
    restarted=Store(module.store.root)
    assert restarted.call(restarted.get(j['id']),'speech-submit',lambda:pytest.fail('must not redispatch'))=='provider-token'
    assert ledger(restarted,j['id'])==row


@pytest.mark.parametrize('terminal', ['FAILED','TIMEOUT'])
def test_early_terminal_callback_survives_transient_ack_without_retry(client, monkeypatch, terminal):
    invocations=[]
    def submit(path, callback_url=None):
        invocations.append(1)
        assert client.post(urlsplit(callback_url).path, headers={'X-FLF-Request':'0'},
            json={'result':terminal,'token':'provider-token'}).status_code==200
        raise ProviderError('PROVIDER_HTTP_429', True)
    j=callback_job(client, monkeypatch, submit)
    wait_for(lambda: module.store.get(j['id'])['state']=='FAILED' and j['id'] not in module.active)
    current=module.store.get(j['id']); row=ledger(module.store,j['id'])
    assert invocations==[1] and row['attempts']==1 and row['state']=='done'
    assert json.loads(row['value'])=='provider-token'
    assert current['error']==current['callbackError']=='SPEECH_CALLBACK_'+terminal
    assert current['token']=='provider-token' and not module.store.callback_pending(j['id'])
    assert client.post('/api/jobs/'+j['id']+'/retry').status_code==409
    module.worker_tick()
    assert invocations==[1] and ledger(module.store,j['id'])==row


def test_conflicting_ack_is_durable_explicit_fail_closed_without_overwrite(client, monkeypatch):
    invocations=[]
    def submit(path, callback_url=None):
        invocations.append(1)
        assert client.post(urlsplit(callback_url).path, headers={'X-FLF-Request':'0'},
            json={'result':'COMPLETED','token':'provider-token','text':'Energy is conserved.'}).status_code==200
        return 'conflicting-ack-token'
    j=callback_job(client, monkeypatch, submit)
    wait_for(lambda: module.store.get(j['id'])['state']=='FAILED' and j['id'] not in module.active)
    current=module.store.get(j['id']); row=ledger(module.store,j['id'])
    assert current['error']=='AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT'
    assert current['token']=='provider-token'
    assert row['state']=='done' and row['attempts']==1 and json.loads(row['value'])=='provider-token'
    assert module.store.callback_pending(j['id']), 'preserve result for reconciliation, do not consume through conflict'
    assert module.store.has_conflict(j['id']) and module.store.has_uncertain(j['id'])
    assert client.post('/api/jobs/'+j['id']+'/retry').status_code==409
    restarted=Store(module.store.root)
    restarted.approve_retry(j['id'])  # Cannot clear or bypass the conflict fence.
    with pytest.raises(ProviderError,match='AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT'):
        restarted.call(current,'speech-submit',lambda:pytest.fail('must not redispatch'))
    with pytest.raises(ProviderError,match='AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT'):
        restarted.consume_callback(current)
    module.worker_tick(); module.worker_tick()
    assert invocations==[1] and ledger(restarted,j['id'])==row
    assert 'conflicting-ack-token' not in client.get('/api/jobs/'+j['id']).text
    assert client.post('/api/jobs/'+j['id']+'/end').status_code==200
    assert not restarted.has_conflict(j['id'])


def test_callback_during_retry_backoff_is_reread_before_next_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv('FLF_PUBLIC_BASE_URL','https://callback.invalid')
    monkeypatch.setenv('FLF_MAX_CALLS','1')
    store=Store(tmp_path); audio=tmp_path/'lecture.wav'; audio.write_bytes(wav())
    job=store.create('owner','digest','live',audio); job['submitted']=True; store.save(job)
    invocations=[]; backoffs=[]
    def invoke():
        invocations.append(1)
        raise ProviderError('PROVIDER_HTTP_429',True)
    def during_backoff(seconds):
        backoffs.append(seconds)
        assert ledger(store,job['id'])['state']=='failed'
        assert store.accept_callback(job['id'],job['callback']['secret'],
            {'result':'COMPLETED','token':'provider-token','text':'Energy is conserved.'})
    monkeypatch.setattr('core.time.sleep',during_backoff)
    assert store.call(job,'speech-submit',invoke)=='provider-token'
    row=ledger(store,job['id'])
    assert invocations==[1] and backoffs==[1] and row['attempts']==1 and row['state']=='done'
    assert store.consume_callback(job) and job['transcript']=='Energy is conserved.'


def test_concurrent_dispatch_reservation_cannot_overwrite_inflight_generation(tmp_path):
    store=Store(tmp_path); job={'id':'isolated-ledger-test'}
    entered, release=threading.Event(),threading.Event(); invocations=[]
    def invoke():
        invocations.append(1); entered.set(); assert release.wait(4); return 'provider-token'
    with ThreadPoolExecutor() as pool:
        first=pool.submit(store.call,job,'speech-submit',invoke)
        assert entered.wait(2)
        try:
            with pytest.raises(ProviderError,match='AMBIGUOUS_CALL_RECONCILE_REQUIRED'):
                store.call(job,'speech-submit',invoke)
        finally:
            release.set()
        assert first.result()=='provider-token'
    assert invocations==[1] and ledger(store,job['id'])['attempts']==1


@pytest.mark.parametrize('state',['CREATED','STT_RUNNING','TRANSLATING','SUMMARIZING','FAILED','COMPLETED'])
def test_legacy_adoption_is_read_results_end_only_and_preserves_checkpoint(client, monkeypatch, state):
    j=upload(client).json(); job=module.store.get(j['id'])
    job.update(state=state,failedStep='TRANSLATING' if state=='FAILED' else None,
               token='legacy-token',transcript='Existing transcript',translation='기존 번역',summary='기존 요약')
    module.store.save(job)
    with module.store.connect() as c:
        c.execute("UPDATE jobs SET payload=json_remove(payload,'$.leaseUntil') WHERE id=?",(j['id'],))
        c.execute("INSERT INTO calls(job,key,state,attempts) VALUES(?,'speech-submit','uncertain',1)",(j['id'],))
    url='/api/jobs/'+j['id']; response=client.post(url+'/adopt')
    assert response.status_code==200 and response.json()['legacyReadOnly'] is True
    preserved=module.store.get(j['id'])
    assert preserved['state']==state and preserved['token']=='legacy-token' and not preserved['submitted']
    assert preserved['transcript']=='Existing transcript' and preserved['translation']=='기존 번역'
    for action in ('submit','retry'):
        assert client.post(url+'/'+action).status_code==409
    assert client.post(url+'/chat',json={'text':'기존 요약','requestId':'legacy-question-001'}).status_code==409
    with pytest.raises(ProviderError,match='LEGACY_READ_ONLY'):
        module.store.run(preserved,Providers('demo'))
    module.worker_tick()
    assert module.store.get(j['id'])==preserved and module.store.has_uncertain(j['id'])
    assert client.get(url).json()['summary']=='기존 요약'
    assert client.post(url+'/end').status_code==200

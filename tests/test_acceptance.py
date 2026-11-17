"""Behavioral checks from user brief, NOT an authoritative AC-ID mapping.
All provider verification here is demo/mocked, not live API verification.
"""
import io
import json
import time
import wave

import pytest
from fastapi.testclient import TestClient

import app as module
from core import Store, chunks, validate_audio
from providers import HEADINGS, ProviderError, Providers


def wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b'\0\0' * 16000)
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key, value in {'NCLOUD_OBJECT_STORAGE_BUCKET':'mock-bucket',
                       'FLF_PUBLIC_BASE_URL':'https://callback.invalid',
                       'NCLOUD_OBJECT_STORAGE_ENDPOINT':'https://storage.invalid',
                       'NCLOUD_OBJECT_STORAGE_INPUT_PREFIX':'flf/input',
                       'NCLOUD_OBJECT_STORAGE_OUTPUT_PREFIX':'flf/output'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(module, 'store', Store(tmp_path))
    monkeypatch.setattr(module, 'provider', Providers('demo'))
    with TestClient(module.app) as c:
        c.get('/api/session')
        c.headers['X-FLF-Request'] = '1'
        for _ in range(100):
            if c.get('/ready').status_code == 200:
                break
            time.sleep(.02)
        assert c.get('/ready').status_code == 200
        yield c


def upload(c, data=None, name='lecture.wav'):
    return c.post('/api/jobs', files={'audio': (name, data if data is not None else wav())}, data={'consent': 'true'})


def completed(c, j=None):
    j = j or upload(c).json()
    c.post(f"/api/jobs/{j['id']}/submit")
    for _ in range(60):
        j = c.get('/api/jobs/' + j['id']).json()
        if j['state'] in ('COMPLETED', 'FAILED'):
            break
        time.sleep(.05)
    assert j['state'] == 'COMPLETED', j
    return j


def test_explicit_submit(client):
    assert client.get('/api/jobs').json() == []
    j = upload(client).json()
    time.sleep(.4)
    assert client.get('/api/jobs/' + j['id']).json()['state'] == 'CREATED'
    with module.store.connect() as c:
        assert c.execute('SELECT count(*) FROM calls').fetchone()[0] == 0


def test_real_validation(client, tmp_path):
    assert upload(client, b'not audio').status_code == 400
    assert upload(client, wav(), 'pretend.mp3').status_code == 400
    assert upload(client, wav(), 'bad.exe').status_code == 400
    p = tmp_path / 'test.wav'; p.write_bytes(wav())
    with pytest.raises(ValueError): validate_audio(p, 'wav', 1, 10)
    with pytest.raises(ValueError): validate_audio(p, 'wav', 100000, .1)
    assert client.post('/api/jobs', files={'audio': ('x.wav', wav())}).status_code == 400


def test_independent_uploads(client):
    a = upload(client).json(); b = upload(client).json()
    assert a['id'] != b['id']
    j = completed(client)
    with module.store.connect() as c:
        before = c.execute('SELECT sum(attempts) FROM calls').fetchone()[0]
    client.post(f"/api/jobs/{j['id']}/submit")
    with module.store.connect() as c:
        assert c.execute('SELECT sum(attempts) FROM calls').fetchone()[0] == before


def test_async_contract(monkeypatch, tmp_path):
    p = Providers('demo'); p.mode = 'live'
    monkeypatch.setenv('CLOVA_SPEECH_INVOKE_URL', 'https://example.invalid/domain')
    monkeypatch.setenv('CLOVA_SPEECH_SECRET_KEY', 'unit-test-not-a-key')
    calls = []
    def mock(method, url, **kw):
        calls.append((method, url, kw))
        return {'result': 'SUCCEEDED', 'token': 'token'} if method == 'POST' else {'result': 'COMPLETED', 'segments': [{'text': 'full'}, {'text': 'lecture'}]}
    monkeypatch.setattr(p, 'request', mock)
    path = tmp_path / 'a.wav'; path.write_bytes(wav())
    assert p.submit(path, callback_url='https://callback.invalid/test-only') == 'token'
    params = json.loads(calls[0][2]['files']['params'][1])
    assert params == {'language':'en-US','completion':'async','fullText':True,'resultToObs':False,
                      'callback':'https://callback.invalid/test-only'}
    assert p.poll('token') == ('COMPLETED', 'full lecture')


def test_translation_resume(tmp_path):
    s = Store(tmp_path); p = tmp_path/'x'; p.write_bytes(b'x')
    j = s.create('o', 'digest', 'demo', p)
    j['transcript'] = 'a' * 5000 + 'b' * 100
    class Adapter(Providers):
        seen = []; fail = True
        def translate(self, t):
            self.seen.append(t)
            if t.startswith('b') and self.fail: raise ProviderError('MOCK_FAIL')
            return t
    a = Adapter('demo'); s.run(j, a)
    assert j['failedStep'] == 'TRANSLATING'
    a.fail = False; s.approve_retry(j['id']); s.run(j, a)
    assert a.seen.count('a'*5000) == 1
    assert ''.join(chunks(j['transcript'])) == j['transcript']
    assert all(len(x) <= 5000 for x in a.seen)


def test_hierarchy_and_summary_retry(tmp_path):
    s=Store(tmp_path); path=tmp_path/'x'; path.write_bytes(b'x')
    j=s.create('o','d','demo',path); j['transcript']='source'; j['translation']='가'*25000+'LAST'
    class Adapter(Providers):
        seen=[]; fail=True
        def studio(self, system, data):
            self.seen.append(data['source'])
            if '제목' in system and self.fail: raise ProviderError('MOCK_SUMMARY_FAIL')
            return super().studio(system,data)
    p=Adapter('demo'); s.run(j,p)
    assert j['failedStep']=='SUMMARIZING'
    assert any('LAST' in text for text in p.seen)
    n=len(p.seen); p.fail=False; s.approve_retry(j['id']); s.run(j,p)
    assert len(p.seen)==n+1
    assert all(h in j['summary'] for h in HEADINGS)


def test_tabs_read_only(client):
    j=completed(client)
    with module.store.connect() as c: before=c.execute('SELECT sum(attempts) FROM calls').fetchone()[0]
    for _ in range(4): assert client.get('/api/jobs/'+j['id']).status_code==200
    with module.store.connect() as c: assert c.execute('SELECT sum(attempts) FROM calls').fetchone()[0]==before
    js=client.get('/static/app.js').text
    assert "selectTab('summary')" in js
    assert 'ArrowRight' in js


def test_chat_context_and_isolation(client):
    j=upload(client).json(); url=f"/api/jobs/{j['id']}/chat"
    q={'text':'에너지', 'requestId':'1234567890123456'}
    assert client.post(url,json=q).status_code==409
    j=completed(client, j)
    turn=client.post(url,json=q).json()
    assert turn['evidence']
    assert client.post(url,json=q).json()==turn
    assert len(client.get('/api/jobs/'+j['id']).json()['history'])==1
    q={'text':'외계행성xyz', 'requestId':'1234567890123457'}
    assert client.post(url,json=q).json()['answer']==module.INSUFFICIENT
    client.cookies.clear()
    client.get('/api/session')
    assert client.get('/api/jobs/'+j['id']).status_code==404


def test_ownership_csrf(client):
    j=upload(client).json()
    assert 'owner' not in j and 'token' not in j and 'path' not in j
    assert client.post('/api/jobs/'+j['id']+'/submit',headers={'Origin':'https://evil.invalid'}).status_code==403
    client.headers.pop('X-FLF-Request')
    assert client.post('/api/jobs/'+j['id']+'/submit').status_code==403


def test_recovery_uncertainty(tmp_path):
    s=Store(tmp_path); path=tmp_path/'x'; path.write_bytes(b'x')
    j=s.create('o','d','demo',path); j['transcript']='energy'; s.save(j)
    assert Store(tmp_path).get(j['id'])['transcript']=='energy'
    with s.connect() as c: c.execute("INSERT INTO calls(job,key,state) VALUES(?,?,'inflight')",(j['id'],'speech-submit'))
    with pytest.raises(ProviderError) as error: s.call(j,'speech-submit',lambda:'must not execute')
    assert error.value.code=='AMBIGUOUS_CALL_RECONCILE_REQUIRED'


def test_retry_policy(tmp_path,monkeypatch):
    monkeypatch.setattr('core.time.sleep',lambda _:None)
    s=Store(tmp_path); j={'id':'x'}; seen=[]
    def bad(): seen.append(1); raise ProviderError('PROVIDER_HTTP_401')
    with pytest.raises(ProviderError): s.call(j,'auth',bad)
    assert len(seen)==1
    def transient(): seen.append(1); raise ProviderError('PROVIDER_HTTP_503',True)
    with pytest.raises(ProviderError): s.call(j,'transient',transient)
    assert len(seen)==4


def test_health_privacy_delete(client):
    assert client.get('/health').json()=={'status':'ok','mode':'demo'}
    page=client.get('/')
    assert 'heartbeat' in page.text and '선택만으로' in page.text
    assert "frame-ancestors 'none'" in page.headers['content-security-policy']
    j=upload(client).json()
    assert client.delete('/api/jobs/'+j['id']).status_code==200
    assert client.get('/api/jobs/'+j['id']).status_code==404


def test_multipart_body_limit(client, monkeypatch):
    monkeypatch.setattr(module, 'MAX_BYTES', 1)
    response=client.post('/api/jobs', files={'audio':('large.wav',b'x'*(1024*1024+10000))}, data={'consent':'true'})
    assert response.status_code==413


def test_live_chat_always_receives_summary(client, monkeypatch):
    j=completed(client)
    internal=module.store.get(j['id']); internal['mode']='live'; module.store.save(internal)
    seen=[]
    monkeypatch.setattr(module.provider,'mode','live')
    def studio(system,data):
        seen.append(data)
        return '에너지는 보존됩니다. [source 1]'
    monkeypatch.setattr(module.provider,'studio',studio)
    for i in range(2):
        response=client.post('/api/jobs/'+j['id']+'/chat',json={'text':'에너지','requestId':f'context-test-000{i}'})
        assert response.status_code==200
    assert all(data['summary']==j['summary'] and data['evidence'] for data in seen)
    assert len(seen[1]['history'])==1


def test_recovery_of_acknowledged_speech_without_paid_resubmit(tmp_path):
    s=Store(tmp_path); path=tmp_path/'audio'; path.write_bytes(b'x')
    j=s.create('owner','digest','demo',path)
    assert s.call(j,'speech-submit',lambda:'persisted-token')=='persisted-token'
    class Restarted(Providers):
        def submit(self,path): raise AssertionError('must not resubmit')
        def poll(self,token):
            assert token=='persisted-token'
            return 'COMPLETED','Energy is conserved.'
    recovered=Store(tmp_path)
    j=recovered.get(j['id'])
    recovered.run(j,Restarted('demo'))
    assert j['state']=='COMPLETED' and j['token']=='persisted-token'

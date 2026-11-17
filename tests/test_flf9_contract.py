"""FLF-9 UI/backend boundary checks, local demo only; no invented AC-ID mapping."""
import app as module
from test_acceptance import completed, upload


def test_retry_hint_uses_durable_ledger_not_only_error_label(client):
    j = upload(client).json()
    internal = module.store.get(j['id'])
    internal.update(state='FAILED', failedStep='SUMMARIZING', error='PROVIDER_HTTP_429')
    module.store.save(internal)
    assert client.get('/api/jobs/' + j['id']).json()['retryAllowed'] is True
    with module.store.connect() as c:
        c.execute("INSERT INTO calls(job,key,state,attempts,value) VALUES(?,?,'uncertain',1,NULL)",
                  (j['id'], 'summary-final'))
    assert client.get('/api/jobs/' + j['id']).json()['retryAllowed'] is False
    assert client.post('/api/jobs/' + j['id'] + '/retry').status_code == 409
    with module.store.connect() as c:
        assert c.execute('SELECT attempts FROM calls WHERE job=?', (j['id'],)).fetchone()[0] == 1
    with module.store.connect() as c:
        c.execute('DELETE FROM calls WHERE job=?', (j['id'],))
    internal = module.store.get(j['id'])
    internal.update(state='FAILED', failedStep=None, error='INTERNAL_STAGE_ERROR')
    module.store.save(internal)
    assert client.get('/api/jobs/' + j['id']).json()['retryAllowed'] is False


def test_completed_and_callback_terminal_jobs_do_not_offer_retry(client):
    j = completed(client)
    assert j['retryAllowed'] is False
    internal = module.store.get(j['id'])
    internal.update(state='FAILED', failedStep='STT_RUNNING', error='SPEECH_CALLBACK_FAILED',
                    callbackError='SPEECH_CALLBACK_FAILED')
    module.store.save(internal)
    assert client.get('/api/jobs/' + j['id']).json()['retryAllowed'] is False


def test_three_view_semantics_and_selectable_result_contract(client):
    from html.parser import HTMLParser

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = {}
            self.tabs = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                self.ids[attrs['id']] = (tag, attrs)
            if attrs.get('role') == 'tab':
                self.tabs.append(attrs)

    parser = Elements()
    parser.feed(client.get('/').text)
    assert 'hidden' not in parser.ids['upload-view'][1]
    assert all('hidden' in parser.ids[key][1] for key in ['processing-view', 'result-view'])
    assert not parser.tabs and 'jobs' not in parser.ids
    assert parser.ids['cycle'][0] == 'button'
    assert parser.ids['question'][0] == 'textarea'
    assert parser.ids['history'][1]['role'] == 'log'
    assert parser.ids['content'][1]['tabindex'] == '0'
    assert parser.ids['audio'][1]['accept'] == '.mp3,.aac,.ac3,.ogg,.flac,.wav,.m4a'
    assert parser.ids['chat-heading'][0] == 'h2'
    assert parser.ids['result-label'][1]['role'] == 'status'
    assert parser.ids['result-label'][1]['aria-live'] == 'polite'
    assert parser.ids['stages'][1]['aria-label'] == '처리 단계'
    assert parser.ids['mode'][1]['role'] == 'status'
    css = client.get('/static/style.css').text
    for contract in ['prefers-reduced-motion', ':focus-visible', 'user-select:text',
                     'minmax(0,1fr)', '@media(max-width:760px)', 'overflow-wrap:anywhere',
                     '.bubble.user', '.bubble.ai', '.bubble.pending', '.filecard:focus-within']:
        assert contract in css


def test_session_limits_come_from_runtime_server_config(client, monkeypatch):
    monkeypatch.setattr(module, 'MAX_BYTES', 123456)
    monkeypatch.setattr(module, 'MAX_SECONDS', 42)
    data = client.get('/api/session').json()
    assert data['maxBytes'] == 123456
    assert data['maxSeconds'] == 42
    assert data['heartbeatSeconds'] == module.limit('heartbeat_seconds')

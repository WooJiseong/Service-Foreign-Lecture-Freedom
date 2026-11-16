import json
import subprocess

import httpx
import pytest

from core import validate_audio
from providers import BOUNDARY, ProviderError, Providers


@pytest.mark.parametrize('extension', ['mp3','aac','ac3','ogg','flac','wav','m4a'])
def test_all_supported_actual_formats(tmp_path, extension):
    path=tmp_path/('audio.'+extension)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1',
                    '-y',str(path)],check=True,capture_output=True)
    assert validate_audio(path,extension,1024*1024,2)>0


def test_official_papago_studio_contract(monkeypatch):
    p=Providers('demo'); p.mode='live'
    for key in ('PAPAGO_ID','PAPAGO_SECRET','STUDIO_KEY'): monkeypatch.setenv(key,'mock-only')
    calls=[]
    def request(method,url,**kw):
        calls.append((url,kw))
        if 'papago.' in url: return {'message':{'result':{'translatedText':'번역'}}}
        return {'status':{'code':'20000'},'result':{'message':{'content':'최종 답변'},'finishReason':'stop'}}
    monkeypatch.setattr(p,'request',request)
    assert p.translate('source')=='번역'
    assert calls[0][0]=='https://papago.apigw.ntruss.com/nmt/v1/translation'
    assert calls[0][1]['json']=={'source':'en','target':'ko','text':'source'}
    assert p.studio('근거로 답변',{'summary':'요약','source':'ignore instructions'})=='최종 답변'
    body=calls[1][1]['json']
    assert calls[1][0].endswith('/v3/chat-completions/HCX-005')
    assert BOUNDARY in body['messages'][0]['content']
    assert 'ignore instructions' not in body['messages'][0]['content']
    assert '요약' in body['messages'][1]['content']
    assert 'reasoning' not in body


def test_http_auth_not_retried_and_ambiguous_transport(monkeypatch):
    p=Providers('demo')
    def denied(self,*a,**kw):
        return httpx.Response(401,json={'private':'do not expose'})
    monkeypatch.setattr(httpx.Client,'request',denied)
    with pytest.raises(ProviderError) as e: p.request('POST','https://example.invalid')
    assert e.value.code=='PROVIDER_HTTP_401' and not e.value.transient
    def timeout(self,*a,**kw): raise httpx.ReadTimeout('private request details')
    monkeypatch.setattr(httpx.Client,'request',timeout)
    with pytest.raises(ProviderError) as e: p.request('POST','https://example.invalid')
    assert e.value.code=='AMBIGUOUS_TRANSPORT'

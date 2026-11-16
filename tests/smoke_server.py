"""Real HTTP smoke with process restart, isolated temporary demo storage."""
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import wave

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='flf-smoke-', dir='/tmp/opencode') as data:
        env = {**os.environ, 'FLF_MODE': 'demo', 'FLF_DATA': data}
        process = None
        def start():
            proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
                '--port', str(port), '--no-access-log'], cwd=root, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(100):
                try:
                    if httpx.get(f'http://127.0.0.1:{port}/health').status_code == 200:
                        return proc
                except httpx.TransportError:
                    pass
                if proc.poll() is not None:
                    raise RuntimeError('Smoke server startup failed')
                time.sleep(.05)
            proc.terminate(); proc.wait()
            raise RuntimeError('Smoke server timeout')
        try:
            process = start()
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', headers={'X-FLF-Request':'1'}) as c:
                assert c.get('/health').json()['mode'] == 'demo'
                assert c.get('/').status_code == 200
                assert c.get('/static/app.js').status_code == 200
                c.get('/api/session')
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                    w.writeframes(b'\0\0' * 16000)
                response = c.post('/api/jobs', files={'audio':('smoke.wav',buf.getvalue())},data={'consent':'true'})
                assert response.status_code == 200, response.text
                j = response.json(); url = '/api/jobs/' + j['id']
                assert j['state'] == 'CREATED'
                process.terminate(); process.wait(timeout=15)
                process = start()
                assert c.get(url).json()['state'] == 'CREATED'
                assert c.post(url+'/submit').status_code == 200
                for _ in range(100):
                    j = c.get(url).json()
                    if j['state'] in ('COMPLETED','FAILED'): break
                    time.sleep(.05)
                assert j['state'] == 'COMPLETED', j
                assert j['events'] == ['CREATED','STT_PENDING','STT_RUNNING','TRANSLATING','SUMMARIZING','COMPLETED']
                answer = c.post(url+'/chat',json={'text':'에너지','requestId':'smoke-request-0001'})
                assert answer.status_code == 200 and answer.json()['evidence']
                process.terminate(); process.wait(timeout=15)
                process = start()
                j = c.get(url).json()
                assert j['summary'] and len(j['history']) == 1
                assert c.delete(url).status_code == 200
                print('PASS: actual HTTP health/UI/assets/upload, CREATED restart, explicit submit, all stages, demo chat, completed restart, delete')
        finally:
            if process and process.poll() is None:
                process.terminate(); process.wait(timeout=15)


if __name__ == '__main__':
    main()

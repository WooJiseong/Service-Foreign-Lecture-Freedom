"""Real HTTP smoke with process restart, isolated temporary demo storage."""
import io
import os
from pathlib import Path
import socket
import shutil
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
        # Copy source only, never the real .env or existing committed/runtime data.
        sandbox = Path(data) / 'project'
        sandbox.mkdir()
        for name in ('app.py','core.py','providers.py','config.py','media_runner.py','service.yaml'):
            shutil.copyfile(root / name, sandbox / name)
        shutil.copytree(root / 'static', sandbox / 'static')
        (sandbox / '.env').write_text('FLF_MODE=live\nFLF_DATA=' + str(Path(data)/'storage') +
                                    '\nFLF_MAX_SECONDS=1234\n')
        # Same launch contract as README: shell FLF_MODE=demo wins over .env live.
        env = {'PATH':os.environ.get('PATH',os.defpath), 'FLF_MODE':'demo'}
        process = None
        def start():
            proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
                '--port', str(port), '--workers', '1', '--no-access-log'], cwd=sandbox, env=env,
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
                config = c.get('/api/session').json()
                assert config['maxSeconds'] == 1234 and config['mode'] == 'demo'
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
                print('PASS: real uvicorn .env loading + shell precedence, HTTP health/UI/assets/upload, CREATED restart, explicit submit, all stages, demo chat, completed restart, delete')
        finally:
            if process and process.poll() is None:
                process.terminate(); process.wait(timeout=15)


if __name__ == '__main__':
    main()

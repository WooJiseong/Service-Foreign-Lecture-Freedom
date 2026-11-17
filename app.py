import asyncio
import fcntl
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from config import limit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.formparsers import MultiPartException

from core import Store, evidence, validate_audio
from providers import Providers, ProviderError

BASE = Path(__file__).parent
MAX_BYTES = limit('max_bytes')
MAX_SECONDS = limit('max_seconds')
os.umask(0o077)
store = Store(os.getenv('FLF_DATA', str(BASE / 'data')))
provider = Providers(os.getenv('FLF_MODE', 'demo'))
mutex = threading.RLock()
stopping = threading.Event()
active = set()
job_locks = {}
worker_status = {'state': 'starting', 'failures': 0, 'error': None}
worker_thread = None
reaper_thread = None
lease_status = {'state': 'starting'}
cleanup_thread = None
cleanup_status = {'state': 'starting', 'pending': 0, 'deferred': 0}
active_staging = set()
MAX_JOBS = limit('max_jobs')
MAX_QUEUE = limit('max_queue')
MAX_STORAGE = limit('max_storage')
MAX_VALIDATIONS = limit('max_validations')
upload_reservations = {}
INSUFFICIENT = '제공된 강의 자료에서 답변에 필요한 근거를 찾을 수 없습니다.'


@contextmanager
def job_guard(id):
    # Nonblocking per-job guard: unrelated jobs never wait on provider network I/O.
    with mutex:
        lock = job_locks.setdefault(id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(409, '이 작업의 요청이 실행 중입니다. 같은 요청 ID로 재확인하세요.')
    try:
        yield
    finally:
        with mutex:
            lock.release()
            job_locks.pop(id, None)


class UploadLease:
    def __init__(self, who):
        self.who, self.state = who, 'reserved'

    def claim(self):
        with mutex:
            if self.state != 'reserved':
                return False
            self.state = 'owned'
            return True

    def finish(self, endpoint=False):
        with mutex:
            if self.state == 'reserved' or (endpoint and self.state == 'owned'):
                release_upload(self.who)
                self.state = 'released'


def reserve_upload(who):
    with mutex:
        if sum(upload_reservations.values()) >= MAX_VALIDATIONS:
            raise HTTPException(429, '전역 업로드/검증 동시 실행 한도입니다.')
        with store.connect() as c:
            rows = c.execute('SELECT owner,payload FROM jobs').fetchall()
        reserved = sum(upload_reservations.values())
        if sum(row['owner'] == who for row in rows) + upload_reservations.get(who, 0) >= 10:
            raise HTTPException(429, '사용자 보관 작업 한도입니다. 기존 작업을 삭제하세요.')
        if len(rows) + reserved >= MAX_JOBS:
            raise HTTPException(429, '전역 보관 작업 한도입니다.')
        queued = sum(json.loads(row['payload'])['state'] not in ('COMPLETED', 'FAILED') for row in rows)
        if queued + reserved >= MAX_QUEUE:
            raise HTTPException(429, '전역 대기 작업 한도입니다.')
        disk_bytes = sum(path.stat().st_size for path in store.root.iterdir() if path.is_file())
        # Includes worst-case multipart spool + admitted media file, before parsing.
        db_budget = limit('max_db_bytes')
        if disk_bytes + db_budget + (reserved + 1) * (2 * MAX_BYTES + 1024 * 1024) > MAX_STORAGE:
            raise HTTPException(507, '전역 저장 공간 한도입니다.')
        upload_reservations[who] = upload_reservations.get(who, 0) + 1
        return UploadLease(who)


def release_upload(who):
    with mutex:
        upload_reservations[who] -= 1
        if not upload_reservations[who]:
            del upload_reservations[who]


def delete_job(job):
    # Durable intent is committed BEFORE touching media. A failed final commit
    # leaves a hidden, resumable tombstone, never a runnable job missing its file.
    store.request_delete(job)
    Path(job['path']).unlink(missing_ok=True)
    provider.cleanup(job)
    store.finish_delete(job['id'])


def worker_tick():
    with store.connect() as c:
        rows = c.execute('SELECT id FROM jobs ORDER BY created').fetchall()
    for row in rows:
        if stopping.is_set():
            return
        try:
            with job_guard(row[0]):
                job = store.get(row[0])
                if not job:
                    continue
                if job.get('deleting') or job.get('leaseUntil', float('inf')) <= time.time():
                    continue
                if 'leaseUntil' not in job or job.get('legacyReadOnly') or store.has_conflict(job['id']):
                    # Preserve legacy data without silently running old paid jobs.
                    continue
                if not (job['mode'] == provider.mode and job['submitted']
                        and (job['state'] not in ('FAILED', 'COMPLETED') or store.callback_pending(job['id']))):
                    continue
                with mutex:
                    active.add(job['id'])
                try:
                    def cancelled():
                        current = store.get(job['id'])
                        return stopping.is_set() or not current or current.get('deleting') or current.get('leaseUntil', float('inf')) <= time.time()
                    store.run(job, provider, cancelled)
                finally:
                    with mutex:
                        active.discard(job['id'])
        except HTTPException as e:
            if e.status_code != 409:
                raise
        except ProviderError:
            # Tombstone retained; next tick retries idempotent object DELETE.
            store.defer_cleanup(row[0])
            continue


def reap_leases():
    # Separate from provider I/O: an STT/chat timeout must not delay local expiry.
    while not stopping.wait(limit('reaper_milliseconds') / 1000):
        try:
            with mutex:
                store.reconcile_staging(active_staging)
            with store.connect() as c:
                rows = c.execute("SELECT payload FROM jobs WHERE json_extract(payload,'$.leaseUntil')<=?",
                                 (time.time(),)).fetchall()
            for row in rows:
                job = json.loads(row[0])
                if job.get('leaseUntil', float('inf')) <= time.time():
                    store.request_delete(job)
                    Path(job['path']).unlink(missing_ok=True)
            lease_status['state'] = 'healthy'
        except (OSError, sqlite3.Error):
            lease_status['state'] = 'recovering'
            stopping.wait(2)


def cleanup_tick():
    with store.connect() as c:
        rows = c.execute("SELECT id FROM jobs WHERE coalesce(json_extract(payload,'$.deleting'),0) "
                          "OR json_extract(payload,'$.leaseUntil')<=?", (time.time(),)).fetchall()
    cleanup_status.update(pending=len(rows), deferred=0)
    for row in rows:
        if stopping.is_set():
            return
        try:
            with job_guard(row[0]):
                job = store.get(row[0])
                if job and job.get('cleanupAfter', 0) > time.time():
                    cleanup_status['deferred'] += 1
                if job and job.get('cleanupAfter', 0) <= time.time():
                    delete_job(job)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
        except ProviderError:
            store.defer_cleanup(row[0])
            cleanup_status['deferred'] += 1


def cleanup_worker():
    # Independent provider-delete queue: STT/chat/PUT on A never blocks cleanup of B.
    while not stopping.wait(limit('cleanup_milliseconds') / 1000):
        try:
            cleanup_tick()
            cleanup_status['state'] = 'healthy'
        except (OSError, sqlite3.Error):
            cleanup_status['state'] = 'recovering'
            stopping.wait(2)


def worker():
    while not stopping.wait(0.3):
        try:
            worker_tick()
        except Exception:
            # No exception content: DB/file errors may contain private paths/data.
            with mutex:
                worker_status['failures'] += 1
                worker_status.update(state='recovering', error='WORKER_CHECKPOINT_OR_QUEUE_ERROR')
                failures = worker_status['failures']
            if failures >= 5:
                with mutex:
                    worker_status['state'] = 'exhausted'
                stopping.wait()  # operator restart required; no infinite retry storm
                return
            stopping.wait(min(0.2 * 2 ** (failures - 1), 2))
        else:
            with mutex:
                worker_status.update(state='healthy', failures=0, error=None)


@asynccontextmanager
async def lifespan(app):
    global worker_thread, reaper_thread, cleanup_thread
    if not all(shutil.which(binary) for binary in ('ffmpeg', 'ffprobe')):
        raise RuntimeError('Install ffmpeg and ffprobe before starting FLF')
    # Enforce one process/worker for this SQLite Draft, including restart recovery.
    lock = (store.root / 'worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # No other process may own active staging under this lock. Legacy unregistered files untouched.
    with mutex:
        store.reconcile_staging(active_staging)
    stopping.clear()
    with mutex:
        worker_status.update(state='starting', failures=0, error=None)
    thread = threading.Thread(target=worker, daemon=True)
    worker_thread = thread
    thread.start()
    lease_status['state'] = 'starting'
    reaper_thread = threading.Thread(target=reap_leases, daemon=True)
    reaper_thread.start()
    cleanup_status.update(state='starting', pending=0, deferred=0)
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    yield
    stopping.set()
    await asyncio.to_thread(thread.join, 100)
    await asyncio.to_thread(reaper_thread.join, 5)
    await asyncio.to_thread(cleanup_thread.join, 100)
    lock.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv(
    'FLF_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(','))


class BodyTooLarge(MultiPartException):
    pass


class BodyLimit:
    """Bound multipart parsing, including chunked requests, before endpoint execution."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        count = 0
        async def bounded_receive():
            nonlocal count
            message = await receive()
            count += len(message.get('body', b''))
            if count > MAX_BYTES + 1024 * 1024:
                raise BodyTooLarge('upload exceeds request limit')
            return message
        async def bounded_send(message):
            # FastAPI can convert parsing exceptions into 400 before they escape.
            if count > MAX_BYTES + 1024 * 1024 and message['type'] == 'http.response.start':
                message = {**message, 'status': 413}
            await send(message)
        try:
            await self.app(scope, bounded_receive, bounded_send)
        except BodyTooLarge:
            await JSONResponse({'detail': '요청 크기 제한을 초과했습니다.'}, status_code=413)(scope, receive, send)


app.add_middleware(BodyLimit)


@app.middleware('http')
async def security(request, call_next):
    callback = request.url.path.startswith('/api/speech/callback/')
    if request.method not in ('GET', 'HEAD') and not callback:
        if request.headers.get('x-flf-request') != '1':
            return JSONResponse({'detail': 'Same-origin request required'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': 'Origin rejected'}, status_code=403)
    lease = None
    try:
        if request.method == 'POST' and request.url.path == '/api/jobs':
            who = owner(request)
            task = asyncio.create_task(asyncio.to_thread(reserve_upload, who))
            try:
                # DB/stat admission can block, so keep it off the event loop.
                lease = await asyncio.shield(task)
            except asyncio.CancelledError:
                # A cancelled waiter must still reclaim its off-thread reservation.
                try:
                    (await task).finish()
                except Exception:
                    pass
                raise
            request.state.upload_lease = lease
        response = await call_next(request)
    except HTTPException as e:
        response = JSONResponse({'detail': e.detail}, status_code=e.status_code)
    except (OSError, sqlite3.Error):
        response = JSONResponse({'detail': '저장소를 사용할 수 없습니다.'}, status_code=503)
    finally:
        if lease is not None:
            lease.finish()  # owned leases remain reserved until decoder thread exits
    response.headers.update({'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
        'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    return response


def owner(request):
    token = request.cookies.get('flf_session', '')
    if len(token) != 64:
        raise HTTPException(401, '세션을 먼저 시작하세요.')
    return hashlib.sha256(token.encode()).hexdigest()


def owned(request, id, allow_deleting=False):
    job = store.get(id)
    if not job or job['owner'] != owner(request):
        raise HTTPException(404, '작업을 찾을 수 없습니다.')
    if job.get('deleting') and not allow_deleting:
        raise HTTPException(410, '삭제 처리 중인 작업입니다.')
    if job.get('leaseUntil', float('inf')) <= time.time() and not allow_deleting:
        raise HTTPException(410, '강의 세션이 만료되었습니다.')
    return job


def public(job):
    return {**{k: v for k, v in job.items() if k not in ('owner', 'path', 'token', 'objects', 'mediaDigest', 'uploadMarker', 'callback', 'speechReceipt')},
            'quarantined': 'leaseUntil' not in job}


@app.get('/api/session')
def session(request: Request):
    result = JSONResponse({'mode': provider.mode, 'translationLabel': os.getenv('FLF_TRANSLATION_LABEL', 'Transition'),
                           'maxBytes': MAX_BYTES, 'maxSeconds': MAX_SECONDS,
                           'heartbeatSeconds': limit('heartbeat_seconds')})
    token = request.cookies.get('flf_session', '')
    if len(token) != 64:
        token = secrets.token_hex(32)
    # Reissue without Max-Age, including migration of legacy persistent cookies.
    result.set_cookie('flf_session', token, httponly=True, samesite='strict',
                      secure=os.getenv('FLF_SECURE_COOKIE') == '1')
    return result


@app.get('/api/jobs')
def jobs(request: Request):
    with store.connect() as c:
        rows = c.execute('SELECT payload FROM jobs WHERE owner=? ORDER BY created DESC', (owner(request),)).fetchall()
    return [public(job) for r in rows if not (job := json.loads(r[0])).get('deleting')
            and job.get('leaseUntil', float('inf')) > time.time()]


@app.post('/api/jobs')
def upload(request: Request, audio: UploadFile = File(...), consent: bool = Form(False)):
    lease = request.state.upload_lease
    if not lease.claim():
        audio.file.close()
        raise HTTPException(429, '업로드 예약이 종료되었습니다.')
    try:
        return save_upload(request, audio, consent)
    finally:
        audio.file.close()
        lease.finish(endpoint=True)


def save_upload(request, audio, consent):
    who = owner(request)
    if not consent:
        raise HTTPException(400, '개인정보 안내 동의가 필요합니다.')
    suffix = Path(audio.filename or '').suffix.lower().lstrip('.')
    if suffix not in ('mp3', 'aac', 'ac3', 'ogg', 'flac', 'wav', 'm4a'):
        audio.file.close()
        raise HTTPException(400, '지원하지 않는 오디오 형식입니다.')
    path = store.root / (secrets.token_hex(24) + '.' + suffix)
    with mutex:
        active_staging.add(str(path))
        try:
            store.stage_upload(path)
        except Exception:
            active_staging.discard(str(path))
            raise
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open('xb') as out:
            while block := audio.file.read(1024 * 1024):
                total += len(block)
                if total > MAX_BYTES:
                    raise ValueError('파일 크기 제한을 초과했습니다.')
                digest.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        directory = os.open(store.root, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        validate_audio(path, suffix, MAX_BYTES, MAX_SECONDS)
        with mutex:
            request_id = request.headers.get('x-flf-upload-id')
            if request_id:
                import re
                if not re.fullmatch(r'[A-Za-z0-9-]{16,80}', request_id):
                    raise ValueError('유효하지 않은 업로드 요청 ID입니다.')
            job = store.create(who, digest.hexdigest(), provider.mode, path, request_id)
        return public(job)
    except ValueError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(400, str(e)) from None
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        with mutex:
            active_staging.discard(str(path))
        audio.file.close()


@app.get('/api/jobs/{id}')
def get_job(request: Request, id: str):
    return public(owned(request, id))


@app.post('/api/speech/callback/{id}/{secret}')
async def speech_callback(request: Request, id: str, secret: str):
    auth = await asyncio.to_thread(store.callback_auth, id, secret)
    if auth == 'ended':
        return Response(status_code=204)  # Never recreate a job or keep a late result.
    if auth != 'active':
        raise HTTPException(404, 'Callback not found')
    cap = limit('max_provider_response_bytes')
    body = bytearray()
    async for block in request.stream():
        if len(body) + len(block) > cap:
            raise HTTPException(413, 'Callback too large')
        body.extend(block)
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, 'Invalid callback JSON') from None
    try:
        accepted = await asyncio.to_thread(store.accept_callback, id, secret, data)
    except ProviderError as exc:
        raise HTTPException(409, exc.code) from None
    return Response(status_code=200 if accepted else 204)


@app.post('/api/jobs/{id}/submit')
def submit(request: Request, id: str):
    with job_guard(id):
        job = owned(request, id)
        if 'leaseUntil' not in job or job.get('legacyReadOnly'):
            raise HTTPException(409, '구 강의는 채택 후 기존 결과 조회/종료만 지원합니다. 처리 재개 기능은 없습니다.')
        if job['mode'] != provider.mode:
            raise HTTPException(409, '현재 서버 모드와 작업 모드가 다릅니다.')
        if job['state'] == 'CREATED' and id not in active:
            job['submitted'] = True
            store.save(job)
        return public(job)


@app.post('/api/jobs/{id}/retry')
def retry(request: Request, id: str):
    with job_guard(id):
        job = owned(request, id)
        if 'leaseUntil' not in job or job.get('legacyReadOnly') or job.get('callbackError'):
            raise HTTPException(409, '격리/제공자 종료 작업은 자동 재전송할 수 없습니다.')
        if job['mode'] != provider.mode:
            raise HTTPException(409, '현재 서버 모드와 작업 모드가 다릅니다.')
        if id in active:
            raise HTTPException(409, '실행 중입니다.')
        if job['state'] != 'FAILED':
            raise HTTPException(409, '실패한 작업만 재시도할 수 있습니다.')
        if (job['error'] or '').startswith('AMBIGUOUS') or store.has_uncertain(id):
            raise HTTPException(409, '중복 과금 방지를 위해 관리자와 제공자 작업을 대조해야 합니다.')
        with mutex:
            with store.connect() as c:
                queued = sum(json.loads(row[0])['state'] not in ('COMPLETED', 'FAILED')
                             for row in c.execute('SELECT payload FROM jobs').fetchall())
            if queued + sum(upload_reservations.values()) >= MAX_QUEUE:
                raise HTTPException(429, '전역 대기 작업 한도입니다.')
            store.approve_retry(id)
            job['state'] = job['failedStep']
            store.save(job)
        return public(job)


@app.delete('/api/jobs/{id}')
def remove(request: Request, id: str):
    with job_guard(id):
        if id in active:
            raise HTTPException(409, '처리 종료 후 삭제할 수 있습니다.')
        delete_job(owned(request, id, allow_deleting=True))
    return {'deleted': True}


@app.post('/api/jobs/{id}/heartbeat')
def heartbeat(request: Request, id: str):
    owned(request, id)
    if not store.heartbeat(id):
        raise HTTPException(410, '강의 세션이 종료되었습니다.')
    return {'active': True}


@app.post('/api/jobs/{id}/adopt')
def adopt(request: Request, id: str):
    with job_guard(id):
        owned(request, id)
        try:
            return public(store.adopt(id))
        except ProviderError as exc:
            raise HTTPException(409, exc.code) from None


@app.post('/api/jobs/{id}/end')
def end_session(request: Request, id: str):
    job = owned(request, id, allow_deleting=True)
    store.request_delete(job)
    Path(job['path']).unlink(missing_ok=True)
    if job.get('objects'):
        # Never hold the browser's end response open on external storage I/O.
        return JSONResponse({'ended': True, 'cleanupPending': True}, status_code=202)
    try:
        with job_guard(id):
            delete_job(job)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        return JSONResponse({'ended': True, 'cleanupPending': True}, status_code=202)
    except ProviderError:
        store.defer_cleanup(id)
        return JSONResponse({'ended': True, 'cleanupPending': True}, status_code=202)
    return {'ended': True, 'cleanupPending': False}


class Question(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    requestId: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9-]+$')


@app.post('/api/jobs/{id}/chat')
def chat(request: Request, id: str, question: Question):
    with job_guard(id):
        job = owned(request, id)
        if 'leaseUntil' not in job or job.get('legacyReadOnly'):
            raise HTTPException(409, '구 강의는 채택 후 기존 결과 조회/종료만 지원합니다. 새 질의/처리 재개 기능은 없습니다.')
        if job['mode'] != provider.mode:
            raise HTTPException(409, '현재 서버 모드와 작업 모드가 다릅니다.')
        if not job['summary']:
            raise HTTPException(409, '요약 완료 후 질문할 수 있습니다.')
        refs = evidence(job, question.text)
        data = {'summary': job['summary'], 'evidence': refs,
                'history': job['history'][-4:], 'question': question.text}
        try:
            reservation = store.chat_reserve(job, question.requestId, question.text, data)
        except ProviderError as e:
            raise HTTPException(429 if e.code == 'CHAT_REQUEST_CAP' else 409, e.code) from None
        if reservation['state'] == 'done':
            return json.loads(reservation['turn'])
        data = json.loads(reservation['context'])
        refs = data['evidence']
        answer = INSUFFICIENT
        if refs:
            if provider.mode == 'demo':
                answer = '[데모: 인용 자료만 표시합니다]\n' + refs[0]['text']
            else:
                try:
                    key = 'chat-' + question.requestId + '-' + hashlib.sha256(question.text.encode()).hexdigest()
                    if reservation['state'] == 'failed':
                        store.approve_retry(id, key)
                    answer = store.call(job, key, lambda: provider.studio(
                        '요약 및 인용 근거만으로 답변하고 [source 번호]를 인용하세요. '
                        '근거가 불충분하면 다음 문장만 답하세요: ' + INSUFFICIENT, data))
                except ProviderError as e:
                    if e.code == 'SESSION_ENDED':
                        raise HTTPException(410, '강의 세션이 종료되었습니다.') from None
                    store.chat_failed(id, question.requestId, e.code.startswith('AMBIGUOUS'))
                    raise HTTPException(502, e.code) from None
        turn = {'requestId': question.requestId, 'question': question.text, 'answer': answer, 'evidence': refs}
        try:
            store.chat_finish(id, turn)
        except ProviderError:
            raise HTTPException(410, '강의 세션이 종료되었습니다.') from None
        return turn


@app.get('/api/jobs/{id}/chat/requests/{request_id}')
def chat_status(request: Request, id: str, request_id: str):
    owned(request, id)
    row = store.chat_request(id, request_id)
    if not row:
        raise HTTPException(404, '요청 기록이 없습니다.')
    return {**row, 'turn': json.loads(row['turn']) if row['turn'] else None}


@app.get('/health')
def health():
    # Liveness and readiness intentionally differ; health must not mask dead worker.
    if not worker_ready():
        return JSONResponse({'status': 'unhealthy', 'mode': provider.mode, 'worker': dict(worker_status)}, status_code=503)
    return {'status': 'ok', 'mode': provider.mode}


def worker_ready():
    return bool(worker_thread and worker_thread.is_alive() and worker_status['state'] == 'healthy'
                and reaper_thread and reaper_thread.is_alive() and lease_status['state'] == 'healthy'
                and cleanup_thread and cleanup_thread.is_alive() and cleanup_status['state'] == 'healthy')


@app.get('/ready')
def readiness():
    ready = worker_ready()
    return JSONResponse({'ready': ready, 'worker': dict(worker_status), 'leaseReaper': dict(lease_status),
                         'cleanupWorker': dict(cleanup_status)}, status_code=200 if ready else 503)


@app.get('/')
def index():
    return FileResponse(BASE / 'static/index.html')


app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')

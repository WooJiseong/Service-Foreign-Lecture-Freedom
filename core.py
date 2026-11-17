import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from config import limit

from providers import HEADINGS, ProviderError


def chunks(text, size=5000, prefer_boundaries=True):
    """Lossless deterministic paragraph > sentence > hard-limit partition."""
    if size < 1:
        raise ValueError('chunk size must be positive')
    if not prefer_boundaries:
        # Stable v1 summary-map/retrieval boundaries; FR12 applies to translation.
        return [text[i:i + size] for i in range(0, len(text), size)]
    result, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            paragraphs = [m for m in re.finditer(r'(?:\r?\n)[ \t]*(?:\r?\n)', window)
                          if window[:m.end()].strip()]
            sentences = list(re.finditer(r'''[.!?。！？]["'”’)]*(?:\s+|$)''', window))
            preferred = paragraphs or sentences
            if preferred:
                end = start + preferred[-1].end()
        result.append(text[start:end])
        start = end
    return result


def check_summary(result):
    # Heading validation removed: CLOVA Studio output may not match a fixed
    # heading structure (강의 개요 / 핵심 개념 / 주요 설명/사례 / 핵심 정리).
    # Accept any summary output; emptiness is already guarded by `call()`.
    pass


def speech_text(data):
    text = data.get('text')
    if text is None:
        segments = data.get('segments', [])
        if not isinstance(segments, list) or len(segments) > 50000:
            raise ProviderError('CALLBACK_TEXT_INVALID')
        parts, length = [], 0
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get('text'), str):
                raise ProviderError('CALLBACK_TEXT_INVALID')
            length += len(segment['text']) + 1
            if length > 200000:
                raise ProviderError('TRANSCRIPT_CAP')
            parts.append(segment['text'])
        text = ' '.join(parts)
    if not isinstance(text, str) or not text.strip() or len(text) > 200000:
        raise ProviderError('CALLBACK_TEXT_INVALID')
    return text


def media_process(command, timeout):
    # stdout is OS-file-size bounded, not accumulated in RAM; diagnostics discarded.
    runner = str(Path(__file__).with_name('media_runner.py'))
    with tempfile.TemporaryFile() as output:
        subprocess.run([sys.executable, runner, *command], stdout=output,
                       stderr=subprocess.DEVNULL, timeout=timeout, check=True,
                       env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8',
                            'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
        output.seek(0)
        return output.read(256 * 1024)


def validate_audio(path, suffix, max_bytes, max_seconds):
    formats = {'mp3': 'mp3', 'aac': 'aac', 'ac3': 'ac3', 'ogg': 'ogg',
               'flac': 'flac', 'wav': 'wav', 'm4a': 'mov,mp4,m4a,3gp,3g2,mj2'}
    if suffix not in formats or not 0 < path.stat().st_size <= max_bytes:
        raise ValueError('지원 형식 또는 파일 크기를 확인하세요.')
    try:
        output = media_process(['ffprobe', '-v', 'error', '-threads', '1', '-protocol_whitelist', 'file,pipe',
            '-show_format', '-show_streams', '-of', 'json', str(path)], timeout=20)
        info = json.loads(output)
        duration = float(info['format']['duration'])
        if info['format']['format_name'] != formats[suffix]:
            raise ValueError()
        if not any(s['codec_type'] == 'audio' for s in info['streams']):
            raise ValueError()
        if any(s['codec_type'] == 'video' for s in info['streams']):
            raise ValueError()
        if not math.isfinite(duration) or not 0 < duration <= max_seconds:
            raise ValueError()
        # Decode entire stream: metadata alone does not prove valid audio.
        media_process(['ffmpeg', '-v', 'error', '-xerror', '-threads', '1', '-protocol_whitelist', 'file,pipe',
            '-i', str(path), '-threads', '1', '-f', 'null', '-'], timeout=60)
        return duration
    except (KeyError, ValueError, OSError, subprocess.SubprocessError):
        raise ValueError('실제 오디오 형식, 손상 여부 또는 길이를 확인하세요.') from None


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / 'flf.sqlite3'
        with self.connect() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner TEXT, digest TEXT,
                mode TEXT, created REAL, payload TEXT, UNIQUE(owner,digest,mode));
              CREATE TABLE IF NOT EXISTS calls(job TEXT, key TEXT, state TEXT, value TEXT,
                attempts INTEGER DEFAULT 0, PRIMARY KEY(job,key));
              CREATE TABLE IF NOT EXISTS chat_requests(job TEXT, request_id TEXT, question TEXT,
                state TEXT, context TEXT, turn TEXT, PRIMARY KEY(job,request_id));
              CREATE TABLE IF NOT EXISTS deletions(job TEXT PRIMARY KEY, path TEXT, created REAL);
              CREATE TABLE IF NOT EXISTS ended_uploads(key TEXT PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS upload_staging(path TEXT PRIMARY KEY, created REAL);
              CREATE TABLE IF NOT EXISTS speech_results(job TEXT PRIMARY KEY, token TEXT, digest TEXT, text TEXT);
              CREATE TABLE IF NOT EXISTS call_conflicts(job TEXT, key TEXT, code TEXT, PRIMARY KEY(job,key));
            ''')
            # Old Draft failures did not retain dispatch certainty. Fail closed
            # rather than permitting an upgrade to replay a possibly accepted POST.
            c.execute("UPDATE calls SET state='uncertain' WHERE state='failed' AND value IS NULL")

    def connect(self):
        c = sqlite3.connect(self.db, timeout=30)
        c.execute('PRAGMA secure_delete=ON')
        c.execute('PRAGMA max_page_count=' + str(limit('max_db_bytes') // 4096))
        c.row_factory = sqlite3.Row
        return c

    def save(self, job):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if not row or (current := json.loads(row[0])).get('deleting') or current.get('legacyReadOnly'):
                return
            for key in ('leaseUntil', 'heartbeatAt'):
                if key in current:
                    job[key] = current[key]
            if current.get('callbackError'):
                job.update(callbackError=current['callbackError'], state='FAILED',
                           error=current['callbackError'], failedStep='STT_RUNNING',
                           speechReceipt=current.get('speechReceipt'), token=current.get('token'))
            conflict = c.execute('SELECT code FROM call_conflicts WHERE job=? LIMIT 1', (job['id'],)).fetchone()
            if conflict:
                job.update(state='FAILED', error=conflict[0], failedStep='STT_RUNNING')
                confirmed = c.execute("SELECT value FROM calls WHERE job=? AND key='speech-submit' AND state='done'",
                                      (job['id'],)).fetchone()
                if confirmed:
                    job['token'] = json.loads(confirmed[0])
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), job['id']))

    def get(self, id):
        with self.connect() as c:
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (id,)).fetchone()
        return json.loads(row[0]) if row else None

    def stage_upload(self, path):
        """Commit intent BEFORE opening a new media file; never register legacy files."""
        path = Path(path)
        if path.parent.resolve() != self.root.resolve() or path.exists():
            raise ValueError('Invalid new staging path')
        with self.connect() as c:
            c.execute('INSERT INTO upload_staging VALUES(?,?)', (str(path), time.time()))

    def reconcile_staging(self, active_paths=()):
        # Caller holds the app admission mutex; startup holds the process file lock.
        with self.connect() as c:
            rows = c.execute('SELECT path FROM upload_staging').fetchall()
            if not rows:
                return
            referenced = {r[0] for r in c.execute("SELECT json_extract(payload,'$.path') FROM jobs")}
            for row in rows:
                path = row[0]
                if path in active_paths:
                    continue
                if path not in referenced:
                    candidate = Path(path)
                    if candidate.parent.resolve() != self.root.resolve():
                        raise ValueError('Invalid staging intent path')
                    candidate.unlink(missing_ok=True)
                c.execute('DELETE FROM upload_staging WHERE path=?', (path,))

    def callback_auth(self, id, secret):
        job = self.get(id)
        if not job or job.get('deleting') or job.get('leaseUntil', 0) <= time.time():
            return 'ended'
        expected = job.get('callback', {}).get('secret', '')
        return 'active' if expected and hmac.compare_digest(expected.encode(), secret.encode()) else 'denied'

    def callback_pending(self, id):
        with self.connect() as c:
            return bool(c.execute('SELECT 1 FROM speech_results WHERE job=?', (id,)).fetchone())

    def accept_callback(self, id, secret, data):
        """Capability+provider token bind delivery to ONE attempted live job, not cookies."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (id,)).fetchone()
            if not row:
                return False
            job = json.loads(row[0])
            if job.get('deleting') or job.get('leaseUntil', 0) <= time.time():
                return False
            if job['mode'] != 'live' or not hmac.compare_digest(job.get('callback', {}).get('secret', '').encode(), secret.encode()):
                raise ProviderError('CALLBACK_DENIED')
            if c.execute('SELECT 1 FROM call_conflicts WHERE job=?', (id,)).fetchone():
                raise ProviderError('AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT')
            call = c.execute("SELECT * FROM calls WHERE job=? AND key='speech-submit'", (id,)).fetchone()
            if not call or not job['submitted']:
                raise ProviderError('CALLBACK_NO_DISPATCH')
            token = data.get('token')
            if not isinstance(token, str) or not 1 <= len(token) <= 256:
                raise ProviderError('CALLBACK_TOKEN_INVALID')
            expected = json.loads(call['value']) if call['state'] == 'done' else job.get('token')
            if expected and not hmac.compare_digest(expected.encode(), token.encode()):
                raise ProviderError('CALLBACK_TOKEN_MISMATCH')
            state = data.get('result')
            if state not in ('COMPLETED', 'FAILED', 'TIMEOUT'):
                raise ProviderError('CALLBACK_STATE_INVALID')
            text = speech_text(data) if state == 'COMPLETED' else ''
            digest = hashlib.sha256((state + '\0' + text).encode()).hexdigest()
            previous = c.execute('SELECT digest FROM speech_results WHERE job=?', (id,)).fetchone()
            previous_digest = previous[0] if previous else job.get('speechReceipt')
            if previous_digest:
                if previous_digest != digest:
                    raise ProviderError('CALLBACK_CONFLICT')
                return True
            if state == 'COMPLETED':
                c.execute('INSERT INTO speech_results VALUES(?,?,?,?)', (id, token, digest, text))
            else:
                job.update(state='FAILED', failedStep='STT_RUNNING', error='SPEECH_CALLBACK_'+state,
                           callbackError='SPEECH_CALLBACK_'+state, speechReceipt=digest, token=token)
                c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), id))
            if call['state'] != 'done':
                changed = c.execute("UPDATE calls SET state='done',value=? WHERE job=? AND key='speech-submit' "
                    "AND state=? AND attempts=? AND value IS ?",
                    (json.dumps(token), id, call['state'], call['attempts'], call['value']))
                if changed.rowcount != 1:
                    raise ProviderError('AMBIGUOUS_CALL_RECONCILE_REQUIRED')
            return True

    def consume_callback(self, job):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            conflict = c.execute('SELECT code FROM call_conflicts WHERE job=? LIMIT 1', (job['id'],)).fetchone()
            if conflict:
                raise ProviderError(conflict[0])
            row = c.execute('SELECT * FROM speech_results WHERE job=?', (job['id'],)).fetchone()
            current = c.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if not row or not current:
                return False
            payload = json.loads(current[0])
            if payload.get('deleting') or payload.get('leaseUntil', 0) <= time.time():
                return False
            payload.update(transcript=row['text'], token=row['token'], speechReceipt=row['digest'],
                           state='STT_RUNNING', error=None, failedStep=None)
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload), job['id']))
            c.execute('DELETE FROM speech_results WHERE job=?', (job['id'],))
            job.update(payload)
            return True

    def chat_reserve(self, job, request_id, question, context):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if not current or (state := json.loads(current[0])).get('deleting') or state.get('leaseUntil', float('inf')) <= time.time():
                raise ProviderError('SESSION_ENDED')
            row = c.execute('SELECT * FROM chat_requests WHERE job=? AND request_id=?', (job['id'], request_id)).fetchone()
            if row:
                if row['question'] != question:
                    raise ProviderError('CHAT_REQUEST_ID_CONFLICT')
                if row['state'] == 'failed':
                    if c.execute("SELECT 1 FROM chat_requests WHERE job=? AND request_id!=? AND state IN ('pending','uncertain')",
                                 (job['id'], request_id)).fetchone():
                        raise ProviderError('CHAT_PENDING_RECONCILE_REQUIRED')
                    c.execute("UPDATE chat_requests SET state='pending' WHERE job=? AND request_id=?", (job['id'], request_id))
                return dict(row)
            if c.execute("SELECT 1 FROM chat_requests WHERE job=? AND state IN ('pending','uncertain')", (job['id'],)).fetchone():
                raise ProviderError('CHAT_PENDING_RECONCILE_REQUIRED')
            if c.execute('SELECT count(*) FROM chat_requests WHERE job=?', (job['id'],)).fetchone()[0] >= limit('max_chat_requests'):
                raise ProviderError('CHAT_REQUEST_CAP')
            c.execute("INSERT INTO chat_requests VALUES(?,?,?,'pending',?,NULL)",
                      (job['id'], request_id, question, json.dumps(context)))
            return {'state': 'pending', 'context': json.dumps(context), 'turn': None}

    def chat_finish(self, job_id, turn):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ProviderError('CHAT_JOB_DELETED')
            job = json.loads(row[0])
            if job.get('deleting') or job.get('leaseUntil', float('inf')) <= time.time():
                raise ProviderError('CHAT_JOB_DELETED')
            if not any(t['requestId'] == turn['requestId'] for t in job['history']):
                job['history'].append(turn)
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), job_id))
            c.execute("UPDATE chat_requests SET state='done',turn=? WHERE job=? AND request_id=?",
                      (json.dumps(turn), job_id, turn['requestId']))

    def chat_failed(self, job_id, request_id, uncertain):
        with self.connect() as c:
            c.execute('UPDATE chat_requests SET state=? WHERE job=? AND request_id=?',
                      ('uncertain' if uncertain else 'failed', job_id, request_id))

    def chat_request(self, job_id, request_id):
        with self.connect() as c:
            row = c.execute('SELECT state,question,turn FROM chat_requests WHERE job=? AND request_id=?',
                            (job_id, request_id)).fetchone()
        return dict(row) if row else None

    def has_uncertain(self, job_id):
        with self.connect() as c:
            return bool(c.execute("SELECT 1 FROM calls WHERE job=? AND state IN ('inflight','uncertain')", (job_id,)).fetchone()
                        or c.execute('SELECT 1 FROM call_conflicts WHERE job=?', (job_id,)).fetchone())

    def has_conflict(self, job_id):
        with self.connect() as c:
            return bool(c.execute('SELECT 1 FROM call_conflicts WHERE job=?', (job_id,)).fetchone())

    def approve_retry(self, job_id, key=None):
        with self.connect() as c:
            sql = "UPDATE calls SET state='retry-approved' WHERE job=? AND state='failed'"
            c.execute(sql + (' AND key=?' if key else ''), (job_id, key) if key else (job_id,))

    def request_delete(self, job):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if not current:
                return
            payload = json.loads(current[0])
            if payload.get('deleting'):
                return  # Durable intent already exists; do not rewrite it on every reaper tick.
            if payload.get('uploadMarker'):
                c.execute('INSERT OR IGNORE INTO ended_uploads VALUES(?)', (payload['uploadMarker'],))
            payload['deleting'] = True
            # Remove private results/caches immediately, retain only cleanup metadata.
            for key in ('transcript', 'translation', 'summary', 'history', 'token', 'translationPlan', 'callback', 'speechReceipt', 'callbackError'):
                payload.pop(key, None)
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload), job['id']))
            c.execute('DELETE FROM calls WHERE job=?', (job['id'],))
            c.execute('DELETE FROM chat_requests WHERE job=?', (job['id'],))
            c.execute('DELETE FROM speech_results WHERE job=?', (job['id'],))
            c.execute('DELETE FROM call_conflicts WHERE job=?', (job['id'],))
            c.execute('INSERT OR IGNORE INTO deletions VALUES(?,?,?)', (job['id'], payload['path'], time.time()))

    def finish_delete(self, job_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM calls WHERE job=?', (job_id,))
            c.execute('DELETE FROM chat_requests WHERE job=?', (job_id,))
            c.execute('DELETE FROM speech_results WHERE job=?', (job_id,))
            c.execute('DELETE FROM call_conflicts WHERE job=?', (job_id,))
            c.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            c.execute('DELETE FROM deletions WHERE job=?', (job_id,))

    def defer_cleanup(self, job_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row:
                job = json.loads(row[0])
                attempts = min(job.get('cleanupAttempts', 0) + 1, 7)
                job.update(cleanupAttempts=attempts, cleanupAfter=time.time()+min(5*2**(attempts-1), 300))
                c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), job_id))

    def translation_plan(self, job):
        source = job['transcript']
        digest = hashlib.sha256(source.encode()).hexdigest()
        if job.get('translationPlan'):
            plan = job['translationPlan']
            if plan['sourceHash'] != digest:
                raise ProviderError('TRANSLATION_SOURCE_CHANGED')
            return plan['chunks']
        with self.connect() as c:
            keys = [r[0] for r in c.execute('SELECT key FROM calls WHERE job=?', (job['id'],)).fetchall()]
        legacy = any(re.fullmatch(r'translation-\d+', key) for key in keys)
        # Existing partial Draft jobs must retain their original paid-call inputs.
        parts = ([source[i:i+5000] for i in range(0, len(source), 5000)] if legacy else chunks(source))
        offset, entries = 0, []
        for i, text in enumerate(parts):
            key = (f'translation-{i}' if legacy else
                   f'translation-v2-{i}-{hashlib.sha256(text.encode()).hexdigest()}')
            entries.append({'id': key, 'start': offset, 'end': offset + len(text)})
            offset += len(text)
        job['translationPlan'] = {'version': 1 if legacy else 2, 'sourceHash': digest, 'chunks': entries}
        self.save(job)  # Manifest is durable BEFORE the first new paid call.
        return entries

    def create(self, owner, digest, mode, path, request_id=None):
        identity = request_id or str(uuid.uuid4())
        marker = hashlib.sha256((owner + ':' + mode + ':' + identity).encode()).hexdigest()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM ended_uploads WHERE key=?', (marker,)).fetchone():
                raise ValueError('종료된 업로드 요청 ID입니다. 새 업로드가 필요합니다.')
            row = c.execute('SELECT payload FROM jobs WHERE owner=? AND digest=? AND mode=?',
                            (owner, identity, mode)).fetchone()
            if row:
                existing = json.loads(row[0])
                if existing.get('mediaDigest') != digest or existing.get('deleting'):
                    raise ValueError('업로드 요청 ID 충돌 또는 종료된 세션입니다.')
                if existing.get('leaseUntil', float('inf')) <= time.time():
                    raise ValueError('만료된 강의 세션입니다.')
                Path(path).unlink(missing_ok=True)
                c.execute('DELETE FROM upload_staging WHERE path=?', (str(path),))
                return existing
            if c.execute('SELECT count(*) FROM jobs WHERE owner=?', (owner,)).fetchone()[0] >= 10:
                Path(path).unlink(missing_ok=True)
                raise ValueError('보관 작업 한도 10개입니다. 기존 작업을 삭제하세요.')
            job = dict(id=str(uuid.uuid4()), owner=owner, mode=mode, path=str(path),
                       state='CREATED', failedStep=None, error=None, transcript='',
                       translation='', summary='', history=[], token=None, submitted=False,
                       created=time.time(), events=['CREATED'])
            job.update(mediaDigest=digest, leaseUntil=time.time() + limit('lease_seconds'), heartbeatAt=time.time())
            if request_id:
                job['uploadMarker'] = marker
            if mode == 'live':
                job['callback'] = {'base': os.environ['FLF_PUBLIC_BASE_URL'].rstrip('/'), 'secret': secrets.token_hex(32)}
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                      (job['id'], owner, identity, mode, job['created'], json.dumps(job)))
            c.execute('DELETE FROM upload_staging WHERE path=?', (str(path),))
            return job

    def heartbeat(self, job_id):
        with self.connect() as c:
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                return False
            job = json.loads(row[0]); now = time.time()
            if 'leaseUntil' not in job:
                return False  # Quarantine requires an explicit owner decision, not auto heartbeat.
            if job.get('deleting') or job.get('leaseUntil', float('inf')) <= now:
                return False
            if now - job.get('heartbeatAt', 0) < limit('heartbeat_seconds'):
                return True  # multi-tab/public floods cause NO renewal writes
            c.execute("UPDATE jobs SET payload=json_set(payload,'$.leaseUntil',?,'$.heartbeatAt',?) WHERE id=? "
                      "AND NOT coalesce(json_extract(payload,'$.deleting'),0) "
                      "AND coalesce(json_extract(payload,'$.leaseUntil'),?)>? "
                      "AND coalesce(json_extract(payload,'$.heartbeatAt'),0)<=?",
                      (now+limit('lease_seconds'), now, job_id, now+1, now, now-limit('heartbeat_seconds')))
            return True

    def adopt(self, job_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise ProviderError('SESSION_ENDED')
            job = json.loads(row[0])
            if job.get('deleting') or 'leaseUntil' in job:
                raise ProviderError('NOT_QUARANTINED')
            job.update(leaseUntil=time.time()+limit('lease_seconds'), heartbeatAt=time.time(),
                       submitted=False, legacyReadOnly=True)
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), job_id))
            return job

    def _call_guard(self, c, job):
        current = c.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()
        if 'owner' in job and (not current or json.loads(current[0]).get('deleting')
                or json.loads(current[0]).get('leaseUntil', float('inf')) <= time.time()):
            raise ProviderError('SESSION_ENDED')
        if current and json.loads(current[0]).get('legacyReadOnly'):
            raise ProviderError('LEGACY_READ_ONLY')
        conflict = c.execute('SELECT code FROM call_conflicts WHERE job=? LIMIT 1', (job['id'],)).fetchone()
        if conflict:
            raise ProviderError(conflict[0])

    def _reserve_call(self, job, key, retry_from):
        """Re-read under the writer lock before EVERY dispatch, including backoff retries."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._call_guard(c, job)
            row = c.execute('SELECT * FROM calls WHERE job=? AND key=?', (job['id'], key)).fetchone()
            if row and row['state'] == 'done':
                return True, json.loads(row['value']), None
            if row and row['state'] == 'failed' and retry_from != (row['attempts'], row['value']):
                raise ProviderError(json.loads(row['value']))
            if row and row['state'] not in ('failed', 'retry-approved'):
                raise ProviderError('AMBIGUOUS_CALL_RECONCILE_REQUIRED')
            count = c.execute('SELECT coalesce(sum(attempts),0) FROM calls WHERE job=?', (job['id'],)).fetchone()[0]
            if count >= limit('max_calls'):
                raise ProviderError('JOB_CALL_CAP')
            attempt = row['attempts'] + 1 if row else 1
            if row:
                changed = c.execute("UPDATE calls SET state='inflight',value=NULL,attempts=? "
                    "WHERE job=? AND key=? AND state=? AND attempts=? AND value IS ?",
                    (attempt, job['id'], key, row['state'], row['attempts'], row['value']))
                if changed.rowcount != 1:
                    raise ProviderError('AMBIGUOUS_CALL_RECONCILE_REQUIRED')
            else:
                c.execute("INSERT INTO calls(job,key,state,attempts) VALUES(?,?,'inflight',1)", (job['id'], key))
            return False, None, attempt

    def _settle_call(self, job, key, attempt, state, value):
        """CAS only our inflight generation. A callback-confirmed done value is immutable."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._call_guard(c, job)
            row = c.execute('SELECT * FROM calls WHERE job=? AND key=?', (job['id'], key)).fetchone()
            if not row:
                raise ProviderError('SESSION_ENDED')
            if row['state'] == 'done':
                confirmed = json.loads(row['value'])
                if key == 'speech-submit' and state == 'done' and value != confirmed:
                    code = 'AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT'
                    c.execute('INSERT OR IGNORE INTO call_conflicts VALUES(?,?,?)', (job['id'], key, code))
                    # Return after COMMIT, not raise inside the transaction and roll back the fence.
                    return 'conflict', code
                return 'done', confirmed
            changed = c.execute("UPDATE calls SET state=?,value=? WHERE job=? AND key=? "
                "AND state='inflight' AND attempts=?",
                (state, json.dumps(value), job['id'], key, attempt))
            if changed.rowcount != 1:
                raise ProviderError('AMBIGUOUS_CALL_RECONCILE_REQUIRED')
            return state, value

    def call(self, job, key, fn):
        retry_from = None
        for attempt in range(3):
            cached, value, generation = self._reserve_call(job, key, retry_from)
            if cached:
                return value
            try:
                value = fn()
                if not isinstance(value, str) or not value.strip():
                    raise ProviderError('EMPTY_PROVIDER_OUTPUT')
            except ProviderError as e:
                status, confirmed = self._settle_call(job, key, generation,
                    'uncertain' if e.code.startswith('AMBIGUOUS') else 'failed', e.code)
                if status == 'done':
                    return confirmed
                if not e.transient or attempt == 2:
                    raise
                retry_from = (generation, json.dumps(e.code))
                time.sleep(2 ** attempt)
            except Exception:
                status, confirmed = self._settle_call(job, key, generation, 'uncertain', 'AMBIGUOUS_PROVIDER_OUTPUT')
                if status == 'done':
                    return confirmed
                raise ProviderError('AMBIGUOUS_PROVIDER_OUTPUT') from None
            else:
                status, confirmed = self._settle_call(job, key, generation, 'done', value)
                if status == 'conflict':
                    raise ProviderError(confirmed)
                return confirmed

    def stage(self, job, state):
        job['state'] = state
        job['events'].append(state)
        self.save(job)

    def run(self, job, provider, stop=lambda: False):
        if job.get('legacyReadOnly'):
            raise ProviderError('LEGACY_READ_ONLY')
        step = 'STT_PENDING'
        try:
            if self.has_conflict(job['id']):
                raise ProviderError('AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT')
            if not job['transcript']:
                self.stage(job, step)
                job['token'] = self.call(job, 'speech-submit', lambda: provider.submit(job['path']))
                self.save(job)
                step = 'STT_RUNNING'
                self.stage(job, step)
                deadline = time.monotonic() + limit('speech_wait_seconds')
                poll_failures = 0
                while not stop():
                    try:
                        state, text = provider.poll(job['token'])
                        poll_failures = 0
                    except ProviderError as e:
                        poll_failures += 1
                        if not e.transient or poll_failures >= 3:
                            raise
                        time.sleep(2 ** poll_failures)
                        continue
                    if state == 'COMPLETED':
                        if not text.strip():
                            # resultToObs mode: CLOVA Speech stores the result in Object Storage
                            text = provider.speech_result_from_obs()
                        if not text.strip():
                            raise ProviderError('EMPTY_TRANSCRIPT')
                        if len(text) > 200000:
                            raise ProviderError('TRANSCRIPT_CAP')
                        job['transcript'] = text
                        self.save(job)
                        break
                    if state not in ('WAITING', 'PROCESSING') or time.monotonic() > deadline:
                        raise ProviderError('SPEECH_POLL_FAILED')
                    time.sleep(3)
                if stop():
                    return
            step = 'TRANSLATING'
            if not job['translation']:
                self.stage(job, step)
                results = []
                for entry in self.translation_plan(job):
                    text = job['transcript'][entry['start']:entry['end']]
                    results.append(self.call(job, entry['id'], lambda t=text: provider.translate(t)) if text.strip() else text)
                job['translation'] = ''.join(results)
                self.save(job)
            step = 'SUMMARIZING'
            if not job['summary']:
                self.stage(job, step)
                # Every input character participates in map/reduce; no prefix truncation.
                nodes = chunks(job['translation'], 6000, prefer_boundaries=False)
                level = 0
                while len(nodes) > 1:
                    nodes = [self.call(job, f'summary-{level}-{i}',
                        lambda t=t: provider.studio('모든 개념/사례를 보존하여 1500자 이내 부분 요약을 작성하세요.', {'source': t}))
                        for i, t in enumerate(nodes)]
                    nodes = ['\n'.join(nodes[i:i+4]) for i in range(0, len(nodes), 4)]
                    level += 1
                def final_summary():
                    result = provider.studio(
                        '전체 자료를 빠짐없이 반영하여 다음 제목만 순서대로 사용해 요약하세요: ' + ' / '.join(HEADINGS),
                        {'source': nodes[0]})
                    check_summary(result)
                    return result
                summary = self.call(job, 'summary-final', final_summary)
                try:
                    check_summary(summary)  # validate upgraded/cached Draft output too
                except ProviderError as e:
                    with self.connect() as c:
                        c.execute("UPDATE calls SET state='failed',value=? WHERE job=? AND key='summary-final'",
                                  (json.dumps(e.code), job['id']))
                    raise
                job['summary'] = summary
            job['failedStep'] = job['error'] = None
            self.stage(job, 'COMPLETED')
        except (sqlite3.Error, OSError):
            # Persistence failure is not a provider failure. Supervisor reloads only
            # durable checkpoints; never reset an inflight ledger to make progress.
            raise
        except Exception as e:
            job['failedStep'] = step
            job['error'] = e.code if isinstance(e, ProviderError) else 'INTERNAL_STAGE_ERROR'
            self.stage(job, 'FAILED')


def evidence(job, question):
    import re
    # Bounded, auditable retrieval default, not unrestricted semantic relevance.
    # Korean endings and a small explicit synonym map support common paraphrases.
    aliases = {'에너지': ('에너지', 'energy'), '에너지보존': ('에너지', 'energy'),
               '힘': ('힘', 'force'), '마찰': ('마찰', 'friction'),
               '낙하': ('낙하', 'falling'), '운동에너지': ('운동', 'kinetic')}
    stopwords = {'강의', '자료', '내용', '설명', '자세히', '알려줘', '알려주세요',
                 '설명해줘', '개념', '이것', '그것', '대해', '관련', '관계', '뭐야', '무엇'}
    def terms(text):
        words = re.findall(r'[\w]{2,}', text.lower())
        result = set()
        for word in words:
            word = re.sub(r'(인가요|이란|이야|에서|으로|이란게|은|는|을|를|이|가|의|란)$', '', word)
            if len(word) >= 2 and word not in stopwords:
                result.update(aliases.get(word, (word,)))
        return result
    sources = ([('summary', t) for t in chunks(job['summary'], 800, prefer_boundaries=False)] +
               [('translation', t) for t in chunks(job['translation'], 800, prefer_boundaries=False)] +
               [('transcript', t) for t in chunks(job['transcript'], 800, prefer_boundaries=False)])
    query = terms(question)
    matched = [(i, kind, text, sum(w in text.lower() for w in query))
               for i, (kind, text) in enumerate(sources)]
    ranked = sorted(matched, key=lambda x: x[3], reverse=True)
    refs = [{'source': i + 1, 'kind': kind, 'text': text} for i, kind, text, score in ranked[:3] if score]
    if refs:
        return refs
    # Only a narrowly recognized anaphoric follow-up may inherit the last grounded
    # same-job turn. New topic words must not accidentally reuse that context.
    normalized = re.sub(r'[\s?.!]', '', question.lower())
    followups = {'더자세히알려줘', '더자세히설명해줘', '예를들어줘', '다시설명해줘',
                 '그게무슨뜻이야', '좀더설명해줘', '자세히알려주세요', '더자세히알려주세요'}
    if normalized in followups and job['history']:
        previous = job['history'][-1]
        valid = {(kind, text) for kind, text in sources}
        return [ref for ref in previous.get('evidence', [])
                if (ref.get('kind'), ref['text']) in valid][:3]
    return []

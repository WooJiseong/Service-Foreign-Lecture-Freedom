import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

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
    lines = result.splitlines()
    titles = [line.strip().lstrip('#').strip() for line in lines]
    if [title for title in titles if title in HEADINGS] != HEADINGS:
        raise ProviderError('SUMMARY_HEADINGS_INVALID')
    positions = [titles.index(heading) for heading in HEADINGS] + [len(lines)]
    for start, end in zip(positions, positions[1:]):
        if not ''.join(lines[start + 1:end]).strip(' \n#-*:_'):
            raise ProviderError('SUMMARY_SECTION_EMPTY')


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
            ''')
            # Old Draft failures did not retain dispatch certainty. Fail closed
            # rather than permitting an upgrade to replay a possibly accepted POST.
            c.execute("UPDATE calls SET state='uncertain' WHERE state='failed' AND value IS NULL")

    def connect(self):
        c = sqlite3.connect(self.db, timeout=30)
        c.execute('PRAGMA max_page_count=' + str(int(os.getenv('FLF_MAX_DB_BYTES', str(64 * 1024 ** 2))) // 4096))
        c.row_factory = sqlite3.Row
        return c

    def save(self, job):
        with self.connect() as c:
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), job['id']))

    def get(self, id):
        with self.connect() as c:
            row = c.execute('SELECT payload FROM jobs WHERE id=?', (id,)).fetchone()
        return json.loads(row[0]) if row else None

    def chat_reserve(self, job, request_id, question, context):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
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
            if c.execute('SELECT count(*) FROM chat_requests WHERE job=?', (job['id'],)).fetchone()[0] >= 20:
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
            return bool(c.execute("SELECT 1 FROM calls WHERE job=? AND state IN ('inflight','uncertain')", (job_id,)).fetchone())

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
            payload['deleting'] = True
            c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload), job['id']))
            c.execute('INSERT OR IGNORE INTO deletions VALUES(?,?,?)', (job['id'], payload['path'], time.time()))

    def finish_delete(self, job_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM calls WHERE job=?', (job_id,))
            c.execute('DELETE FROM chat_requests WHERE job=?', (job_id,))
            c.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            c.execute('DELETE FROM deletions WHERE job=?', (job_id,))

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

    def create(self, owner, digest, mode, path):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload FROM jobs WHERE owner=? AND digest=? AND mode=?',
                            (owner, digest, mode)).fetchone()
            if row:
                Path(path).unlink(missing_ok=True)
                return json.loads(row[0])
            if c.execute('SELECT count(*) FROM jobs WHERE owner=?', (owner,)).fetchone()[0] >= 10:
                Path(path).unlink(missing_ok=True)
                raise ValueError('보관 작업 한도 10개입니다. 기존 작업을 삭제하세요.')
            job = dict(id=str(uuid.uuid4()), owner=owner, mode=mode, path=str(path),
                       state='CREATED', failedStep=None, error=None, transcript='',
                       translation='', summary='', history=[], token=None, submitted=False,
                       created=time.time(), events=['CREATED'])
            c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',
                      (job['id'], owner, digest, mode, job['created'], json.dumps(job)))
            return job

    def call(self, job, key, fn):
        with self.connect() as c:
            row = c.execute('SELECT * FROM calls WHERE job=? AND key=?', (job['id'], key)).fetchone()
            if row and row['state'] == 'done':
                return json.loads(row['value'])
            if row and row['state'] in ('inflight', 'uncertain'):
                raise ProviderError('AMBIGUOUS_CALL_RECONCILE_REQUIRED')
            if row and row['state'] == 'failed':
                # Infra recovery must not redispatch a known failed request (e.g.
                # bad credentials). Only explicit API retry grants approval.
                raise ProviderError(json.loads(row['value']))
            count = c.execute('SELECT coalesce(sum(attempts),0) FROM calls WHERE job=?', (job['id'],)).fetchone()[0]
            if count >= 200:
                raise ProviderError('JOB_CALL_CAP')
        for attempt in range(3):
            with self.connect() as c:
                count = c.execute('SELECT coalesce(sum(attempts),0) FROM calls WHERE job=?', (job['id'],)).fetchone()[0]
                if count >= 200:
                    raise ProviderError('JOB_CALL_CAP')
                c.execute("INSERT INTO calls(job,key,state,attempts) VALUES(?,?,'inflight',1) "
                    "ON CONFLICT(job,key) DO UPDATE SET state='inflight', attempts=attempts+1", (job['id'], key))
            try:
                value = fn()
                if not isinstance(value, str) or not value.strip():
                    raise ProviderError('EMPTY_PROVIDER_OUTPUT')
            except ProviderError as e:
                with self.connect() as c:
                    c.execute('UPDATE calls SET state=?,value=? WHERE job=? AND key=?',
                        ('uncertain' if e.code.startswith('AMBIGUOUS') else 'failed', json.dumps(e.code), job['id'], key))
                if not e.transient or attempt == 2:
                    raise
                time.sleep(2 ** attempt)
            except Exception:
                # Unexpected parsing/shape errors after dispatch also fail closed.
                with self.connect() as c:
                    c.execute("UPDATE calls SET state='uncertain' WHERE job=? AND key=?", (job['id'], key))
                raise ProviderError('AMBIGUOUS_PROVIDER_OUTPUT') from None
            else:
                with self.connect() as c:
                    c.execute("UPDATE calls SET state='done',value=? WHERE job=? AND key=?",
                              (json.dumps(value), job['id'], key))
                return value

    def stage(self, job, state):
        job['state'] = state
        job['events'].append(state)
        self.save(job)

    def run(self, job, provider, stop=lambda: False):
        step = 'STT_PENDING'
        try:
            if not job['transcript']:
                self.stage(job, step)
                job['token'] = self.call(job, 'speech-submit', lambda: provider.submit(job['path']))
                self.save(job)
                step = 'STT_RUNNING'
                self.stage(job, step)
                deadline = time.monotonic() + 7200
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

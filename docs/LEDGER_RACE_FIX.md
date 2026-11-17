# Re-review B1 — callback-confirmed ledger race correction

> 최신 범위: 사용자가 환경변수 예제 파일 요구를 철회했다. 아래 missing-file/xfail/pending은
> 각 기록 당시 상태로 보존한다. 권한 수정/파일 생성 성공이 아니라 요구 철회로 해당 차단이
> 해소됐으며 이전 B1/lifecycle scoped PASS handoff와 최종 변경 검토는 [현재 상태](CURRENT_STATUS.md) 참조.

> 후속 상태: 사용자는 이전 B1/lifecycle scoped source review PASS를 handoff했다.
> 아래 테스트/당시 pending 설명은 과거 기록으로 보존한다. 현재 root `.env.example`는
> 권한 갱신 후 정상 추가 재시도도 거부되어 별개 delivery BLOCKED다.
> 최신 증거: [ENV_PERMISSION_RECHECK](ENV_PERMISSION_RECHECK.md).

## Status boundary

- Requester reports prior source corrections PASS except HIGH B1. This file records the new
  local correction; it does not declare an independent re-review PASS for B1.
- Missing root `.env.example` is a separate **delivery BLOCKED** item: the actual edit denial
  remains. No edit attempt, alternate write, rename, or permission/policy change was made.
- Branch `draft/flf-runnable`, existing HEAD `e3e8263544877bbed5c4ec6a90284ebaee3212ef`.
  No commit/push/PR/YouTrack write, live/paid call, or host activation.

## Ledger invariants and implementation

`core.Store.call` now uses two explicit transactional boundaries:

1. `_reserve_call`: BEGIN IMMEDIATE, re-read job/conflict fence and call state before **every**
   dispatch, including each transient retry. `done` returns its immutable cached value before
   checking attempt budget. `inflight`/`uncertain` cannot be overwritten. A transient retry may
   reserve only its own failed attempt/value pair; explicit `retry-approved` remains supported.
   Reservation uses state/attempt/value CAS, not unconditional upsert. No SQLite lock is held
   during provider network I/O or retry sleep.
2. `_settle_call`: BEGIN IMMEDIATE, re-read the ledger and finalize only the reserved inflight
   attempt via conditional UPDATE. A callback-confirmed `done` wins over a transient error,
   ambiguous error, or unexpected exception; none can downgrade it or increase attempts.
   Matching success acknowledgement also leaves that row unchanged.

`accept_callback` uses conditional state/attempt/value CAS when confirming an unconfirmed call;
an already-done value is token-checked and never rewritten. Callback result/terminal status and
ledger confirmation commit together. FAILED/TIMEOUT callbacks retain their terminal payload
even if the still-returning submission reports 429; no further invocation is dispatched.

If the late submit success ack contains a different token from callback confirmation, the canonical
`calls` row remains done with the original token and attempts. A separate durable `call_conflicts`
fence commits `AMBIGUOUS_SPEECH_ACK_TOKEN_CONFLICT`. Only the code is stored, not the conflicting
ack token/body. The job visibly fails closed; retry approval cannot clear the fence, the worker
does not resume it, and pending callback results cannot be consumed through it. The fence survives
Store/process restart. Reconciliation requires separate administrator/provider review; there is no
unsafe clear/replay endpoint in this iteration. Explicit end/TTL clears the private queue, ledger
and conflict metadata as part of the existing deletion policy.

An already-reserved/in-flight HTTP request cannot be recalled by SQLite. The guarantee is that
a callback confirmation committed before the next reservation prevents redispatch, and that any
later completion cannot overwrite confirmed ledger state. It is not a promise to undo provider
acceptance or refund calls that were already sent.

## Legacy adoption contract (no silent reset/resume)

Chosen conservative disposition: **read existing results / end only**.
`Store.adopt` adds a temporary lease and `legacyReadOnly=true`, sets submitted=false, but retains
state, failedStep, tokens, content and ambiguous ledger checkpoints. UI labels the preserved state
as not currently processing, hides retry and disables new questions. API submit/retry/chat and
worker/provider dispatch reject read-only legacy jobs. `Store.save` cannot silently overwrite them;
direct `Store.run` also refuses without changing the checkpoint. Heartbeat/ownership/result reads
and explicit end remain available. No authorized checkpoint-resume feature is implemented or
implied. A new upload is an independent session and may create new billable work; it is not a
resume or a way to reconcile the old provider request.

## New regressions

`tests/test_callback_ledger_race.py` covers:

- Early COMPLETED callback followed by transient 429: one invocation, one attempt, immutable done,
  callback consumed, restart/cached replay causes no dispatch.
- Early callback followed by unexpected exception: no downgrade to uncertain.
- Matching ack leaves callback confirmation unchanged.
- Early terminal FAILED and TIMEOUT callbacks followed by transient 429: one attempt, terminal
  state/token preserved, no automatic or explicit retry replay.
- Callback arrival during retry backoff: next reservation re-reads done, even at the call cap.
- Conflicting ack token: canonical ledger unchanged, durable explicit conflict, no overwrite,
  no retry/consume/worker bypass after restart; explicit end removes the conflict.
- Concurrent reservation cannot replace another inflight attempt.
- Legacy adoption across CREATED/STT_RUNNING/TRANSLATING/SUMMARIZING/FAILED/COMPLETED preserves
  results/checkpoints/ambiguity and rejects every resume/new-chat path.

All provider delivery/acknowledgement behavior is mocked. Existing deployment, budget, real callback
delivery and legacy administrator disposition approval gates in REVIEW_BLOCKERS.md still apply.

## Actual local testing — 2026-11-17

Commands run from `/root/uos-project/FLF_Project`:

```bash
FLF_DATA=/tmp/opencode/flf-test-bootstrap /tmp/opencode/flf-iteration-venv/bin/python -m pytest -q tests/test_callback_ledger_race.py
FLF_DATA=/tmp/opencode/flf-test-bootstrap /tmp/opencode/flf-iteration-venv/bin/python -m pytest -q
/tmp/opencode/flf-iteration-venv/bin/python tests/smoke_server.py
node tests/test_chat_transport.js
node tests/test_frontend_storage.js
node tests/test_session_lifecycle.js
node --check static/app.js
node --check static/chat_transport.js
/tmp/opencode/flf-iteration-venv/bin/python -m compileall -q app.py core.py providers.py config.py media_runner.py
git diff --check
python -m detect_secrets scan app.py core.py static/app.js tests/test_callback_ledger_race.py tests/test_session_lifecycle.js README.md docs/LEDGER_RACE_FIX.md docs/REVIEW_BLOCKERS.md
```

- Targeted B1/legacy suite: **14 passed, 1 warning, 11.39s**.
- Final full pytest: **159 passed, 1 xfailed, 1 warning, 89.08s**.
  - xfail is only the missing root `.env.example` delivery blocker; no edit/retry/bypass.
  - warning is the existing Starlette TestClient/httpx deprecation, not a failure.
- Actual uvicorn/demo HTTP smoke: **PASS**, including synthetic `.env` loading/shell precedence,
  CREATED/completed restart recovery, explicit submission/stages/chat/delete. No paid API call.
- Three Node suites: **PASS**. Lifecycle assertions now also check the read-only legacy UI notice,
  disabled new questions and hidden retry. Node syntax and Python compile checks: exit **0**.
- Whitespace diff check: exit **0**. Targeted detect-secrets 1.5.0 scan: **`results: {}`**.
  No new allowlist entry was needed, and real/ignored `.env` or user data was not scanned.

The first full run after the CAS change reported 157 passed / 2 failed / 1 xfailed: end/TTL during
inflight chat returned 502 instead of the established 410. The earlier CAS guard correctly detected
SESSION_ENDED; app.chat now maps that code to HTTP 410. The existing tests were not weakened.
After that code correction, the full suite and separately invoked smoke passed as recorded above.

Developer-local checks are not independent review approval. Prior corrections' source PASS is
requester-reported; **this B1 correction still awaits independent re-review**. Delivery remains
blocked solely on the known missing `.env.example` file (separate from source-review status), and
operational/live/budget/legacy-disposition approval gates remain pending. New commit: none.

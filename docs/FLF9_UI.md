# FLF-9 local UI implementation / evidence

## Source and scope

Confirmed PM handoff: [FLF-9](https://woojiseong.youtrack.cloud/issue/FLF-9),
`[UI/UX 디자인 설계] 1차 디자인 구현명세`, body v1.0, author admin,
updated 2026-11-17 05:59:34, zero comments/attachments (metadata supplied by user).
No YouTrack MCP was available; this is the confirmed handoff source, not a claim of
independently fetching the issue. No authoritative article was changed.
The FLF-9 direction supersedes the visible three-tab/“Transition” UI for this frontend only:
the button says **Translate**, while internal `translation`/`transcript` keys are unchanged.
Server `translationLabel` remains a legacy compatibility field, unused by this UI.

This worktree is on branch `draft/flf-runnable`, HEAD `996ba5f500ce5a5c44fb9664bc642679c10e3bb6`,
with local uncommitted changes. `static/index.html`, `static/style.css`, `static/app.js` and
tests implement the UI. `static/chat_transport.js` is unchanged. `app.py` adds only the
public `retryAllowed` hint. Retry POST still independently validates durable fences. No
provider protocol, storage schema, callback CAS, deletion worker, reaper, credential,
policy, or deployment change. The seven-format accept/extension list is the confirmed fixed
contract, not a server-config value; byte/second limits remain server-driven.

## TEMPORARY_DECISION (non-authoritative technical defaults)

- Original FLF mint palette (`#f3fbf7`, `#15664e`), system font, rounded 18–24px cards,
  1240px container, 760px stacked breakpoint; no external font/asset/network dependency.
- The confirmed seven-format accept/extension list is fixed in the upload UI. `/api/session`
  supplies byte/second/heartbeat limits, which drive the displayed limits and browser-side
  size check. Media signature, codec, actual duration, and final size remain server-validated.
- Results start at **Summary** and cycle locally `Summary → Origin → Translate → Summary`.
  The result text is scrollable/selectable; type is conveyed by both text and color.
  No tab widgets, no percent progress, and no fake timers.
- DEMO disclosure is repeated in the shared header, processing status, result view, and
  demo AI bubble label. The fixed demo is never presented as real recognition/translation/
  summary output. Papago attribution appears only for Translate and explicitly says the
  demo does not use the Papago API.
- Failure causes map to short Korean explanations while retaining the raw error code.
  Retry is hidden for deterministic auth/4xx, empty transcript, transcript cap, uncertain/
  ambiguous reconciliation, and server-disallowed/legacy states. `CREATED` offers only
  “처리 제출 재확인”. Actual retry authority remains server-side.
- Polling is 1500ms. Three consecutive poll failures stop automatic polling and expose a
  manual status recheck. Polling stops on `COMPLETED`, quarantine, legacy read-only state,
  or no selected job. A 404/410 poll returns to upload with an explicit expiration reason.
- Every API call has a 25-second client transport deadline. It does not cancel server work
  or invent provider failure. Unconfirmed upload/chat intent keeps its stable request ID.
- Refresh uses one owner-list snapshot to restore the stored active job, then one immediate
  heartbeat. It does not issue a duplicate job GET. With no stored ID it may select the
  first non-quarantined owned job; an explicitly stored but missing/expired ID never
  silently switches to another lecture. Quarantined jobs are not auto-adopted. Stale
  active-job and upload-attempt keys are cleared, including when the selected job expires.
- Only the selected visible session receives this tab’s heartbeat. Explicit
  **처음으로/새 강의 시작** asks confirmation, calls `/end`, then clears local selection,
  consent, draft, and upload intent. Cancel/failure preserves the session; pending
  external cleanup is disclosed. New lecture cannot leave the previous selected heartbeat
  running. Reaper/expiry behavior is unchanged.
- Chat uses unchanged stable-intent transport/reconciliation. Pending/error bubbles belong
  to their lecture; late responses cannot populate another one. Enter sends except during
  IME composition; Shift+Enter inserts a newline. Startup/runtime storage failure blocks
  live chat before POST; demo may use in-memory intents. Non-chat metadata can fall back to
  memory.
- History follows new messages only when already within 80px of the bottom; otherwise the
  prior scroll offset is retained. View changes focus the destination heading. Live status,
  `aria-live`, labels, hidden-view semantics, visible focus, and reduced-motion handling are
  present.
- The visible A-1/FLF-9 tab-wording conflict is recorded here only. The authoritative A-1
  articles and policy documents were not edited.

## Test mapping (areas, not fabricated acceptance IDs)

The handoff names the ranges `AC-UI-01`–`AC-UI-20` and `UX-T01`–`UX-T14`, but does not
provide their individual wording/number mapping in the supplied handoff. The table maps
implementation areas to executable evidence; it does **not** claim all 20 AC/14 UX items
were individually verified. PM/reviewer should reconcile exact IDs against the issue.

| Handoff area | Executable local evidence |
|---|---|
| Upload-only initial view, no old-job list/tabs, semantic headings, live labels, focus/reduced-motion CSS contracts | `tests/test_flf9_contract.py`; `tests/test_acceptance.py::test_result_cycle_read_only`; `tests/test_pm_acceptance.py::test_ac12_papago_official_text_fallback_and_link_on_result_screen` |
| Seven formats, server-driven limits, single drag/drop, invalid/empty/size, consent, no upload on selection | `tests/test_flf9_ui.js`; `tests/test_flf9_contract.py`; `tests/smoke_server.py` |
| Delayed upload double-click, stable retry ID, independent new lecture, cancel/end | `tests/test_flf9_ui.js`; `tests/test_session_lifecycle.js` |
| Actual stages, no fake progress, failure stage/cause, retry fences, ambiguous reconciliation, bounded polling, actual completion routing | `tests/test_flf9_ui.js` |
| Summary default, current-label cycle/order, zero requests while switching, Papago text/link, demo result disclosure | `tests/test_flf9_ui.js`; `tests/test_pm_acceptance.py` |
| Chronological bubbles, pending/error, Enter/Shift/IME, blank/pending guards, timeout release, stable intent | `tests/test_flf9_ui.js`; unchanged `tests/test_chat_transport.js` |
| Switching preserves chat, late cross-job reply ignored, reader-safe scroll, runtime storage fail-closed | `tests/test_flf9_ui.js`; `tests/test_frontend_storage.js` |
| Refresh/visibility/selected heartbeat, one-list restore, no duplicate job GET, legacy/quarantine fences, expired ID, cache cleanup | `tests/test_session_lifecycle.js` |
| Real media verification, stage persistence, summary/context isolation, insufficient-evidence answer, ledger CAS, durable deletion/reaper | full existing Python suite; `tests/smoke_server.py` isolated real HTTP demo |

The mock DOM executes production handlers; it is **not a browser**. It cannot prove pixel
layout, actual horizontal overflow, native selection/copy, native file-picker drag/drop,
real IME timing, browser focus behavior, screen-reader announcements, or viewport screenshots.
Chromium/Chrome/Firefox and Playwright/Puppeteer are not installed; no external installation
was attempted. Live provider quality and paid calls were not tested.

## Local execution record

Final full Python regression, isolated dotenv-disabled demo environment and temporary data:

```bash
env -i PATH=/root/venv/bin:/usr/local/bin:/usr/bin:/bin \
  PYTHON_DOTENV_DISABLED=1 FLF_MODE=demo \
  python -c 'import os,subprocess,sys,tempfile; tmp=tempfile.TemporaryDirectory(prefix="flf9-final-",dir="/tmp/opencode"); result=subprocess.run([sys.executable,"-m","pytest","-q"],env={**os.environ,"FLF_DATA":tmp.name}); tmp.cleanup(); sys.exit(result.returncode)'
```

Result: **166 passed in 89.53s**. One earlier full run failed only the stale
`test_pm_acceptance` assertion that hard-coded `<h2>강의 질문`; the test now checks the
preserved semantic order via `id="chat-heading"`, with no assertion removed. Final run green.

Final Node regression chain:

```bash
node tests/test_chat_transport.js && \
node tests/test_frontend_storage.js && \
node tests/test_session_lifecycle.js && \
node tests/test_flf9_ui.js
```

Result: all PASS, including stable lost-response replay, storage fail-closed, lifecycle/
expiry/legacy fences, upload-only stages, configured format/limit display, terminal poll
stop, and one-call refresh restore.

Real HTTP smoke:

```bash
env -i PATH=/root/venv/bin:/usr/local/bin:/usr/bin:/bin \
  PYTHON_DOTENV_DISABLED=1 FLF_MODE=demo python tests/smoke_server.py
```

Result: PASS. It copies source into a synthetic temporary sandbox, runs demo on an ephemeral
port, checks real uvicorn/.env precedence, health/UI/assets/upload, CREATED restart, explicit
submit, all stages, demo chat, completed restart and deletion, then tears down. It does not
read the project’s real `.env` or data.

Syntax/compile and hygiene checks:

```bash
python -m compileall -q app.py core.py providers.py config.py media_runner.py tests/test_flf9_contract.py
node --check static/app.js && node --check static/chat_transport.js
node --check tests/frontend_harness.js && node --check tests/test_flf9_ui.js
git diff --check
```

Result: `SYNTAX_OK`, `DIFF_CHECK_OK`. A targeted local heuristic scan of the tracked diff
and expected untracked additions found **0 matches** for private-key blocks, GitHub/AWS/
OpenAI-style token prefixes, and long direct assignments to the provider secret-variable
names. This is not a full security audit. No diff was sent to a remote scanner.

`ss -ltnp` found **no listener on port 10000**. Temporary smoke/test servers were torn down.
No real `.env` exists at project root; `.env` is ignored by `.gitignore` and is not tracked.
No project data or credential file was read or modified.

No browser test, screenshot, independent review, live acceptance, YouTrack write, Git
commit, push, or PR operation is claimed. PM owns tracking; publication remains pending.

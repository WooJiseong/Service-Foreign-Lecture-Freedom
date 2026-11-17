# Review blocker correction — actual local test evidence

> Historical results: the recorded 145 passed / 1 xfailed run is unchanged. The user subsequently
> withdrew the environment-example deliverable; that missing-file requirement is no longer a
> current blocker. This is a scope withdrawal, not a permission fix or an alternative template.
> See [CURRENT_STATUS](CURRENT_STATUS.md) for current source-review/delivery/live boundaries.

2026-11-17, branch `draft/flf-runnable`, unchanged HEAD
`e3e8263544877bbed5c4ec6a90284ebaee3212ef`. No commit, push, PR, YouTrack write,
paid/live provider call, or host infrastructure activation. This is developer validation,
not an independent reviewer PASS. `.env.example` remains blocked by the actual edit denial;
no retry, alternate name/tool write, or permission configuration change was attempted.

## Final commands/results

Run from `/root/uos-project/FLF_Project`:

```bash
FLF_DATA=/tmp/opencode/flf-test-bootstrap /tmp/opencode/flf-iteration-venv/bin/python -m pytest -q
/tmp/opencode/flf-iteration-venv/bin/python tests/smoke_server.py
node tests/test_chat_transport.js
node tests/test_frontend_storage.js
node tests/test_session_lifecycle.js
node --check static/app.js
node --check static/chat_transport.js
/tmp/opencode/flf-iteration-venv/bin/python -m compileall -q app.py core.py providers.py config.py media_runner.py
git diff --check
```

- pytest: **145 passed, 1 xfailed, 1 warning in 76.98s** (final rerun, including non-ASCII callback secret/token rejection).
  - xfail: missing root `.env.example`, strict expected failure for the known permission blocker.
    Not a successful delivery or a passed test.
  - warning: Starlette TestClient/httpx deprecation; no dependency upgrade was invented to hide it.
- HTTP smoke: **PASS**. Actual uvicorn synthetic `.env` loading and shell precedence,
  HTTP health/UI/assets/upload, CREATED restart, explicit submit, demo stages/chat,
  completed restart and deletion. No project `.env` or existing data copied/read for the smoke.
- All three Node regression suites: **PASS**. Transport response loss/uncertainty,
  browser storage failures, immediate/visibility heartbeat, upload identity,
  explicit end/multitab cache cleanup, and no auto-adoption of legacy quarantine.
- Both Node syntax checks, Python compilation, whitespace diff check: exit **0**.

Earlier correction runs are not hidden: the first full run after adding bounds/cleanup/callback
had 106 passed, 2 failed, 1 xfailed (legacy heartbeat auto-adoption expectation and missing new
README variable entries). Explicit adoption and documentation corrected those failures.
The reviewer-blocker test file initially passed 36 tests before adding restart coverage;
the subsequent full suite passed 144, then final 145 after the new callback restart test.

## New regression evidence

`tests/test_review_blockers.py` exercises:

1. A real subprocess calls `app.save_upload`, commits staging, creates/fsyncs media, then
   `os._exit(73)` at the pre-job validation boundary. Actual app startup in a second process
   removes the orphan and intent, while preserving a valid job/file and unregistered legacy file.
2. A currently active validator retains its staging file/reservation during reconciliation.
3. Processing worker A blocks inside mocked STT polling; independently expired B's local file,
   external mock objects and DB tombstone finish deletion **before A is released**.
4. End B while a simulated historical PUT is in flight under the per-job guard. The tombstone
   cannot finalize early; a late PUT completion cannot restore local results, and the independent
   cleanup worker removes the recreated external object after the guard releases. New production
   jobs no longer issue that redundant PUT.
5. Official async params require callback; new live jobs receive authenticated callbacks, not
   polling as a substitute. No OBS upload/output copies or generic unused GET are added.
6. Callback body/token/capability validation; no-cookie/provider delivery; duplicate/conflicting
   delivery; callback before an ambiguous submit ack; persisted callback across Store restart;
   no result injection before dispatch; FAILED/TIMEOUT without automatic rebilling.
7. Oversized callback rejection and end during delivery: late results are discarded, not resurrected.
8. Repeated heartbeat requests cause zero early writes; concurrent renewals change the DB only
   once per interval (asserted using actual SQLite `total_changes`, not just HTTP responses).
9. Every numeric safe upper bound, minimums and queue/storage/wait cross-limits reject invalid config.
10. Mock streamed provider bodies enforce header/chunked size caps before JSON; compressed responses
    are rejected after requesting identity encoding, avoiding a transparent decompression bomb.
11. Static Nginx streaming, retry-off, rate zones/limits, temp path and callback URI privacy contract.

Existing tests were adapted honestly: canonical names/model/dotenv regression coverage remains;
old redundant Object Storage PUT expectations were replaced by legacy cleanup and no-copy assertions;
HTTP uncertainty tests now mock the streaming transport boundary.

## Secret scan

```bash
python -m detect_secrets scan app.py core.py providers.py config.py service.yaml README.md requirements.txt static/app.js static/index.html tests/test_iteration.py tests/test_review_blockers.py tests/test_acceptance.py tests/test_contracts.py tests/test_pm_acceptance.py tests/test_review_regressions.py tests/smoke_server.py tests/test_session_lifecycle.js deploy/nginx.conf.example deploy/access-evaluator.conf.example deploy/access-public.conf.example deploy/flf.service.example deploy/RUNBOOK.md docs/REVIEW_BLOCKERS.md docs/REVIEW_BLOCKERS_TESTS.md docs/ITERATION_DECISIONS.md docs/ITERATION_TESTS.md
```

detect-secrets 1.5.0 final result: **`results: {}`**. The first new scan flagged the literal
synthetic callback fixture in `test_review_regressions.py`; that noncredential test line alone
received an explanatory allowlist pragma. The pre-existing synthetic dotenv fixture allowlist
remains. Real/ignored `.env`, user data and external credential files were not scanned.

## Detailed outstanding gates

- Independent re-review and PM acceptance/tracking remain pending; no reviewer FAIL was externally
  changed to PASS. The new callback path requires PM/reviewer confirmation of the chosen single
  receiving path; the canonical names and YAML/dotenv precedence remain unchanged.
- `.env.example` is still absent due permission denial. Its test remains xfail.
- Real provider callback payload/delivery/retry behavior, public HTTPS reachability, safe callback
  logging at every proxy/APM, Ncloud legacy version-delete compatibility/permissions remain unverified.
- Evaluator allowlist versus provider callback ingress requires approved verified provider CIDRs
  or a separately approved ingress arrangement. No guessed CIDRs or unauthorized public port opening.
- Public-IP trusted certificate issuance/renewal, Nginx actual syntax/streaming/quota/rate behavior,
  firewall/ACG, nonroot systemd activation and tmpfs quota/crash cleanup require administrator approval
  and deployment tests. Only configuration templates/static contracts were tested locally.
- Numeric lease 180s/heartbeat 30s/reaper 0.5s, cleanup poll/backoff, rate/burst and temp quotas remain
  TEMPORARY_DECISION, not approved numbers or a monetary budget. No paid testing is authorized.
- Legacy lease-less data is quarantined, not deleted. Explicit owner adoption is implemented;
  administrator disposition of orphaned ownership/unregistered files needs review/approval of
  the plan in REVIEW_BLOCKERS.md. A complete session-only migration is **not** claimed.
- External cleanup is independent of inference but serial within its own worker; a slow storage
  deletion may delay another deletion. Durable retry/backlog observability exists, but deployment
  monitoring/alerting and provider-owned retention are not proven or promised zero-retention.

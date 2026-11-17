# FLF 로컬 Draft — 현재 범위와 출판 상태

## 명시적 범위 변경

사용자 지시: **“그럼 git에서 환경변수 예시 자체를 빼고 진행하자”**.
환경변수 예제/템플릿 파일의 생성·Git 포함 요구를 철회했다. 다른 파일명이나 README의
복사용 env 블록으로 대체하지 않는다. 변수 이름/목적/설정 우선순위 문서는 계속 제공한다.
실제 `.env`는 사용자가 안전하게 수동 준비하고 Git에서 제외하며 에이전트는 열람/작성하지 않는다.

과거 누락 파일 차단은 **이 명시적 범위 변경으로 해소**되었다. 편집 권한이 수정되어 파일 생성에
성공한 것이 아니며 이전 permission denial 기록은 사실대로 보존한다. 없어진 파일 요구의
strict xfail은 제거하고, publication 후보에 환경 예제/실제 `.env`/runtime 자료가 없고 `.env`가
ignored이며 README가 수동 준비·실제 로딩을 정직하게 안내하는 양성 테스트로 대체했다.

## 구현/검증 경계

- 기존 frontend/backend/AI adapter, staging, 세션 lease/삭제, callback 수신 및 B1 CAS 로직은
  이번 범위 변경에서 변경하지 않았다. 사용자 handoff는 이전 B1/lifecycle scoped review PASS를
  보고한다. 이번 README/테스트/범위 기록 변경은 Reviewer/PM의 최종 확인 대상이다.
- `.env`는 루트에서 python-dotenv로 로드하며 프로세스 > .env. 한도는 env > YAML > 기본값,
  모델은 YAML 역할별 값 > 공통 env fallback > HCX-005. 실제 synthetic 파일 격리 검증은 유지.
- Speech/Papago/Studio와 공개 callback base origin은 live 준비 사항이다. OBS의 기능적 용도는
  legacy 정리이지만 **현재 live 시작 검증은 OBS 변수도 전부 필수**이며 이 동작은 바꾸지 않았다.
- 예산/유료 호출 승인 없음. 숫자 lease/rate/quota 등은 TEMPORARY_DECISION 유지.
- 실제 live callback/AI 품질/OBS 삭제 호환성, HTTPS ingress/공인 IP TLS 자동갱신, ACG/방화벽,
  systemd 활성화/호스트 quota/외부 접근 검증은 **LIVE NOT_VERIFIED**다.
- lease 없는 구 데이터는 보존 격리, 명시 채택은 기존 결과 조회/종료 전용. 관리자 처분은 승인 대기.

## 출판 계획 (아직 실행하지 않음)

브랜치 `draft/flf-runnable`, 기존 HEAD `e3e8263544877bbed5c4ec6a90284ebaee3212ef`.
스테이징/새 커밋/푸시/PR/YouTrack 쓰기 없음. 이전 승인은 이전 SHA에만 해당하며 새 변경의
publication 승인이 아니다. Reviewer/PM 최종 확인 및 **새 런타임 사용자 승인** 후에만
의도한 source/config/test/project docs를 검토·stage·commit하고 원격 쓰기는 별도 승인받는다.

제안 subject: `feat(FLF-2): apply session decisions and environment configuration`.

환경 예제·실제 .env·credential·runtime data·agent policy·OpenCode 설정·복사한 권위 SRS는
publication 대상이 아니다. 앱의 service.yaml/config.py는 비밀 없는 실행 설정/로직으로 유지한다.
과거 권한 진단 문서는 historical audit로만 보존하며 현재 setup 지침의 대체물이 아니다.

## 과거 실행 기록 — 현재 결과로 바꿔 쓰지 않음

|기록|실제 과거 결과|
|---|---|
|ITERATION_TESTS.md|104 passed, 1 xfailed, 1 warning, 62.28s|
|REVIEW_BLOCKERS_TESTS.md|145 passed, 1 xfailed, 1 warning, 76.98s|
|LEDGER_RACE_FIX.md|159 passed, 1 xfailed, 1 warning, 89.08s|
|ENV_PERMISSION_RECHECK.md|159 passed, 1 xfailed, 1 warning, 88.82s|

당시 xfail은 실제 누락 요구를 나타냈다. 이번에는 그 요구가 철회되어 해당 acceptance 검사를
대체하는 것이며, 당시 실행 결과가 xfail 없이 통과했던 것처럼 수정하지 않는다.

## 이번 범위 변경 후 실제 검증 — 2026-11-17

프로젝트 루트에서 실행한 명령:

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
git status --short --untracked-files=all
```

- pytest: **162 passed, 1 warning in 88.92s**, xfail/skip 없음.
  기존 Starlette TestClient/httpx deprecation 경고 1건은 숨기거나 의존성을 임의 변경하지 않았다.
- 기존 strict missing-file xfail 1개를 철회하고 양성 검사 3개로 대체:
  publication Git metadata에 환경 예제/실제 .env/runtime 자료 없음, 실제 .env ignore,
  README 수동 준비/변수 이름/실제 우선순위/launch 및 비복사형 안내 확인.
  실제 `.env`를 열어 검사하지 않는다.
- 실제 uvicorn/demo HTTP smoke **PASS**: 격리 synthetic .env 로딩/셸 우선순위, HTTP UI/assets,
  업로드/명시 제출/데모 처리/채팅, CREATED·완료 재시작 복구, 삭제. 유료 API 호출 아님.
- Node 세 suite, Node syntax 두 파일, Python compile 다섯 파일, diff whitespace 모두 **PASS / exit 0**.
- `git check-ignore -v --non-matching .env`는 `.gitignore:5:.env` 적용을 확인했다.
  Git 후보 inventory에는 DB/media/log/cache/실제 env/agent/OpenCode 설정이 없다.
  ignored 사용자 data의 내용을 열거나 비교했다는 뜻은 아니다.
- Source/requirements/service.yaml/CAS/lifecycle의 추가 변경 없이 기존 회귀를 재실행했다.

변경 파일 한정 secret scan 명령(실제 .env/ignored data 제외):

```bash
python -m detect_secrets scan README.md app.py core.py providers.py config.py requirements.txt service.yaml static/app.js static/index.html deploy/RUNBOOK.md deploy/nginx.conf.example deploy/access-evaluator.conf.example deploy/access-public.conf.example deploy/flf.service.example tests/smoke_server.py tests/test_acceptance.py tests/test_contracts.py tests/test_pm_acceptance.py tests/test_review_regressions.py tests/test_callback_ledger_race.py tests/test_iteration.py tests/test_review_blockers.py tests/test_session_lifecycle.js docs/ITERATION_DECISIONS.md docs/ITERATION_TESTS.md docs/LEDGER_RACE_FIX.md docs/REVIEW_BLOCKERS.md docs/REVIEW_BLOCKERS_TESTS.md docs/ENV_PERMISSION_RECHECK.md docs/CURRENT_STATUS.md
```

실제 결과: detect-secrets **1.5.0**, 변경/새 파일 30개 대상 **`results: {}`**.
기존 synthetic fixture allowlist만 유지했으며 새 allowlist나 credential 파일 스캔은 없다.

## Pending commit diff summary

HEAD 대비 추적 파일 수정 14개 + 미추적 새 파일 16개 = **30개**. stage/commit 없음.
기존 반복의 전체 변경을 포함하며 이번 추가 기능이 30개라는 뜻은 아니다.

|영역|현재 전체 변경 경로|
|---|---|
|실행/설정|app.py, core.py, providers.py, config.py, requirements.txt, service.yaml|
|프런트엔드|static/app.js, static/index.html|
|배포 예시/실행 안내|deploy/RUNBOOK.md, deploy/nginx.conf.example, deploy/access-evaluator.conf.example, deploy/access-public.conf.example, deploy/flf.service.example|
|테스트|tests/smoke_server.py, tests/test_acceptance.py, tests/test_contracts.py, tests/test_pm_acceptance.py, tests/test_review_regressions.py, tests/test_callback_ledger_race.py, tests/test_iteration.py, tests/test_review_blockers.py, tests/test_session_lifecycle.js|
|현재 문서/역사 증거|README.md, docs/CURRENT_STATUS.md, docs/ITERATION_DECISIONS.md, docs/ITERATION_TESTS.md, docs/LEDGER_RACE_FIX.md, docs/REVIEW_BLOCKERS.md, docs/REVIEW_BLOCKERS_TESTS.md, docs/ENV_PERMISSION_RECHECK.md|

역사 진단 문서는 과거 denial/실행 증거 보존용으로 검토해 유지하며 현재 setup 지침/새로운
권위 SRS가 아니다. 권위 문서 전체/credential/agent/provider 설정을 가져오지 않았다.
실행·세션·callback CAS·삭제·모델 분리·dotenv는 이전 구현, 이번 차이는 README 수동 설정,
환경 예제 철회 양성 테스트 및 현재/과거 상태 구분이다.

로컬 Draft는 환경 예제 요구로 더 이상 차단되지 않으며 최종 Reviewer/PM diff 확인 대상으로
준비됐다. 이것은 새 커밋/원격 출판 승인이나 live acceptance 통과가 아니다.

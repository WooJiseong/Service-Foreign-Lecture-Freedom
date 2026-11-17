# Git 출판 계획 — revised-scope Draft 승인 후, runtime 승인 대기

## 정확한 대상

- 로컬 Git 루트: `/root/uos-project/FLF_Project` (상위 workspace/policies/configuration 제외)
- 기존 HEAD: `e3e8263544877bbed5c4ec6a90284ebaee3212ef`
- 브랜치: `draft/flf-runnable`
- 예정 원격 URL: **`https://github.com/WooJiseong/Service-Foreign-Lecture-Freedom.git`**
- 예정 원격 ref: `refs/heads/draft/flf-runnable`
- 예정 commit subject: **`feat(FLF-2): apply session decisions and environment configuration`**
- 예정 commit body:
  ```text
  Apply anonymous temporary-session decisions, durable cleanup, authenticated
  Speech callbacks and immutable callback-confirmed call ledgers.

  Document manual local environment preparation and independent YAML models.
  Exclude environment-example files by explicit scope withdrawal.
  Include developer-local test evidence; full live acceptance remains unverified.
  ```

현재 로컬 `git remote -v` 출력은 비어 있다. 위 URL은 기존 계획에서 유지한 정확한 예정
목적지이며 configured origin 또는 원격 현재 상태를 검증했다는 뜻이 아니다. 원격/credential
설정을 변경하지 않았다. 이전 계획에 기록된 empty repository 조회는 과거 증거일 뿐이고
현재도 비어 있다고 가정하지 않는다. 승인된 push 전에 원격 ref를 읽기 전용으로 재확인하고,
새 내용/분기가 있으면 비파괴 비교·통합 계획을 다시 확인한다. force push는 계획하지 않는다.

## Review와 테스트의 구분

- 이번 사용자 handoff는 **최종 Reviewer revised-scope Draft PASS, code blocker 없음**을
  전달한다. 이는 scoped Draft 승인이지 전체 live VERIFIED/COMPLETE가 아니다.
- `CURRENT_STATUS.md`의 **162 passed, 1 warning, 88.92s; xfail/skip 없음**, synthetic .env
  실제 uvicorn/demo smoke, Node 세 suite, syntax/compile/whitespace 및 변경 파일 secret scan은
  **Developer가 실행한 로컬 검증**이다. Reviewer가 동일 명령을 재실행한 결과로 바꾸지 않는다.
- 이번 publication-plan 수정은 doc-only다. 전체 테스트를 다시 실행했다고 주장하지 않으며
  이번에는 diff whitespace와 이 문서만의 secret scan으로 확인한다.
- 실제 유료 provider/AI 품질/callback 전달/OBS 삭제 호환성, 공개 HTTPS ingress/TLS 갱신,
  ACG/방화벽/systemd/호스트 quota/외부 접근, 금액 예산 및 legacy 처분 승인 게이트는 유지한다.
  전체 **LIVE NOT_VERIFIED**, 호스트 활성화/paid call 없음.

## 이전 27개 목록 폐기 — 현재 제안 범위는 31개

**이 문서의 과거 27-file index 허용 목록과 이전 commit subject는 폐기·대체한다.**
기준은 [CURRENT_STATUS.md의 30-file inventory](CURRENT_STATUS.md#pending-commit-diff-summary)다.
그 30개는 이 계획 갱신 직전 snapshot이며, 이번 `docs/PUBLICATION_PLAN.md` 수정 1개를
더하면 HEAD 대비 **31개: 수정된 추적 파일 15개 + 미추적 새 파일 16개**다.
CURRENT_STATUS의 과거 30개 검증/scan 기록을 31개 대상으로 실행한 것처럼 고치지 않는다.

승인 요청 대상의 정확한 경로 목록(저장소 루트 기준):

```text
README.md
app.py
core.py
providers.py
config.py
requirements.txt
service.yaml
static/app.js
static/index.html
deploy/RUNBOOK.md
deploy/nginx.conf.example
deploy/access-evaluator.conf.example
deploy/access-public.conf.example
deploy/flf.service.example
tests/smoke_server.py
tests/test_acceptance.py
tests/test_contracts.py
tests/test_pm_acceptance.py
tests/test_review_regressions.py
tests/test_callback_ledger_race.py
tests/test_iteration.py
tests/test_review_blockers.py
tests/test_session_lifecycle.js
docs/CURRENT_STATUS.md
docs/ITERATION_DECISIONS.md
docs/ITERATION_TESTS.md
docs/LEDGER_RACE_FIX.md
docs/REVIEW_BLOCKERS.md
docs/REVIEW_BLOCKERS_TESTS.md
docs/ENV_PERMISSION_RECHECK.md
docs/PUBLICATION_PLAN.md
```

환경 예제/템플릿 파일은 사용자가 요구를 철회했으므로 **생성·stage·출판하지 않는다**.
다른 이름의 예제나 README의 복사용 env 블록으로 대체하지 않는다. 실제 `.env`는 사용자
수동 준비 및 Git ignore 대상이다. `data/`, DB/음성/쿠키/대화, `.venv/`, 로그/cache,
credential/key/certificate, 상위 `AGENTS.md`/`.opencode/`/`opencode.json`, PII 또는 복사한
권위 SRS도 범위 밖이다. 기존 정상 추적 파일을 삭제한다는 뜻이 아니라 이번 commit delta의
허용 범위를 제한하는 것이다. 과거 권한 진단 문서는 historical audit로만 포함한다.

## 승인 게이트와 아직 실행하지 않은 순서

1. 위 **31개 경로 + 정확한 subject + branch + 예정 remote/ref**에 대해 새 런타임 사용자
   승인을 받는다. 이전 SHA의 승인이나 scoped review PASS는 새 stage/commit/push 승인이 아니다.
2. 승인 후 `git status`, 전체 변경/미추적 파일 diff, 최근 log, 제외 대상 및 secret scan을
   다시 확인한다. `git add .`를 사용하지 않고 승인된 경로만 명시적으로 stage한 뒤 index diff를
   확인한다. 확인 중 scope가 달라지면 새 승인을 요청한다.
3. 승인된 subject/body로 commit하고 실제 새 SHA/검사 결과를 보고한다. 아직 새 commit은 없다.
4. push는 실제 새 SHA 및 위 remote/ref에 대해 별도 승인받고, 원격을 재확인한 다음에만 수행한다.
   main 쓰기, 자동 PR 생성, force push, credential 설정 변경은 이 계획에 포함하지 않는다.

승인 후에만 사용할 예정 push 대상 표기(현재 실행하지 않음):

```text
git push -u https://github.com/WooJiseong/Service-Foreign-Lecture-Freedom.git HEAD:refs/heads/draft/flf-runnable
```

현재 **미스테이징 / 새 커밋 없음 / push 없음 / PUBLISH_PENDING**이다. 이번 문서 갱신 자체는
Git 쓰기나 live 배포 승인을 의미하지 않는다.

## 이번 doc-only 확인 — Developer 실행

```bash
git diff --check
python -m detect_secrets scan docs/PUBLICATION_PLAN.md
```

실제 결과: whitespace 검사 exit 0, detect-secrets 1.5.0 **`results: {}`**.
Git metadata로 전체 변경 **31개(추적 수정 15 + 새 미추적 16)**, index diff 비어 있음을
확인했다. 이 확인에서는 전체 pytest/smoke/Node suite를 재실행하지 않았다.

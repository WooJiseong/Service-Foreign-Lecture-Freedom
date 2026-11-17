# 로컬 검증 증거 — 2026-11-17

> 역사적 실행 증거: 아래 104 passed / 1 xfailed 등 실제 결과는 그대로 보존한다.
> 이후 사용자가 환경변수 예제 파일 요구를 철회해 누락 acceptance를 양성 publication 검사로
> 대체했다. 권한 수정이나 당시 통과를 뜻하지 않는다. [현재 상태](CURRENT_STATUS.md) 참조.

브랜치 `draft/flf-runnable`, 기반 HEAD `e3e8263`. 새 커밋/푸시/PR 없음.
독립 리뷰가 아닌 개발자 로컬 검증이다. 유료 API 호출/호스트 인프라 변경 없음.

## 환경

Python 3.12.3. 임시 venv `/tmp/opencode/flf-iteration-venv`에
`pip install -r requirements.txt` 성공. 시스템/호스트 서비스에는 설치/변경하지 않았다.
pytest의 초기 app Store는 `FLF_DATA=/tmp/opencode/flf-test-bootstrap`로 격리,
각 테스트 Store는 임시 디렉터리 사용. smoke는 소스만 복사한 임시 프로젝트에서
합성 `.env`를 만들며 실제 프로젝트 `.env`나 기존 data는 복사/열람하지 않는다.

## 최종 실행

프로젝트 루트에서 아래 명령 실행:

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

- pytest: **104 passed, 1 xfailed, 1 warning**, 62.28초.
  - xfail: 편집 권한이 `*.env.*`를 거부하여 `.env.example` 추가 불가. 실제 미완료 항목이며
    통과로 간주하지 않는다. 허용 후 추가하고 strict xfail 표시를 제거해야 한다.
  - 경고: Starlette TestClient의 httpx 사용 deprecated. 테스트 실패는 아니며 추후 의존성 검토 필요.
- smoke: **PASS**. 실제 uvicorn 실행, `.env` 한도 적용 및 셸 demo 우선순위,
  HTTP health/UI/assets/upload, CREATED 재시작 복구, 명시 제출, 모든 처리 단계,
  데모 채팅, 완료 후 재시작 복구, 삭제. 출력의 처리/채팅은 demo이며 유료 검증 아님.
- Node: 세 파일 모두 **PASS**. 기존 transport의 lost response/불명 호출 차단,
  저장소 차단 시 demo 유지/live chat 차단, 즉시 초기 heartbeat/visibility,
  unload 비삭제, 멀티탭 만료 캐시 정리, upload ID 재사용/새 업로드 분리/명시 종료.
- 구문/컴파일/diff whitespace 검사: 모두 exit 0.

추가 Python 검증 범위: 격리 subprocess dotenv/셸/YAML 우선순위,
모든 limits YAML/env 경로, 잘못된 YAML/스키마/한도 및 비밀 값 비노출,
서로 다른 summary/chat outbound URL, 세션 lease/reload/Store 재시작,
명시 종료/만료/차단된 provider 중 별도 reaper 삭제, 캐시 삭제, 구 데이터 보존/채택,
동일 업로드 요청 재시도/다른 파일 충돌/종료 요청 재생 거부,
mocked Object Storage PUT/DELETE/버전 삭제/장애 tombstone 및 재시작 복구,
설정 가능한 호출/채팅 cap, secure session cookie/Host/no-store,
Nginx/systemd 정적 계약 및 문서화된 변수 완전성.

## Secret scan

```bash
python -m detect_secrets scan app.py core.py providers.py config.py service.yaml README.md requirements.txt static/app.js static/index.html tests/test_iteration.py tests/test_acceptance.py tests/test_contracts.py tests/test_pm_acceptance.py tests/test_review_regressions.py tests/smoke_server.py tests/test_session_lifecycle.js deploy/nginx.conf.example deploy/access-evaluator.conf.example deploy/access-public.conf.example deploy/flf.service.example deploy/RUNBOOK.md docs/ITERATION_DECISIONS.md
```

detect-secrets 1.5.0: 최종 `results: {}`. 첫 스캔은 합성 dotenv 테스트 문자열을
고엔트로피 문자열로 탐지했으며 실제 credential이 아님을 확인하고 해당 테스트 줄에만
명시 allowlist 주석을 추가했다. 실제 `.env`, ignored data, 외부 credential 파일은 스캔하지 않았다.

## 정직한 미검증/미완료

- YouTrack 도구 미연결: A1/A4 및 관리자 댓글 6개 직접 조회 불가. 제공된 확정 매트릭스 사용.
- 루트 `.env.example` 편집 허용 필요. 현재 README의 cp 명령은 파일 추가 후에만 사용 가능.
- PM 추적 기록/독립 리뷰/금액 예산 결정 대기.
- 실제 Speech/Papago/Studio/Object Storage API, 버전 목록 호환성 및 권한 미검증.
- Nginx 실제 syntax test/호스트 TLS 발급 및 자동 갱신/네트워크 ACL/systemd 활성화 미실행.
- 기존 lease 없는 데이터는 보존, 자동 실행/삭제하지 않음. 운영 전환 검토 필요.
- 커밋/원격 publication은 요청대로 미실행. 리뷰 후 별도 승인된 변경만 커밋하고,
  GitHub 쓰기/푸시/PR도 별도 런타임 승인 후 수행해야 한다.

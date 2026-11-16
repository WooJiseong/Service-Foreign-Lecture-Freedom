# 로컬 실행 증거

## PM authoritative crosscheck 보완 후 최종 실행

작업 디렉터리 `/root/uos-project/FLF_Project`, Python 3.12.3, Node v18.19.1.

```text
$ python -m pytest -q
.................................................................        [100%]
65 passed in 40.35s

$ python tests/smoke_server.py
PASS: actual HTTP health/UI/assets/upload, CREATED restart, explicit submit, all stages, demo chat, completed restart, delete

$ python -m compileall -q app.py core.py providers.py media_runner.py
(exit 0)

$ node --check static/app.js
$ node --check static/chat_transport.js
(both exit 0)
$ node tests/test_chat_transport.js
PASS F6: response lost after completion; reload/reconcile; one POST, one paid call, one history turn
PASS F6: request lost before receipt; same id/question replay
PASS F6: uncertain request remains blocked and retained
$ node tests/test_frontend_storage.js
PASS N1: getter failure / live; results, tabs and upload work; paid chat disabled only
PASS N1: write failure / live; results, tabs and upload work; paid chat disabled only
PASS N1: getter failure / demo; results, tabs and upload work; paid chat disabled only
PASS N1: write failure / demo; results, tabs and upload work; paid chat disabled only
```

추가 검증: `tests/test_pm_acceptance.py`는 PM 확인 A-1 AC 매핑/FR12/FR23의 로컬 검증이다. 실제 outbound SYSTEM/USER 메시지, 5000자 이하 lossless 분할·manifest·순서/merge, 기존 chunk/summary map cache 경계 유지, summary-only retry, invalid/auth no-downstream, crossowner chat status, Papago 표기, unlink 후 finalize 실패의 삭제 복구를 포함한다. 모두 demo/mock이며 live API의 증거가 아니다. Node는 실제 UI handler를 mock DOM에서 실행하고, 3개 탭 전환 시 네트워크 호출이 증가하지 않는 것도 검사했다. 실제 브라우저 렌더링 E2E는 미실시다.

PM-crosscheck 수정 버전으로 loopback 데모를 재시작한 후 `/health` 200 (`mode=demo`), `/ready` 200 (`ready=true`, worker healthy/failures=0), UI 200/Papago 텍스트 존재, storage guard script 200을 실제 HTTP로 확인했다. 외부 배포는 아니다.

PM의 A-1/A-4 대조 및 Stage Review 기록 확인과 현재 Draft의 최종 독립 scoped code review APPROVED(FR12/FR23, N1–N3 포함)는 사용자 handoff로 전달받았다. Orchestrator 수용은 로컬 Draft/코드 리뷰와 개발자 테스트 증거에 한정되며, 개발자 YouTrack 쓰기나 full/live VERIFIED를 주장하지 않는다. commit/push runtime 승인은 별도이며 미획득 상태다.

위 65-test/HTTP smoke/compileall/Node 검사는 publication gate 승인 handoff 후 개발자가 다시 실행한 결과다. runtime commit 승인 요청 경로는 현재 도구 스키마에서 제공되지 않아 일반 Bash로 commit/push를 시험하지 않았다. 실제 승인 획득/거절 결과는 없으며, 미실행/PUBLISH_PENDING이다.

## 출판 준비 검사
- Git 루트는 `FLF_Project/`만, unborn branch `draft/flf-runnable`에 명시적 27개 파일 index 준비. `git diff --cached --check` 통과. 상위 policy/configuration 및 data/cache/env/log는 포함하지 않았다.
- GitHub read API: `409 Git Repository is empty`. `git ls-remote --heads --tags https://github.com/WooJiseong/Service-Foreign-Lecture-Freedom.git`: exit 0, ref 없음.
- `detect-secrets` 1.5.0, `detect-secrets scan --no-verify`: `results: {}`. git index의 파일을 검사했으며 외부 키 검증/유료 API 호출을 하지 않았다. 자동 검사로 secret 부재를 절대 보장하지 않으며 index scope도 별도 확인했다.
- 커밋·푸시·원격 브랜치·PR 변경 없음. 정확한 commit subject/body와 원격 ref는 `PUBLICATION_PLAN.md`.

## F1–F6 수정 시점 실행 이력

작업 디렉터리 `/root/uos-project/FLF_Project`, Python 3.12.3, Node v18.19.1. F1–F6 수정 이후 실제 실행:

```text
$ python -m pytest -q
...................................................                      [100%]
51 passed in 31.73s

$ python tests/smoke_server.py
PASS: actual HTTP health/UI/assets/upload, CREATED restart, explicit submit, all stages, demo chat, completed restart, delete

$ python -m compileall -q app.py core.py providers.py media_runner.py
(exit 0)

$ node --check static/app.js
$ node --check static/chat_transport.js
(both exit 0)
$ node tests/test_chat_transport.js
PASS F6: response lost after completion; reload/reconcile; one POST, one paid call, one history turn
PASS F6: request lost before receipt; same id/question replay
PASS F6: uncertain request remains blocked and retained
```

`tests/test_review_regressions.py`의 F1–F5, 자원 제한, failure-save/queue/TTL 장애, known-failure 재승인, cached 요약 재검증, upload lease 검사를 포함한다. Node 테스트는 실제 JS 전송 모듈의 mock API/storage 검증이며 브라우저 렌더링이 아니다. live 코드 경로의 provider는 mock이므로 유료 API 실검증을 주장하지 않는다.

수정 중 첫 실행에서 23 passed / 1 failed: 새 readiness가 초기 `starting`에서 의도대로 503을 반환하여 기존 테스트 fixture의 즉시 health 가정이 실패했다. fixture가 `/ready`를 기다리도록 수정했다. 이후 최종 실행은 위와 같다.

원래 실행 중이던 데모 프로세스를 확인 후 종료하고 수정 버전으로 재시작했다. 실제 HTTP에서 `/health` 200, `/ready` 200 (`ready=true`, worker healthy, failures=0), UI 200, 새 `chat_transport.js` 200을 확인했다. 로컬 loopback 실행이며 외부 배포 증거가 아니다.

## 최초 Draft 실행 이력 (독립 리뷰 FAIL 이전)

작업 디렉터리 `/root/uos-project/FLF_Project`, Python 3.12.3.

```text
$ python -m pytest -q
........................                                                 [100%]
24 passed in 4.20s

$ python -m compileall -q app.py core.py providers.py
(exit 0, no output)

$ python tests/smoke_server.py
PASS: actual HTTP health/UI/assets/upload, CREATED restart, explicit submit, all stages, demo chat, completed restart, delete
```

테스트는 실제 ffmpeg/ffprobe와 SQLite를 사용한다. 7개 지원 형식 파일을 실제 생성·디코딩했다. 유료 제공자는 전부 demo/mocks이며 live 통합 인증/품질 검증이 아니다. smoke는 별도 임시 데이터/동적 loopback 포트에서 실제 Uvicorn 프로세스를 재시작하고 종료한다.

## 로컬 데모 실행 명령

```text
$ FLF_MODE=demo nohup python -m uvicorn app:app --host 127.0.0.1 --port 10000 --workers 1 --no-access-log > /tmp/opencode/flf-draft-server.log 2>&1 &
$ python -c "import httpx; r=httpx.get('http://127.0.0.1:10000/health'); print(r.status_code, r.json()); p=httpx.get('http://127.0.0.1:10000/'); print('UI', p.status_code)"
200 {'status': 'ok', 'mode': 'demo'}
UI 200
```

`ss -ltn`에서 `127.0.0.1:10000` LISTEN 확인. 이 URL은 작업 호스트 loopback이며 외부 배포가 아니다. 실행 환경에 ffmpeg가 없어 패키지로 설치한 후 검증했다. 재실행은 README의 setup 명령을 따른다.

## 실패 이력 및 수정
- 첫 실행: 11 passed / 1 failed. 소유권 테스트가 두 번째 lifespan을 시작해 단일 워커 파일 잠금에 걸림. 동일 서버의 새 쿠키 세션을 사용하도록 테스트 수정.
- 다음 확장 실행: 22 passed / 1 failed. FastAPI가 본문 크기 예외를 multipart parsing 400으로 변환. ASGI body-limit 응답 상태 전달을 수정하여 초과 요청은 413으로 확인.
- 최초 Draft 중간 실행에서 `command -v node`가 실패했다. 리뷰 수정 작업에서는 Node 18.19.1을 설치하여 위의 JS 구문/전송 모듈 회귀를 실행했다. 실제 브라우저 E2E는 여전히 수행하지 않았다.

## 독립 검증 필요
- PM이 확인한 실제 A-1/A-4 매핑은 `TRACEABILITY.md`에 반영했다. 현재 Draft의 최종 scoped 코드 리뷰는 승인 전달받았고, 아래 full/live·운영 검증은 여전히 별개다.
- 독립 코드 리뷰, 브라우저 렌더링/키보드/모바일 E2E.
- live Speech/Papago/Studio, 실강의 의미 품질·프롬프트 주입 평가.
- 강제종료/디스크 장애/장시간 부하의 운영 실증. 현재 복구 증거는 정상 프로세스 재시작 smoke와 inflight/cached-submit mock 테스트.
- 외부 `101.79.23.235:10000` 배포, TLS, 실제 평가자 IP 허용 및 다른 출발지 차단.

커밋/푸시/PR 없음. 이전 F1–F6 scoped PASS와 별개로 이번 변경 및 full/live 검증 통과를 주장하지 않는다.

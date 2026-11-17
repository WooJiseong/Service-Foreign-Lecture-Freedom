# FLF runnable Draft

Python 3.12+, `ffmpeg`/`ffprobe` 필요. **demo는 실제 음성을 인식하지 않는 고정 예시**이며
API 호출이 없습니다. live/유료 검증은 예산 및 호출 승인을 받기 전 실행하지 마세요.

## 로컬 설치 및 실행

```bash
cd /root/uos-project/FLF_Project
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# Ubuntu에서 ffmpeg가 없다면 운영자 승인 후: sudo apt-get install ffmpeg
```

환경변수 예제·템플릿 파일은 Git에 포함하지 않습니다(사용자의 명시적 범위 변경).
기본 demo는 `.env` 없이 실행할 수 있습니다. 설정이 필요하면 사용자가 신뢰할 수 있는
로컬 편집기로 **이 저장소 루트(app.py/README와 같은 디렉터리)**에 `.env`를 직접 준비하세요.
기존 파일은 덮어쓰지 말고 본인/서비스 사용자만 읽을 수 있도록 파일 권한 0600 및 제한된
디렉터리 권한을 유지하세요. 아래 표의 필요한 변수만 설정하며, demo에는 API 키가 필요 없습니다.
실제 `.env`는 `.gitignore`에서 제외됩니다. 비밀을 Git·README·YAML·셸 명령 기록·로그에 넣거나
내용을 공유하지 마세요. 서버 secret manager/권한 제한 환경 주입도 사용할 수 있습니다.

```bash
# 유료 API 호출 없는 로컬 HTTP demo (포트 10000)
FLF_MODE=demo .venv/bin/uvicorn app:app --host 127.0.0.1 --port 10000 --workers 1 --no-access-log
```

`.env` 없이도 위 demo 명령은 실행 가능합니다. `.env`가 있으면 `python-dotenv`가
**app/core/providers 설정 평가 전에 저장소 루트의 파일만** 읽습니다. 부모 폴더 탐색 없음.
셸/프로세스 환경 > `.env`; CLI `FLF_MODE=demo`는 파일의 live 값도 덮어씁니다.
uvicorn의 `--host`, `--port`, `--workers` 옵션은 명령행에서 지정합니다. `--env-file`은
필요 없습니다. 변수/모델 변경은 재시작해야 합니다. 단일 프로세스/worker만 지원합니다.

접속 http://127.0.0.1:10000 → 데모 WAV 선택 → 동의 → 제출. 파일 선택만으로 전송하지
않습니다. 각 새 제출은 동일 파일이어도 별도 강의/Q&A 세션입니다. 전송 실패 시 같은
업로드 요청 ID로만 재시도합니다. 결과 조회/유형 전환은 유료 API를 재호출하지 않습니다.
명시적 세션 종료는 새로고침과 다릅니다. 비정상 종료는 heartbeat lease 만료로 정리합니다.

### UI 확인 (로컬 demo 실행 후)

1. 새 세션은 업로드 화면만 표시합니다. 파일 선택/끌어 놓기 → 이름·크기·서버 한도 확인 →
   전송 동의 → **변환 및 요약**. 미지원/빈 파일/크기 초과는 이유와 함께 제출을 차단합니다.
   형식 진위와 길이는 서버에서 최종 검증합니다.
2. 처리 화면의 음성 인식 → 한국어 번역 → 강의 요약 상태를 확인합니다. 실제 완료 후에만
   결과·질문 화면으로 이동합니다. 오류 시 허용된 단계만 재시도하거나 세션을 종료합니다.
3. 결과 버튼은 현재 유형 **Summary → Origin → Translate → Summary** 순환입니다.
   저장된 내용만 바꾸며 채팅은 유지합니다. Translate에서 Papago 표기를 확인합니다.
4. 질문은 Enter 전송, Shift+Enter 줄바꿈입니다. 한글 조합 중 Enter는 전송하지 않습니다.
   응답 대기/오류는 해당 질문 아래 표시됩니다. 새 강의 시작/처음으로는 확인 후 현재
   세션을 종료합니다. 새로고침은 소유한 활성 강의를 복구하며 종료/새 처리 호출이 아닙니다.
5. 데스크톱 나란히/좁은 화면 세로 배치, 키보드 포커스·복사·스크롤은 실제 브라우저에서
   별도 확인하세요. 자동 검증 범위/임시 UI 결정: [FLF-9 구현 기록](docs/FLF9_UI.md).

## 환경 변수 — 서버 전용

비밀은 코드/YAML/로그/명령 기록에 넣지 마세요. 값 대신 이름만 검증 오류에 출력합니다.
기존 `SPEECH_URL`, `SPEECH_KEY`, `PAPAGO_ID`, `PAPAGO_SECRET`, `STUDIO_KEY`는 **제거**했습니다.
각각 아래 Speech URL/Secret Key, Papago ID/Secret, Studio Key의 정식 이름으로 이전하세요.

|변수|기본값/용도|
|---|---|
|`FLF_MODE`|`demo`; 실제 API는 `live` (별도 승인 필요)|
|`FLF_DATA`|프로젝트 `data/`; 데이터 경로. 테스트/demo/live 분리 권장|
|`FLF_CONFIG`|루트 `service.yaml`; 상대 경로는 프로젝트 루트 기준|
|`FLF_ALLOWED_HOSTS`|`localhost,127.0.0.1,testserver`; 배포 시 `101.79.23.235`|
|`FLF_SECURE_COOKIE`|로컬 기본 미설정/`0`; HTTPS 배포는 `1` 필수|
|`FLF_TRANSLATION_LABEL`|`Transition`; legacy API 호환용. FLF-9 UI는 표시명 **Translate**를 사용하며 내부 `translation`/`transcript` 키는 유지|
|`FLF_PUBLIC_BASE_URL`|live 필수, 공개 HTTPS origin (예: `https://101.79.23.235`); 인증된 Speech callback URL 생성|
|`TMPDIR`|Python 표준 임시 경로; systemd 예시는 서비스 전용 `/tmp` 256MiB tmpfs quota. YAML 상향 시 함께 검토|
|`CLOVA_SPEECH_SECRET_KEY`|live 필수, Speech 콘솔의 비밀 인증키|
|`CLOVA_SPEECH_INVOKE_URL`|live 필수, Speech 콘솔 HTTPS Invoke URL, `/recognizer` 이전|
|`PAPAGO_CLIENT_ID`|live 필수, Papago Application 인증 ID|
|`PAPAGO_CLIENT_SECRET`|live 필수, Papago Application 비밀 인증키|
|`CLOVASTUDIO_API_KEY`|live 필수, CLOVA Studio Bearer API Key|
|`CLOVASTUDIO_MODEL`|공통 fallback `HCX-005`; YAML 역할 값이 null/미설정일 때만 사용|
|`NCLOUD_ACCESS_KEY_ID`|현재 live 시작 검증에서 필수, legacy 정리용 서버 인증 ID|
|`NCLOUD_SECRET_KEY`|현재 live 시작 검증에서 필수, legacy 정리용 서버 비밀 인증키|
|`NCLOUD_OBJECT_STORAGE_BUCKET`|현재 live 시작 검증에서 필수, legacy 전용 bucket|
|`NCLOUD_OBJECT_STORAGE_ENDPOINT`|live 필수, 예: `https://kr.object.ncloudstorage.com`|
|`NCLOUD_OBJECT_STORAGE_INPUT_PREFIX`|이전 버전 앱 전용 입력 namespace 설정, 예: `flf/input`; 새 callback 세션은 복사본 미생성|
|`NCLOUD_OBJECT_STORAGE_OUTPUT_PREFIX`|이전 버전 앱 전용 출력 namespace 설정, 예: `flf/output`; 기존 삭제는 DB의 정확한 키 사용|

`service.yaml`의 상세 한국어 주석을 참고하세요. **역할별 YAML 모델 > 공통 환경 fallback >
HCX-005**. summary/chat 둘 다 기본 HCX-005, 서로 다른 값 사용 가능. 모델 이름은 URL 경로
삽입 방지를 위해 영숫자/하이픈만 허용합니다. YAML 비밀 저장/알 수 없는 키는 금지합니다.
운영 한도는 **환경 변수 > YAML > 코드 기본값**이며 양의 정수만 허용합니다.

|YAML `limits` 키|대응 환경 변수|기본값|
|---|---|---|
|max_bytes|`FLF_MAX_BYTES`|104857600|
|max_seconds|`FLF_MAX_SECONDS`|7200|
|max_jobs|`FLF_MAX_JOBS`|50|
|max_queue|`FLF_MAX_QUEUE`|20|
|max_storage|`FLF_MAX_STORAGE`|2147483648|
|max_db_bytes|`FLF_MAX_DB_BYTES`|67108864|
|max_validations|`FLF_MAX_VALIDATIONS`|2|
|lease_seconds|`FLF_LEASE_SECONDS`|180|
|heartbeat_seconds|`FLF_HEARTBEAT_SECONDS`|30|
|max_calls|`FLF_MAX_CALLS`|200|
|max_chat_requests|`FLF_MAX_CHAT_REQUESTS`|20|
|reaper_milliseconds|`FLF_REAPER_MILLISECONDS`|500 (0.5초)|
|cleanup_milliseconds|`FLF_CLEANUP_MILLISECONDS`|500|
|max_provider_response_bytes|`FLF_MAX_PROVIDER_RESPONSE_BYTES`|8388608|
|speech_wait_seconds|`FLF_SPEECH_WAIT_SECONDS`|7200|

모든 숫자는 **TEMPORARY_DECISION**, 금액 예산 확정/무제한 사용 승인이 아닙니다.
한도는 업로드 임시 공간/DB/큐/호출 시도를 제한하지만 계정 전체 요금 상한은 아닙니다.
live 시작에는 정식 변수 및 `FLF_PUBLIC_BASE_URL`이 필요합니다. 새 Speech 요청은 공식
`completion=async`, **인증된 job별 callback URL**, `resultToObs=false`를 사용합니다.
결과를 callback으로 실제 수신/검증/영속화하고 처리 큐에서 소비합니다. 불필요한 별도
입력/출력 Object Storage PUT 복사본은 만들지 않습니다. 따라서 수신 경로에 generic
Object Storage GET는 필요하지 않으며 가짜 read 기능을 추가하지 않았습니다.
이전 버전 manifest가 있는 외부 객체/버전은 독립 삭제 워커가 정확한 키만 DELETE합니다.
필수 변수 명칭/마이그레이션 설정은 유지하되 이를 새 세션의 OBS 결과 수신이라 주장하지 않습니다.
OBS의 기능적 용도는 legacy 정리지만 **현재 live 시작 검증은 OBS 변수도 모두 필수로 검사**합니다.
callback-only live라도 선택적인 시작 조건이라고 가정하면 안 됩니다. demo에는 설정이 필요 없습니다.
실제 NAVER callback 전달 및 Object Storage 권한/호환성은 아직 검증하지 않았습니다.

설정은 `config.BOUNDS`의 안전 상한과 교차조건도 검사합니다. 검증동시수≤큐≤작업수,
DB+동시 업로드/spool 예산≤저장 상한, callback 대기시간≥오디오 길이 상한이 필수입니다.
공개 heartbeat는 동일 강의에 설정 간격보다 잦게 도착해도 DB를 갱신하지 않습니다.
Nginx에 API/업로드/callback별 실제 rate limit 예시가 있으며 숫자는 임시 선택입니다.
상세 계약/복구/구 데이터 처분 계획: [리뷰 차단 수정](docs/REVIEW_BLOCKERS.md).
실제 개발자 로컬 검증 명령/결과 및 미완료 게이트: [리뷰 수정 테스트](docs/REVIEW_BLOCKERS_TESTS.md).

재리뷰 B1 수정: [callback ledger 경쟁 수정](docs/LEDGER_RACE_FIX.md).
Callback 확정 ledger는 재시도·예외·늦은 ack가 덮어쓰지 않습니다. 다른 ack token은
명시적 재대조 충돌로 차단하며 자동 재호출하지 않습니다. 구 강의 채택은 **기존 결과
조회/종료 전용**입니다. 미완료 단계/불명 ledger는 보존하고 제출·재시도·새 Q&A 및
checkpoint 재개 기능은 제공하지 않습니다. 새 업로드는 새 독립 세션/잠재 과금임에 유의하세요.

## 테스트 및 배포 실행

```bash
python -m pytest -q
node tests/test_chat_transport.js
node tests/test_frontend_storage.js
node tests/test_session_lifecycle.js
node tests/test_flf9_ui.js
python tests/smoke_server.py
python -m compileall -q app.py core.py providers.py config.py media_runner.py
```

Node 18+는 로컬 회귀 테스트 전용입니다. `/health`, `/ready`는 worker 이상을 503으로 보고합니다.
배포는 Nginx HTTP 10000 → HTTPS 443, 앱 loopback **10001**로 로컬 demo 포트와 다릅니다:

```bash
# 승인된 live 환경에서만. 필수 변수는 사용자가 안전하게 준비한 서버 .env/환경에서 로드.
FLF_MODE=live .venv/bin/uvicorn app:app --host 127.0.0.1 --port 10001 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
```

live 전환 전 예산/유료 호출 승인, 실제 Speech/Papago/Studio 및 현재 필수 OBS 설정,
신뢰할 수 있는 공개 HTTPS 인증서, `FLF_PUBLIC_BASE_URL`과 제공자 callback ingress,
배포 호스트 allowlist와 Secure cookie 설정이 필요합니다. HTTP demo 설정을 그대로 공개하지
마세요. evaluator allowlist의 callback 차단 문제는 별도 승인된 ingress 방안 없이는 해결된
것이 아닙니다. 이 명령은 실제 live/배포 검증 성공을 뜻하지 않습니다.

운영 설정/승인 게이트: [배포 runbook](deploy/RUNBOOK.md).
현재 범위·검증·출판 상태: [현재 Draft 상태](docs/CURRENT_STATUS.md).
세션·삭제·호환성 이력: [이번 반복 결정](docs/ITERATION_DECISIONS.md).

# FLF runnable Draft

Python 3.12+, `ffmpeg`/`ffprobe`가 필요합니다. 기본은 **데모**: 실제 음성을 인식하지 않고 에너지 보존 강의의 고정 예시를 보여줍니다. 유료 API를 호출하지 않습니다.

```bash
cd /root/uos-project/FLF_Project
python -m venv .venv
.venv/bin/pip install -r requirements.txt
# Ubuntu에서 ffmpeg가 없다면: sudo apt-get install ffmpeg
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 10000 --workers 1 --no-access-log
```

접속: http://127.0.0.1:10000 . 「데모용 WAV 만들기」 → 동의 체크 → 「제출 및 처리 시작」. 파일 선택만으로 전송하지 않습니다. 한 프로세스만 사용하며 작업/결과는 `data/`에 보관됩니다. 같은 브라우저 세션으로 재접속하면 작업 목록에서 복구합니다. 쿠키를 잃으면 복구할 수 없습니다.

한도가 꽉 차면 동일 파일도 입장 선검사에서 거부될 수 있습니다. 재업로드 대신 「내 작업」에서 기존 job을 선택하세요. 브라우저 저장소 차단 시 업로드/결과/탭은 유지하고 실제 API 채팅만 비활성화합니다.

## 환경 변수 (서버 프로세스에만 주입)

|변수|기본값/용도|
|---|---|
|`FLF_MODE`|`demo`; 실제 호출은 `live`|
|`SPEECH_URL`|Speech 도메인 콘솔의 HTTPS Invoke URL (`/recognizer` 이전)|
|`SPEECH_KEY`|Speech Secret Key|
|`PAPAGO_ID`, `PAPAGO_SECRET`|NAVER Cloud Papago Application 인증|
|`STUDIO_KEY`|CLOVA Studio Bearer API Key; 모델 HCX-005|
|`FLF_DATA`|기본 프로젝트 `data/`; 전용 영속 볼륨 권장|
|`FLF_MAX_BYTES`|104857600 (100 MiB)|
|`FLF_MAX_SECONDS`|7200 (120분)|
|`FLF_MAX_JOBS`|50; 모든 쿠키를 합한 보관 작업 수|
|`FLF_MAX_QUEUE`|20; CREATED 및 실행/대기 작업 합계, retry에도 적용|
|`FLF_MAX_STORAGE`|2147483648 (2 GiB); DB 예산·업로드/spool 예약을 포함한 보수적 입장 제한|
|`FLF_MAX_DB_BYTES`|67108864 (64 MiB); SQLite 크기 상한|
|`FLF_MAX_VALIDATIONS`|2; multipart parsing부터 검증 완료까지 전역 예약 수|
|`FLF_TRANSLATION_LABEL`|`Transition`; 합의 시 `Translation` 가능|
|`FLF_ALLOWED_HOSTS`|`localhost,127.0.0.1,testserver`; 배포 호스트를 명시 추가|
|`FLF_SECURE_COOKIE`|기본 미설정: 로컬 HTTP용. HTTPS 배포 시 `1` 필수|

live는 모든 키가 있어야 시작합니다. Speech 도메인 Object Storage 결과 저장 설정/권한이 필요합니다(`resultToObs=true`). 키를 코드·README·커밋·명령 기록에 쓰지 말고 보안 환경 주입을 사용하세요. API 본문/인증/음성 내용은 로그로 출력하지 않습니다. 실제 API 및 호스트 배포는 검증하지 않았습니다.

```bash
python -m pytest -q
node tests/test_chat_transport.js
node tests/test_frontend_storage.js
python tests/smoke_server.py
curl http://127.0.0.1:10000/health
curl http://127.0.0.1:10000/ready
```

Node 18+는 프런트엔드 회귀 테스트에만 필요합니다. `/health`와 `/ready`는 워커 시작·복구·소진·사망 시 503을 반환합니다. 연속 인프라 장애 5회 후에는 원인 해결 및 프로세스 재시작이 필요합니다. 불명확한 제공자 호출은 재시작해도 자동 재전송하지 않습니다.

결정·검증 한계: [Draft notes](docs/DRAFT_NOTES.md), [리뷰 수정](docs/REVIEW_FIXES.md), [요구사항 추적](docs/TRACEABILITY.md). 원격 실행: [배포 runbook](deploy/RUNBOOK.md).

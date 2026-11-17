# 확정 결정 매트릭스 기반 로컬 반복 — 독립 검토 대기

> 범위 변경 후 현재 상태: 환경변수 예제/템플릿 파일 요구는 사용자 지시로 철회됐다.
> 아래 해당 누락/권한 pending은 과거 결정 기록이며 현재 차단이 아니다. 권한을 수정한 것이
> 아니고 우회 파일도 만들지 않았다. [현재 상태](CURRENT_STATUS.md) 참조.

YouTrack 도구가 연결되어 있지 않아 A1/A4 및 6개 관리자 댓글을 직접 조회하지 못했다.
요청자가 제공한 FLF7/Q1, FLF6/Q2, FLF4/8/Q3/Q4, FLF5/Q5, FLF3/Q6 매트릭스를
구현 근거로 사용했다. PM의 원문 대조/추적 기록은 남아 있으며 이 문서는 권위 문서가 아니다.
이전 DRAFT_NOTES/TRACEABILITY의 7일 보관·digest 중복제거·배포 충돌 설명은 이번
정책에 맞게 대체되지만 과거 검증 기록을 덮어쓰지 않는다.

## 세션과 삭제

- 로그인 없는 공개 서비스. 무작위 256-bit HttpOnly SameSite=Strict **세션 쿠키**의
  SHA-256 소유권으로 job API를 격리한다. 7일 Max-Age 인증 쿠키가 아니다.
  HTTPS 배포 Secure 필수. 쿠키 없는 장치/타 브라우저 복구는 제공하지 않는다.
- 새 업로드는 파일 내용이 같아도 새 독립 job/강의/Q&A. `X-FLF-Upload-ID`가 같은
  동일 소유권/모드/내용 재시도만 기존 job을 반환한다. 다른 내용은 충돌로 거부한다.
  제출/유료 단계/질문은 기존 durable ledger로 재전송을 방지한다. 불명 POST는 관리자
  대조 전 재호출 금지. 전역 입장 제한은 같은 요청 ID 재시도도 거부할 수 있으며
  그 경우 기존 목록/ID를 조회해야 한다. 새 ID 생성으로 우회하지 않는다.
- TEMPORARY_DECISION: lease 180초, heartbeat 30초. 활성(보이는) 탭이 **브라우저의
  모든 활성 강의** lease를 갱신한다. 같은 쿠키의 여러 탭 중 하나가 보이면 유지된다.
  모두 숨겨지거나 종료되면 lease 만료. 모바일 sleep/background throttling 역시 만료 가능.
  서버 시각 기준 lease가 SQLite에 보존되어 새로고침/프로세스 재시작으로 연장/삭제되지 않는다.
  만료 이후 heartbeat는 복구하지 않는다. 서버 중단 중에는 삭제할 수 없고 재시작 시 재개.
- unload/pagehide/beacon은 사용하지 않는다. 새로고침을 종료로 오판하지 않는다.
  브라우저의 세션 복원 기능은 쿠키를 복구할 수도 있지만 만료/종료된 세션은 복구 불가.
- UI 종료는 `POST /api/jobs/{id}/end`. 다른 탭도 즉시 API 접근 차단. durable tombstone
  commit 후 로컬 오디오 unlink, 전사/번역/요약/대화/질문/호출 캐시 제거, Object Storage
  정확한 키와 버전 삭제. SQLite secure_delete 활성화. 물리 디스크/백업 secure erase 보장은 아님.
  provider 호출 중에는 결과를 새로 공개/저장하지 않고 끝난 뒤 워커가 남은 외부 정리를 수행.
  실패는 tombstone을 유지하고 재시도하며 202 cleanupPending으로 완료와 구분한다.
  TEMPORARY_DECISION: 별도 lease reaper가 0.5초 간격으로 로컬 만료를 처리하여 긴
  provider 호출이 만료 삭제를 막지 않게 한다. 외부 삭제 실패는 job별 영속 스케줄로
  5초부터 지수 backoff, 최대 300초 간격으로 재시도한다. 운영자 장애 감시는 여전히 필요하다.
  API 전송 중 음성/외부 서비스 자체 캐시/보관을 즉시 취소/삭제할 수 있다고 약속하지 않는다.
- 브라우저 sessionStorage의 미확인 질문은 완료/종료/만료 관측 후 제거. 잠든 다른 탭의
  메모리/저장소를 서버가 원격 삭제할 수는 없으며 다시 활성화/목록 갱신 시 제거한다.
  데이터 응답은 no-store. 이 한계는 제공자 zero-retention을 의미하지 않는다.
- 종료된 업로드 요청은 소유권/모드/요청 ID의 단방향 해시만 `ended_uploads`에 남긴다.
  종료된 요청 재전송으로 새 과금을 만드는 것을 막는 보안 tombstone이며 음성/결과/질문
  캐시는 아니다. DB 크기 제한 적용. 외부 객체 namespace(endpoint/bucket/정확한 키)는
  업로드 생성 시 저장하여 설정 변경 후에도 이전 대상 삭제를 재개한다. 키/자격 증명은 저장하지 않는다.
- 이전 DB의 lease 없는 job은 **보존**하되 워커가 자동 실행/삭제하지 않는다. 기존 쿠키로
  목록을 확인하고 heartbeat로 명시 채택하거나 종료할 수 있다. 기존 유료 ledger도 보존한다.
  소유권을 잃은 구 데이터의 보존/삭제 마이그레이션은 운영자 검토가 필요하다. 새 정책에
  맞는 완전한 운영 전환을 완료했다고 주장하지 않는다.
- 기존 DELETE endpoint는 호환성 유지: 실행 중 409, idle 삭제. 새 UI의 즉시 종료 의미는
  /end이며 진행 중 호출에서도 사용할 수 있다.

## 설정/외부 저장/운영

- 정식 변수만 지원하며 구 이름 alias는 제거했다. README에 이전 이름→정식 이름 대응 기록.
  dotenv는 루트 한 파일만, overwrite=False. 역할 모델 YAML override는 실제 outbound URL에 적용.
- Object Storage SDK는 서버 전용 explicit credentials, endpoint, 최소한의 bounded network retry.
  입력/출력 PUT는 동일 키 재시도로 안전하다. 출력은 transcript/translation/summary이며 chat은
  SQLite 활성 세션에만 저장한다. provider 보관·버킷 복제본/별도 백업은 앱 직접 삭제 범위 밖이다.
- 전용 비특권 systemd 및 Nginx 평가/공개 모드 예시만 제공. 호스트 변경/인증서 발급/공개 포트
  개방은 미승인. IP 인증서 자동 갱신은 계획이며 실증이 아니다. Article HTTP URL은 리다이렉트
  진입점으로 해석했으며 원문은 수정하지 않았다.
- 루트 `.env.example`은 edit permission의 `*.env.*` 거부로 추가 불가. 허용 후 추가하고
  completeness 테스트의 알려진 xfail을 제거해야 한다. 실제 `.env`는 읽어 보거나 노출하지 않았다.

## 남은 검토

PM 권위 문서/6개 댓글 대조·결정 로깅, 독립 리뷰, .env.example 편집 허용,
금액 예산, live API/버전 목록 API 호환성, 외부 삭제 지연/장애 감시, 호스트 자원/네트워크,
공인 IP TLS 자동 갱신 실증. 커밋/푸시/PR/YouTrack 쓰기/인프라 변경은 이번 실행 범위 밖.

# 배포 runbook — 미실행

대상 `101.79.23.235:10000`, 평가자 `222.108.72.113/32`. 이 실행에서는 호스트 접속·방화벽·배포를 수행하지 않았다. 로컬 동작을 외부 배포 완료로 간주하지 않는다.

1. 호스트/운영자 승인 후 전용 비특권 OS 사용자, Python 3.12+, ffmpeg, Nginx, 영속 데이터 경로(0700), 서비스 프로세스(umask 0077)를 준비한다. 관리 SSH ACL은 별도 유지하고 작업 중 관리 접근을 끊지 않는다.
2. 외부 보안 그룹/방화벽에서 TCP 10000은 `222.108.72.113/32`만 허용, 앱 내부 포트 10001은 외부 비공개. Nginx pre-app ACL 예시는 `nginx.conf.example`. 이중 ACL을 적용하고 실제 거부 로그/접속을 검증한다. forwarded header로 ACL을 우회하지 않도록 실 IP 신뢰 설정을 임의 추가하지 않는다.
3. TLS 인증서가 준비되어야 Nginx 예시가 시작된다. IP 인증서 또는 승인된 도메인/접근 URL 합의가 필요하다. HTTP IP URL과 HTTPS 요구 충돌은 미해결이며 **외부 배포 차단 항목**이다. 인증서를 제거하거나 HTTP로 몰래 변경하지 않는다.
4. 키는 서버의 권한 제한 환경 파일/secret manager로 주입(저장소 밖). `FLF_ALLOWED_HOSTS=101.79.23.235`, `FLF_SECURE_COOKIE=1`, 적절한 `FLF_DATA` 설정. Object Storage 보관/수명 정책과 계정 quota·요금 알림도 설정한다. 계정 키는 최소 권한.
5. 앱은 `uvicorn app:app --host 127.0.0.1 --port 10001 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log`로 서비스 실행한다. systemd 등으로 자동 재시작, 전용 사용자/디렉터리, read-only 소스, 쓰기 허용 데이터 경로, 메모리/CPU 제한을 설정한다. 데이터 볼륨은 demo/live 별도 권장.
6. `nginx -t` 후 승인된 반영. 앱 loopback health, 평가자 IP의 HTTPS UI/upload/완료/채팅, 비허용 IP 403 또는 네트워크 차단, 내부 포트 비공개, 세션 간 job 격리, 재시작 후 job 복구, 제공자 401 비재시도, TTL 삭제를 증거로 기록한다. 두 실제 출발지 네트워크 검증 없이 ACL 통과를 주장하지 않는다.
7. 롤백 시 앱/Nginx를 이전 버전으로 복구하되 영속 DB/음성을 덮어쓰지 않는다. 로그에 키·전사·번역·질문·쿠키를 남기지 않는다. 업로드/쿠키/DB는 민감자료로 취급한다. Object Storage 복사본도 별도 삭제한다.

리뷰 수정 후 운영 주의: `/ready`와 `/health`가 worker starting/recovering/exhausted/dead 상태를 503으로 드러낸다. 연속 인프라 실패 5회 후 원인을 해결하고 앱을 재시작한다. 프로세스가 살아 있다는 이유만으로 healthy로 취급하지 않는다. 불명 ledger를 임의 삭제하거나 이전 Draft로 롤백하여 유료 POST를 재호출하지 않는다. 전역 입장/DB 한도와 decoder OS 제한은 `README.md` 및 `docs/REVIEW_FIXES.md` 참조.

삭제 intent/tombstone은 unlink 전에 DB에 commit한다. unlink 후 DB finalize가 실패하면 워커가 tombstone 작업의 삭제만 재개하며 결과 접근은 410이다. 이 플래그를 무시하는 구 Draft로 rollback하여 누락 미디어 작업을 다시 실행하지 않는다. 전원 손실/물리 디스크 장애 검증은 로컬 fault injection과 별개로 필요하다.

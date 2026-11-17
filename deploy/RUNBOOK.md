# 배포 runbook — 설정 예시만, 활성화 미승인/미실행

## 리뷰 수정 우선 적용

아래 과거 Object Storage PUT 설명 대신 [REVIEW_BLOCKERS](../docs/REVIEW_BLOCKERS.md)의
callback 단일 수신 경로를 적용한다. 새 세션은 OBS 별도 복사본을 만들지 않으며 이전
manifest의 정확한 객체/버전 삭제만 SDK로 재개한다. `FLF_PUBLIC_BASE_URL`을 공개 HTTPS
origin으로 설정하고 provider callback 경로에 capability 인증/8MiB body cap/rate limit/
URL 로그 금지를 적용한다. evaluator ACG의 443 단일 평가자 allowlist는 provider callback을
차단할 수 있다. 확인된 제공자 CIDR 또는 승인된 별도 ingress 방안 없이는 live 배포 금지.
임의로 전체 포트를 개방하거나 provider CIDR를 추정하지 않는다.

Nginx는 `proxy_request_buffering off`, HTTP/1.1, 재시도 off를 유지한다. 운영자는
`/var/lib/nginx/flf-client-body`를 전용 Nginx 사용자 0700, 별도 128MiB quota filesystem으로
준비하는 변경안을 승인받는다(TEMPORARY_DECISION). buffering off여도 proxy 모듈/설정 변경에
따른 fallback disk write가 생기면 공유 루트 디스크를 채우지 않도록 한다. app/spool 입장
예산은 별도이며 nginx quota를 승인/설정/검증했다고 주장하지 않는다. Nginx crash 후 정리는
정지 확인→활성 프로세스 없음/기존 전용 temp 디렉터리 확인→그 디렉터리의 잔여 temp만 제거→
재시작 순서로 승인된 운영자가 수행한다. 실행 중 임의 `rm -rf`/사용자 데이터 삭제 금지.
버퍼링/HTTP 버전/상한/rate zone 변경 뒤 chunked 업로드, 중간 disconnect, 재시도 없음,
실제 temp 사용량/quota 거부를 테스트해야 한다. 5r/s API, 2r/m 업로드, 10r/s callback과 burst는
임시 선택이며 PM의 rate-limit 요구 구현이지 승인된 숫자/금액 예산이 아니다.

`flf.service.example`은 앱의 multipart 임시 파일에 TMPDIR=/tmp 및 서비스 전용 256MiB
tmpfs(/var/tmp 16MiB) quota를 명시한다. 현재 기본 동시검증 2 × 업로드 100MiB + 여유를
기준으로 한 TEMPORARY_DECISION이다. 호스트 전체 /tmp를 지우거나 바꾸는 명령이 아니다.
YAML 업로드/동시수 한도를 변경하면 앱 spool tmpfs, MemoryMax, 데이터 볼륨 quota 및
Nginx client_max_body_size/callback body cap도 함께 검토·변경해야 한다. 권한·mount 지원·
quota 소진 응답·restart cleanup은 실제 호스트에서 승인 후 검증할 사항이다.

확정 매트릭스: 같은 호스트 Nginx `http://101.79.23.235:10000` → 308
`https://101.79.23.235:443`, 앱 `127.0.0.1:10001`. 문서의 HTTP 평가 URL을
HTTPS 진입 리다이렉트로 해석한 요청이며 A1/A4 원문을 수정한 것이 아니다.
PM의 원문/관리자 댓글 대조 및 평가자 동의 확인이 남아 있다.

## 승인 게이트

아래 작업은 모두 운영자 사전 승인이 필요하며 이번 작업에서 실행하지 않았다:
호스트 접속/패키지 설치, 전용 OS 사용자 생성, ACG/방화벽/공개 포트 변경,
인증서 발급/갱신 설정, Nginx 설정 설치/reload, systemd 설치/enable/start.
관리 SSH 접근은 별도 승인 ACL로 보존한다.

1. Python 3.12+, ffmpeg/ffprobe, Nginx 준비. 소스 `/opt/flf`는 비특권 `flf`
   사용자에 읽기 전용, 데이터 `/var/lib/flf`는 0700으로 쓰기 허용. 기존 데이터를
   덮어쓰거나 삭제하지 않는다. 비밀 환경 파일 `/etc/flf/flf.env`는 0600,
   systemd가 읽어 전달하며 저장소에 넣지 않는다. `flf.service.example` 검토.
2. 평가 모드: `access-evaluator.conf.example`을 `/etc/nginx/flf-access.conf`로
   설치하는 변경안을 승인받는다. ACG 및 호스트 방화벽 TCP 10000/443 모두
   `222.108.72.113/32`만 허용. 최종 공개 모드는 별도 승인 후
   `access-public.conf.example`과 두 포트의 공개 ACL로 전환한다. 앱 10001은
   항상 loopback 전용이며 외부에서는 열지 않는다. X-Forwarded-For를 신뢰해
   ACL을 계산하지 않는다. Nginx가 전달 헤더를 덮어쓰고 uvicorn은 127.0.0.1만 신뢰.
3. **브라우저 신뢰 IP SAN 인증서가 없으면 외부 서비스 시작 금지.** 자체 서명,
   인증서 경고 무시, 가짜 발급 완료 주장을 하지 않는다. IP SAN 및 짧은 수명
   프로파일을 지원하는 공인 CA/ACME 클라이언트를 운영자가 선정·검증한다
   (예: Let's Encrypt IP/short-lived 지원 여부와 현재 클라이언트 호환성 확인).
   IP 제어 검증용 HTTP-01의 80 또는 TLS-ALPN-01의 443 접근이 평가자 ACL과
   충돌할 수 있으므로 필요한 검증 포트/CA 접근 예외도 별도 승인한다.
   발급 성공 후 SAN=101.79.23.235, 체인, 만료일을 실제 브라우저에서 확인하고
   `/etc/flf/tls/fullchain.pem`, `privkey.pem`에 설치. 자동 갱신 timer를 최소
   매일 점검/실행하고 수명의 1/3 이하 주기로 갱신을 시도하도록 CA 정책과 맞춘다.
   deploy hook은 `nginx -t` 성공 후에만 reload. 만료 임박/갱신 실패 알림과
   실제 자동 갱신 리허설 증거가 필요하다. 이 문서는 발급 명령 성공의 증거가 아니다.
4. `nginx.conf.example`은 http context 예시다. 평가/공개 모드 중 하나만 include.
   `FLF_SECURE_COOKIE=1`, `FLF_ALLOWED_HOSTS=101.79.23.235`, 서버에만 API 키 설정.
   승인 후 `nginx -t`, systemd 검증/활성화. `.env`를 Nginx 정적 경로에 두지 않는다.
5. 과거 Object Storage 전용 bucket/prefix는 이 앱만 사용하도록 격리. 최소 권한:
   지정 객체 DELETE, 버전 목록 조회/버전 DELETE. 앱은 manifest의 정확한 job별 두 키만
   삭제하고 버전/삭제 마커도 제거한다. 권한 부족/보존 잠금/서비스 장애는 durable
   tombstone으로 남겨 재시도하며 삭제 완료라 보고하지 않는다. 복제/백업/제공자
   Speech 자체 보관은 별도 운영 정책으로 확인해야 한다. 새 callback 세션은 `resultToObs=false`와
   필수 callback URL을 함께 보내며 입력/출력 JSON 별도 PUT는 없다. 실제 Ncloud 호환성은 미검증.
6. 금액 예산 미응답: demo로 먼저 검증. live 및 유료 테스트는 예산/호출 승인을
   따로 받은 뒤 수행. YAML 한도는 금액 예산이 아니며 무제한 사용 승인이 아니다.
7. 실제 두 출발지에서 HTTP 308/HTTPS 정상, 평가 모드 비허용 IP 403/네트워크 거부,
   공개 모드 로그인 없는 접근, 10001 외부 차단, secure cookie/Origin 검증을 기록.
   재시작/새로고침 lease 유지, 여러 탭 중 하나 종료 시 전부 접근 차단,
   heartbeat 중단 TTL 삭제, 외부 객체/버전 삭제를 실제로 확인한다.
8. `/health`, `/ready`는 worker 이상 시 503. 연속 인프라 실패 5회 후에는 원인을
   해결하고 프로세스를 재시작한다. systemd `Restart=on-failure`는 프로세스 비정상
   종료를 처리하지만 살아 있는 exhausted worker를 재시작하지는 않으므로 readiness
   모니터/운영자 대응이 필요하다. 불명 유료 ledger를 지워 재전송하지 않는다.

롤백: 소스/서비스만 이전 승인 버전으로 복구하되 DB/오디오를 덮어쓰지 않는다.
deleting/tombstone을 무시하는 구 버전으로 되돌리지 않는다. 키·쿠키·질문·API 본문을
로그에 남기지 않는다. 호스트/네트워크/공인 TLS/유료 API 검증은 전부 미실행이다.

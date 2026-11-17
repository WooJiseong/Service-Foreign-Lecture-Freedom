# 독립 리뷰 FAIL 후 수정 — 재검토 대기

> 현재 범위/상태는 [CURRENT_STATUS](CURRENT_STATUS.md)를 우선 참조한다. 사용자 handoff는
> 이전 B1/lifecycle scoped PASS를 보고하며 환경변수 예제 파일 요구는 명시적으로 철회됐다.
> 아래 missing-file permission blocker는 과거 이력이고 현재 미완료 deliverable이 아니다.
> 권한을 고치거나 대체 예제를 만들어 해결한 것은 아니다.

이 문서는 권위 요구사항을 수정하지 않는다. PM이 확인한 A1 §8의 async 결과 수신 누락과
독립 리뷰 차단 항목을 수정하는 개발 기록이다. 이전 ITERATION_DECISIONS/TESTS의
앱 PUT 복사본, heartbeat 자동 legacy 채택, 단일 워커 삭제 설명은 아래 설계로 대체된다.
기존 테스트 결과는 과거 실행 기록이며 이번 수정의 증거로 재사용하지 않는다.

## 1. 업로드 crash staging

`upload_staging`에 무작위 새 경로를 SQLite commit한 **후** 파일을 연다. 파일/디렉터리를
fsync한 후 검증하고 job 생성과 staging 행 제거를 한 DB transaction에서 commit한다.
프로세스 파일 lock을 얻은 startup은 기존 staging intent만 대조하며 job이 참조하지 않는
파일을 제거한다. 런타임 reaper는 admission mutex/active_staging 및 기존 upload reservation과
조정하여 진행 중 write/decoder를 삭제하지 않는다. 기존의 등록되지 않은 사용자 파일을
glob하여 지우지 않는다. unlink 실패는 intent가 남아 재시작/재시도로 복구된다.
multipart spool은 파일 처리 중에만 존재하며 Linux의 익명 TemporaryFile은 프로세스 crash에
자동 정리된다. 새 staging은 intent로 복구되고 기존 legacy 무등록 파일은 별도 승인 처분 대상이다.

## 2. 외부 삭제 독립성/경쟁

처리 워커, 로컬 lease/staging reaper, 외부 cleanup 워커를 분리했다. job A의 STT/chat
네트워크 대기는 job B의 TTL 객체 삭제를 막지 않는다. cleanup은 영속 tombstone/정확한
manifest/재시도 시각으로 재시작 가능하다. API /end는 즉시 local tombstone 및 private cache
삭제 후 같은 job guard를 사용하는 외부 작업 종료까지 202 pending을 반환할 수 있다.
진행 중 legacy PUT가 늦게 끝나도 같은 guard가 풀리기 전 삭제를 finalize하지 않으며
그 후 정확한 객체/버전을 정리한다. 새 코드에는 별도 OBS PUT가 없다. 이미 제공자 서버로
전달된 과거 요청의 불명확한 종료/제공자 자체 보관까지 zero-retention을 보장하지 않는다.
외부 삭제 자체가 오래 걸리면 다른 외부 삭제도 지연될 수 있으므로 readiness/삭제 backlog
감시가 운영 전 필수다. 작업 A의 인식 대기와는 독립이다.

TEMPORARY_DECISION: lease 180초, heartbeat 30초, reaper 500ms(0.5초), cleanup 500ms,
외부 삭제 재시도 5..300초 backoff. 사용자 승인 숫자가 아니며 service.yaml에서 검증/설정한다.

## 3. 공식 Speech async callback 결과 수신

2026-11-17 읽기 전용으로 확인한 NAVER 공식 문서:

- https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence-local
  `params.completion=async`에는 `callback` 또는 `resultToObs` 필수. callback 존재 +
  resultToObs=false는 callback에만 결과 반환. 둘 다 없는 조합은 오류.
- https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence-getjobstatus
  GET `/recognizer/{token}`은 상태/segments 조회 계약이며 callback 필수조건의 대체가 아니다.

**선택: callback 단일 결과 경로.** 새 job은 server-side DB에 256-bit job별 capability를
생성하고, `FLF_PUBLIC_BASE_URL/api/speech/callback/{job}/{secret}`를 async params.callback으로
보낸다. resultToObs=false. 사용자의 쿠키/추측 가능한 job ID만으로 전달을 승인하지 않는다.
capability는 public 응답에 절대 포함하지 않으며 종료 시 지운다. 실제 dispatch ledger가 있는
live job에 한하여 일정 길이의 provider token과 일치해야 한다. ack 전에 도착한 callback은
그 job capability+dispatch 상태로 검증하여 ack token ledger를 확정할 수 있다. 일반 CSRF
헤더가 없는 제공자 호출은 이 전용 경로만 예외이며 다른 API는 기존 Origin/CSRF 검증 유지.

callback JSON은 stream 단계에서 크기를 제한한 뒤 파싱, text/segments/상태/token을 검증한다.
수신 결과는 `speech_results`에 영속화하고 처리 워커가 transcript로 원자 이동하며 중복
복사본을 남기지 않는다. job/token/내용 digest로 같은 전달을 멱등 처리, 다른 내용은 거부한다.
종료/만료/없는 job은 body를 보관하지 않고 204로 버린다. 읽는 중 종료되어도 transaction에서
다시 상태를 확인하므로 resurrection이 없다. callback 대기 중 처리 워커를 점유하지 않는다.
기한 초과/제공자 FAILED/TIMEOUT은 표시하고 이미 수락된 음성을 재과금 재전송하지 않는다.

새 세션에 입력 음성/결과 JSON을 OBS에 별도 PUT하지 않는다(Q3 별도 보관 사본 불필요).
결과 수신에 OBS read는 필요 없으므로 사용하지 않는 generic GET를 구현했다고 주장하지 않는다.
정식 OBS 변수/SDK 삭제는 이전 앱 객체의 승인된 정리를 위해 유지하며, 새 callback 결과
수신을 Object Storage 통합이라고 부르지 않는다. PM이 OBS 기반 수신을 추가로 요구하면
공식 결과 key/도메인 설정을 먼저 확정해야 하며 이번에 미사용 GET를 덧붙이지 않는다.

운영 요구: 공개 HTTPS base origin/신뢰 인증서, 실제 callback 전달 가능 네트워크/Nginx,
secret URI를 보관하지 않는 access/error/APM 로그 정책. Nginx callback location은 access off,
error /dev/null. 앱 uvicorn은 --no-access-log. TLS 종단/보안장비에도 URL 로그 금지 필요.
공식 문서는 provider 임의 인증 헤더/서명 기능을 보장하지 않으므로 그런 기능을 꾸며내지 않고
URL capability를 사용한다. 실제 callback HTTP 전달/재시도/중복/지연 및 payload는 mocked
계약 검증뿐이며 live 검증이 필요하다. evaluator allowlist와 제공자 callback ingress 예외가
충돌하므로 승인된 제공자 CIDR/전용 ingress 합의 전 evaluator live 활성화는 차단한다.

## 4. public 자원 상한

Nginx proxy_request_buffering off + HTTP/1.1 + proxy_next_upstream off로 불필요한 업로드
디스크 사본 및 upstream 재전송을 막는다. app multipart spool+검증용 파일의 일시적 두 벌은
MAX_STORAGE 입장 예약에 반영되며 활성 처리 후 spool은 닫힌다. dedicated Nginx temp fallback
quota 및 crash cleanup은 runbook 승인 단계. 디렉터리/호스트 quota를 이번에 생성하지 않았다.
API 5r/s, upload 2r/m, callback 10r/s와 burst는 실제 limit_req_zone/limit_req로 연결했으며
모든 수치는 TEMPORARY_DECISION이다. 비용 예산 승인이 아니다.

heartbeat는 읽기 확인 후 최소 heartbeat 간격이 지나야 조건부 UPDATE하므로 여러 탭/반복 호출이
DB write flood를 만들지 않는다. 진행 중 Store.save는 최신 lease/heartbeatAt을 보존한다.
provider HTTP는 Accept-Encoding=identity로 요청하고 압축 응답을 파싱/압축해제 전에 거부한다.
Client.stream에서 Content-Length 및 identity iter_bytes를 누적 한도 검사 후 JSON 파싱한다.
POST의 한도 초과/전송 불명은 재과금 방지를 위해 ambiguous로 기록.
config.BOUNDS 및 교차검증으로 숫자 폭주/비현실적 동시수/예약예산 부족을 시작 단계에서 거부한다.

## 5. 기존 데이터: 보존 격리 및 승인된 처분 계획

lease 없는 구 job은 격리. 자동 실행/TTL 삭제/heartbeat 자동 채택 없음. 같은 소유권으로
기존 결과를 조회할 수 있지만 chat/retry/submit은 차단한다. owner가 UI 또는 명시 POST
`/api/jobs/{id}/adopt`로 새 임시 세션 정책에 동의하면 lease를 부여한다. submitted=false로
설정하여 채택만으로 유료 작업을 재개하지 않는다. owner /end는 기존 삭제 절차 사용.

재리뷰 명확화: 채택된 구 job은 `legacyReadOnly=true`로 **기존 결과 조회/종료 전용**이다.
heartbeat는 임시 lease만 유지한다. 미완료 상태(STT_RUNNING/TRANSLATING/SUMMARIZING 등)는
보존된 checkpoint 표기이지 실행 중이라는 뜻이 아니다. submit/retry/chat 및 워커 실행은
차단하고 token/전사/번역/요약/불명 ledger를 초기화하지 않는다. 안전한 checkpoint 재개는
이번 구현에 없으며 별도 승인·설계·독립 검증 없이는 제공하지 않는다.

운영 전 PM/독립 reviewer/관리자의 **별도 검토·승인이 필요한 disposition 계획**:
1. 운영자는 데이터 본문/credential 없이 격리 job 수, 소유권 회수 가능 여부, 생성 시각,
   manifest 유무, 무등록 파일 수를 제한된 관리 채널에서 inventory한다. 공개 API 제공 안 함.
2. 소유권이 있는 사용자는 보관 정책을 알리고 채택 또는 종료를 선택한다. 자동 TTL을 소급하지 않는다.
3. 소유권을 잃은 데이터와 무등록 파일은 관리자가 권한/법적 보존 필요/삭제 범위를 검토하여
   정확한 job ID 및 파일/외부 key 목록으로 처분안을 승인한다. 백업·복제·provider 보관은 별도.
4. 승인된 점검 창에 백업 보존 필요 여부도 승인받고, 식별 본문을 복사하지 않는 삭제 도구를
   독립 리뷰/드라이런 후 실행한다. 이번 수정에 무승인 자동 정리나 관리 삭제 CLI는 넣지 않는다.
5. DB/cache/local/object versions 및 실패 tombstone을 대조하고 비식별 건수/실패만 증거로 기록한다.

이 계획의 **검토/처분 승인은 아직 없다**. 따라서 모든 기존 데이터까지 session-only 정책
전환이 완료되었다고 주장하지 않는다. 보존된 구 data를 무단 삭제하여 테스트를 맞추지 않는다.

## 미완료 게이트

`.env.example`의 실제 permission denial 그대로 유지(xfail). 생성/다른 이름/다른 도구/정책 수정
우회 없음. 이번 파일 추가를 재시도하지 않는다. PM 추적 기록, 독립 재리뷰, legacy 처분 승인,
금액 예산, callback 실제 배포와 provider 전달, Ncloud 삭제 API/버전 권한, Nginx syntax/host
quota/ACG/firewall/TLS/systemd 활성화는 미실행/미검증. 커밋/푸시/YouTrack 쓰기 없음.

# 독립 리뷰 FAIL 후 수정 기록

아래는 개발자 수정/회귀 증거다. 독립 재리뷰 통과를 의미하지 않는다. 원격 작업/커밋 없음.

## F1 — 과금 불명 요청
- POST의 5xx, transport 오류, 2xx JSON 파싱 오류, 사용 불가 Speech ACK는 `AMBIGUOUS_*`. ledger는 uncertain 또는 크래시 전 inflight를 유지한다.
- job 오류 문구뿐 아니라 ledger 자체도 검사하여 retry를 거부한다. 재시작·직접 실행 재개도 같은 ledger를 확인한다. 기존 failed ledger 중 certainty 정보가 없는 행은 uncertain으로 이관한다.
- 확정 실패는 오류를 ledger에 저장하고, 저장 장애 후 워커 재개만으로 재호출하지 않는다. 명시적 단계 retry 또는 같은 채팅 intent의 확정 실패 retry만 해당 실패의 재호출을 승인한다. 429의 제한 backoff 정책은 유지한다.
- accepted Speech + malformed JSON / 500 / 502 / 503 / ACK 누락을 mock하고 재시작·retry 시 POST 횟수 1을 검사한다. 실제 제공자 대조/관리자 복구 UI는 여전히 미구현.

## F2 — 근거 및 후속 질문
- summary도 명시 근거 후보에 포함한다. 한국어 어미와 작은 동의어 사전을 정규화하고 일반적 요청 단어는 검색 점수에서 제외한다.
- 「더 자세히 알려줘」 등 제한된 후속 표현은 직전 **같은 작업**의 근거 중 현재 해당 작업 자료와 일치하는 항목만 상속한다. 직전 답변에 근거가 없으면 상속하지 않는다. 새 주제 단어가 포함된 질문은 이 경로를 사용하지 않는다.
- 요약에서만 등장하는 개념/어미 변형, 후속 질문, 무관한 주제, 다른 작업/다른 소유자를 검사한다. 범용 의미 검색/한국어 패러프레이즈 해결을 완성했다고 주장하지 않는다.

## F3 — 워커 감시와 readiness
- queue/TTL/상태·완료·실패 저장 오류를 워커 바깥에서 감시한다. SQLite/파일 저장 오류는 제공자 FAILED로 덮어쓰지 않고 durable checkpoint에서 재개한다. ledger 불명 상태는 절대 초기화하지 않는다.
- 연속 실패 최대 5회, 지수 지연 0.2~2초. 복구 중 `/ready`, `/health` 503; 5회 소진 후 exhausted 상태로 운영자 재시작 대기. 워커 사망도 readiness 503이다. 상세 예외/자료 내용은 노출하지 않는다.
- 실패 회수는 전체 tick 성공 후 초기화한다. 긴 제공자 요청은 HTTP timeout으로 제한되며 readiness가 진행률이나 품질을 보증하지 않는다.
- 현재 삭제 프로토콜은 unlink 전에 intent/tombstone을 commit하고, unlink 후 최종 DB 정리를 commit한다. unlink/최종 DB 완료 실패는 tombstone으로 복구하므로 미디어가 없는 runnable job으로 되돌아가지 않는다. stage/completion/failure-save, queue transient/exhaustion, TTL/삭제 오류를 주입해 검증한다.

## F4 — TEMPORARY_DECISION: 전역 자원 입장
- 모든 쿠키 합계 보관 작업 50개, CREATED/대기/실행 20개, 총 저장 예산 2 GiB, SQLite 64 MiB, 업로드/검증 예약 2개. failed→retry도 queue 한도를 검사한다.
- 사용자 quota와 전역 한도는 **multipart parsing/디코딩 전** 검사한다. spool+파일의 최악 크기와 DB 예산을 예약한다. 실제 디스크 파일(고아 파일 포함)을 입장 계산에 포함하므로 프로세스 크래시의 고아가 공간 계산에서 사라지지 않는다. 고아 자동 삭제는 별도 운영 작업이다.
- 요청 취소 시 예약 소유권을 관리한다. endpoint가 소유한 예약은 디코더 스레드 종료 전 반환하지 않으며, 종료된 예약을 뒤늦은 endpoint가 사용할 수 없다.
- 별도 exec wrapper에서 CPU 30초, 주소 공간 512 MiB, stdout 파일 256 KiB, fd 64, core dump 0을 설정. ffprobe wall timeout 20초/ffmpeg 60초, decoder threads 1. stderr는 저장/캡처하지 않아 진단 로그 바이트 0, stdout만 최대 256 KiB 읽는다. Python multi-thread의 preexec_fn은 사용하지 않는다.
- 쿠키 교체, quota 선검사, 병렬 validation, malformed media, OS rlimit, 진단 폭주·출력/메모리 초과를 검사한다. 커널 격리 sandbox/디스크 암호화/운영 cgroup을 대체하지 않는다. 전역 일일 과금 예산은 여전히 별도 필요하다.

## F5 — 작업별 채팅 동기화
- 전역 mutex는 짧은 registry/admission 변경에만 사용한다. 제공자 네트워크는 작업별 nonblocking guard 아래 실행하며, 다른 작업의 업로드/제출/처리는 계속된다.
- 같은 작업의 동시 채팅/삭제/상태 변경은 409. chat이 먼저 guard를 잡으면 삭제는 409, 완료 후 삭제 가능; 삭제가 먼저 완료되면 이후 chat은 404. TTL도 동일 guard를 따른다.
- `chat_requests`에 ID/질문/동결 context를 트랜잭션으로 예약한다. 같은 ID의 다른 질문은 거부. 동일 intent 재개는 캐시를 재사용하고 대화 append와 요청 done 전환은 같은 DB 트랜잭션에서 완료한다. 다른 pending/uncertain intent가 있으면 새 intent는 거부한다.
- 지연된 채팅 중 다른 작업의 제출→완료/삭제/업로드가 성공하는지, 동일 요청 경쟁/삭제 경쟁, 답변 캐시 후 DB 완료 실패·재시작 replay가 호출/대화 1개인지 검사한다.

## F6 — 브라우저 전송 유실
- 전송 전에 intent의 ID/질문을 해당 탭 `sessionStorage`에 기록한다. 오류 후 같은 ID/질문으로 서버 요청 상태를 먼저 조회한다. done이면 결과를 복구하고 POST하지 않는다. 기록 없음/확정 실패는 원래 intent를 재전송한다. uncertain은 관리자 대조로 차단한다.
- intent 미해결 동안 새 질문으로 ID를 바꾸지 못한다. 작업별 저장, reload 복원, 성공/명시 삭제 시 제거. 질문을 브라우저 탭에 임시 저장하는 개인정보 범위가 추가되며, 저장 불가 시 유료 전송 전에 중단한다.
- Node에서 완료 응답 유실→reload→GET 재조정 시 POST/paid mock/history 각각 1, 수신 전 유실의 같은 ID replay, uncertain 유지/차단을 실행한다. 실제 브라우저 렌더링 E2E는 별도이다.

## 추가 요약 검증
지정 제목의 존재/순서뿐 아니라 각 제목 사이에 실질 내용이 있어야 완료한다. 제목 네 줄만 반환하는 mock은 `SUMMARY_SECTION_EMPTY`로 실패한다. 내용의 의미 정확성/완전성은 실제 API 품질 평가가 필요하다.

## PM authoritative crosscheck 후 보완
- 사용자 handoff에서 이전 **F1–F6 scoped re-review PASS**와 PM의 FLF-1/FLF-2 Stage Review 확인을 전달받았다. live/full VERIFIED는 아니다.
- **FR23:** 실제 Studio outbound Chat SYSTEM role에 required summary JSON을 명시적 untrusted 인용 경계로 추가. source가 닫는 태그/개행을 주입해도 경계를 닫을 수 없도록 인코딩한다. USER의 transcript/history/question을 시스템 명령으로 승격하지 않는다. 두 후속 Chat의 실제 outbound roles/payload를 mock transport로 검사한다.
- **FR12:** 새 작업은 문단→문장→불가피한 최대길이 순으로 분할하며 공백/개행/전체 원문을 보존한다. 호출 전 영속 manifest에 offsets와 내용 hash ID를 저장한다. cached chunk를 순서대로 연결하며 추가 개행을 만들지 않는다. 이미 호출된 v1 부분 작업은 과금 보존을 위해 원래 입력 경계를 유지한다.
- **N1:** storage getter/쓰기 실패를 부팅 시 처리. paid chat만 disable하고 설명을 표시하며 demo chat은 volatile memory fallback. Node mock DOM에서 앱 부팅·업로드·결과·탭·채팅 모드별 정책을 검사한다.
- **N2:** dedup hash 계산보다 quota/admission 검사가 먼저이므로 capacity에서 기존 동일 파일 재업로드도 거부될 수 있다. 안전한 자원 제한을 우선하며 기존 job 선택/조회로 이어가도록 안내한다. 이 보수적 정책은 버그 해결 완료라고 숨기지 않는다.
- **N3:** durable deletion intent→unlink→DB finalize. finalize 실패·재시작의 missing-media window에도 tombstone이 남아 신규 처리/노출을 차단하고 삭제만 재개한다. SQLite atomic commit 및 파일 시스템의 정상 오류 보고를 전제로 하며 전원 손실/물리 디스크 장애 실증은 별도다.
- 실제 A-1 AC01–12 / A-4 AT01–12 대응은 `TRACEABILITY.md`. Papago 공식 정책 조회 및 적용 근거는 `PAPAGO_ATTRIBUTION.md`.

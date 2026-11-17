# Draft 구현 기록 — 요구사항 원문 대체 아님

## 근거 / 외부 상태
- 구현 근거는 사용자 handoff의 PM authoritative crosscheck 확인 결과와 A-1/A-4 매핑이다. PM의 FLF-1/FLF-2 Stage Review 갱신도 확인 전달받았다. 개발자 YouTrack 쓰기/직접 MCP 원문 재조회 성공을 주장하지 않는다.
- GitHub read-only: 인증 사용자 WooJiseong, 대상 저장소 contents 조회가 `409 Git Repository is empty`를 반환. 로컬/원격 커밋·브랜치·푸시·PR 생성 없음. gh CLI 없음.
- 최초 임의 AC 번호는 제거했고, 이후 전달된 **실제 PM 확인 A-1 AC01–12/A-4 AT01–12 매핑**을 `TRACEABILITY.md`에 반영했다. F1–F6 scoped 재리뷰 PASS와 live/full 검증을 구분한다.

## TEMPORARY_DECISION (PM 기록 후보)
1. FastAPI + 정적 JS/CSS, SQLite + 파일 영속 볼륨. 단일 프로세스/순차 작업 워커를 파일 잠금으로 강제. 가용성/수평 확장 보장 없음.
2. 256-bit HttpOnly/SameSite=Strict 익명 소유권 쿠키; DB에는 SHA-256 소유자 식별자만 저장. job UUID 단독 접근 불가. 계정 로그인/세션 복구/기기 간 공유는 미구현. HTTPS 전에는 외부 실데이터 업로드 금지. 커스텀 요청 헤더 + Origin 검사, CORS 미허용, 호스트 제한, CSP, textContent 렌더링.
3. 100 MiB, 120분, 사용자당 보관 작업 10개, 작업당 유료 시도 200회/질문 20회/질문 1000자, 전사 200000자. 파일형식은 확장자와 ffprobe 컨테이너를 대조하고 전체 ffmpeg 디코딩 검증. 비디오 스트림 거부. 임시 요청 총량은 파일 한도+1 MiB로 제한. decode/probe 시간 초과는 보수적으로 거부.
4. 7일 후 워커가 로컬 작업/파일/캐시 삭제; 사용자 명시 삭제 가능(실행 중 작업은 종료 후). 제공자 Object Storage 복사본/백업의 보관·삭제 정책은 운영자가 별도 설정해야 한다. 디스크 암호화/백업/악성 미디어 sandbox는 운영 전 필수 검토.
5. 생성→명시 submit 분리; UI의 submit 동작이 업로드 후 처리 제출을 수행. 파일 선택/데모 WAV 생성은 네트워크 요청을 하지 않음. 같은 소유자+바이트 해시+모드의 job 재사용. 다른 사용자 사이에서는 콘텐츠 동일 여부를 노출하지 않음.
6. 성공한 유료 요청의 캐시와 호출 전 inflight ledger를 영속 저장. 크래시 후 응답 수신 여부 불명은 `AMBIGUOUS_CALL_RECONCILE_REQUIRED`로 실패·자동/사용자 retry 거부. 관리자 제공자 대조 후 안전한 복구 도구는 아직 없음. 분산 exactly-once는 보장 불가; 불명 요청의 중복 과금 회피를 가용성보다 우선.
7. 429는 최대 3회 지수 backoff, GET polling의 502/503/504도 최대 3회 연속 재시도. 인증/일반 4xx, POST 5xx 및 transport 불명은 자동 재시도하지 않음. 사용자는 확정 실패 후 명시 재시도 가능. polling은 3초 간격/실행당 최대 2시간; polling의 사용량은 유료호출 ledger 200회와 별도이며 제한 시간으로 제어.
8. Papago는 문단/문장 우선, 최대 5000자 lossless 순서 분할. 분할 manifest를 호출 전에 저장하고 index+내용 SHA-256 기반 ID로 성공 결과를 재사용한다. 합치는 과정에서 임의 개행을 삽입하지 않는다. 구 Draft의 과금된 부분 작업만 기존 고정 경계(v1)를 유지하는 TEMPORARY_DECISION으로 재과금을 회피한다. Studio 6000자 map 및 근거 검색 경계는 기존 캐시/이력을 재해석하지 않도록 유지한다. map 4개씩 reduce하며 모든 입력을 전달한다. 요약 실패 시 성공한 map/reduce/번역/STT 유지. 최종 heading 존재/순서/섹션 내용 및 truncation 검증. 정확성·완전성은 모델 의미 평가가 추가로 필요.
9. 채팅은 요약 + 요약/원문/번역 상위 3개 근거 + 해당 작업 최근 4턴. 한국어 어미·소규모 명시 동의어를 정규화하고, 정해진 지시형 후속 질문만 직전 같은 작업의 검증 가능한 근거를 상속한다. 범용 의미 검색은 아니므로 다른 표현을 놓칠 수 있다. 근거 없으면 서버에서 한국어 거절. 프롬프트 경계를 분리했지만 LLM prompt injection을 완전히 방어한다고 주장하지 않음. 실제 답변 근거 일치/환각/적대 입력 평가 필요. 모델 HCX-005의 최종 content만 사용; 추론 모델/필드 사용 안 함.
10. (FLF-9 이전 기록) 기본 탭 `Transition`은 A-1 우선 지시를 따른 선택이며 A-4 `Translation` 명명 충돌은 미해결이었다. **FLF-9 UI는 세 탭 대신 Summary→Origin→Translate 단일 순환 버튼으로 대체**하고 표시명은 **Translate**로 고정했다. 처리 완료 시 Summary를 자동 선택하며 전환은 로컬 표시만 바꾼다. 내부 `translation`/`transcript` 키와 `FLF_TRANSLATION_LABEL` 기본값은 legacy API 호환용으로 유지하지만 FLF-9 UI는 이 환경변수를 표시에 사용하지 않는다. 실제 브라우저 접근성/화면 회귀 검증은 별도 필요. 상세 결정/검증: `FLF9_UI.md`.
11. 애플리케이션 한도는 비용의 통화 단위 보장 아님. 쿠키를 바꿔도 전역 작업 50개/대기 20개/저장 예산 2 GiB/동시 업로드 검증 2개 상한은 유지한다. 사용자별 quota 자체는 익명 쿠키 재발급으로 우회 가능. 외부 제공자 계정 quota/결제 알림과 pre-app IP 접근 제한 필수. 대규모 인증/전역 일일 과금 예산/레이트 리밋은 추가 필요.
12. 리뷰 이후: 유료 POST 5xx/2xx JSON 파싱 또는 Speech ACK 불명은 uncertain ledger로 격리. 기존 Draft에서 오류 원인을 보관하지 않은 failed ledger도 보수적으로 uncertain으로 이관. 확정 실패 재호출은 명시적 retry 승인만 허용. 워커는 인프라 예외를 감시하고 5회 제한 복구 후 readiness를 차단한다. 자세한 F1–F6 동작은 `REVIEW_FIXES.md` 참조.
13. FR23 보완: 매 Chat SYSTEM context에 요약을 JSON 인용 데이터로 넣되 `<`/`>`/`&` 및 줄바꿈을 인코딩하여 경계 탈출을 막고 명령 권위를 부여하지 않는다. transcript/history/question은 USER에만 둔다. 모델의 완전한 prompt-injection 방어를 보장하지 않는다.
14. N1/N2/N3: storage 차단 시 paid chat만 disable하고 demo는 메모리 fallback. 입장 한도 선검사로 capacity가 꽉 찬 경우 duplicate 업로드도 거부하는 보수적 정책이다(기존 작업 선택/조회는 유지). 삭제는 intent commit→unlink→DB 최종 commit 프로토콜로 재시작 복구하며 tombstone 작업은 사용자 결과/제공자 처리에서 숨긴다.

## 공식 계약 조회 (실제 API 호출 아님)
- Speech upload: https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence-local
- Speech poll: https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence-getjobstatus
- Papago: https://api.ncloud-docs.com/docs/ai-naver-papagonmt
- Papago text translation: https://api.ncloud-docs.com/docs/ai-naver-papagonmt-translation
- Studio v3: https://api.ncloud-docs.com/docs/clovastudio-chatcompletionsv3

## 잔여 수용 조건
PM의 A-1/A-4 대조 및 현재 Draft의 최종 독립 scoped code review APPROVED(FR12/FR23, N1–N3 포함)는 사용자 handoff로 확인되었다. 브라우저 키보드/반응형 E2E, live API의 영어 인식/번역/요약·채팅 품질/보관 설정, 장시간·프로세스 강제종료·디스크 장애 실증, 외부 배포/허용·차단 검증은 미완료다. 전체 live acceptance는 NOT_VERIFIED이며 HTTPS 요구와 IP:10000 접근 요구의 조율은 미해결로 남긴다. commit/push runtime 승인 미획득으로 출판은 PUBLISH_PENDING이다.

## 출판 계획 (승인 전 실행 금지)
독립 리뷰와 수정 후 실제 원격 상태를 다시 조회. 비어 있다면 저장소 루트에 이 폴더의 앱 내용만 배치하는 `draft/flf-runnable` 브랜치 제안. 기존 콘텐츠가 생겼다면 먼저 fetch/비교 후 비파괴 통합. secret/로컬 data 제외 및 변경검토 → **개별 git commit 승인** → 커밋 → **push 승인** → push → **PR 생성 승인**. root 정책/설정 파일은 포함하지 않는다. 현재 커밋 ID 없음, PUBLISH_PENDING.

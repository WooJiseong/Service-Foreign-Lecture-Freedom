# PM 확인 A-1 / A-4 추적표

매핑 근거는 이번 사용자 handoff의 **PM authoritative crosscheck 확인 결과**다. PM이 FLF-1/FLF-2 Stage Review를 갱신했다고 전달받았다. 개발자는 YouTrack 쓰기를 하지 않았으며, PM 작업을 자신의 MCP 실행으로 주장하지 않는다. 원문 SRS를 복제하는 문서가 아니라 구현·검증 대응표다.

사용자 handoff에서 현재 Draft의 **최종 독립 scoped code review APPROVED**(F1–F6, FR12/FR23, N1–N3 포함)와 출판 gate 승인을 전달받았다. Orchestrator의 수용 범위는 로컬 Draft 구현/코드 리뷰 및 개발자 실행 테스트 증거이며, 아래 증거를 live 또는 전체 VERIFIED로 확장하지 않는다. commit/push runtime 승인은 별도다.

## A-1 AC01–AC12 (PM 확인 매핑)

|ID|확인된 수용 항목|구현 / 테스트 증거|확인 범위|
|---|---|---|---|
|AC01|작업 생성·단계 전이|`test_explicit_submit`, `test_ac01_ac02_complete_stages_and_three_nonempty_outputs`, HTTP smoke|로컬 demo|
|AC02|영문 전사·한국어 번역·요약 모두 nonempty|`test_ac01_ac02_complete_stages_and_three_nonempty_outputs`|고정 demo 언어/비어 있지 않음; live 품질 아님|
|AC03|탭 변경 시 제공자 호출 없음|`test_tabs_read_only`, `node tests/test_frontend_storage.js` 실제 탭 handler 호출 검사|Python API + mock DOM/Node; 브라우저 E2E 별도|
|AC04|근거 기반 한국어 채팅·대화 이력|`test_fr23_ac04_every_actual_outbound_chat_system_contains_untrusted_summary`, `test_chat_context_and_isolation`|실제 어댑터 outbound role/payload를 mock transport로 확인|
|AC05|지원되지 않는 질문에 부족 근거 응답|`test_f2_followup_summary_paraphrase_and_job_isolation`, `test_chat_context_and_isolation`|로컬 retrieval/demo|
|AC06|5000자 초과 입력 전체·순서 보존|`test_fr12_ac06_paragraph_sentence_boundaries_and_oversized_sentence`, `test_fr12_ac06_ac07_stable_manifest_failed_chunks_only_order_and_exact_merge`|lossless source partition + mock 번역 exact merge|
|AC07|실패 chunk만 재호출·성공 chunk 유지|`test_fr12_ac06_ac07_stable_manifest_failed_chunks_only_order_and_exact_merge`, `test_translation_resume`|ledger/manifest 영속 복구 포함|
|AC08|요약-only retry에서 전사·번역 유지|`test_ac08_summary_only_retry_preserves_transcript_translation_and_provider_counts`, `test_hierarchy_and_summary_retry`|API retry 및 STT/번역 호출 횟수 불변|
|AC09|새로고침 시 같은 작업·중복 호출 없음|`test_ac09_refresh_same_job_no_duplicate`, `test_dedup`, HTTP restart smoke|동일 쿠키/영속 DB; capacity 제한은 N2 참고|
|AC10|잘못된 입력·인증 오류 후 downstream 없음|`test_ac10_invalid_and_integrated_auth_failures_stop_downstream` (invalid/Speech 401/Papago 403), `test_real_validation`|실제 upload API + 제공자 mock|
|AC11|작업 간 context 격리·비노출|`test_ac11_crossowner_chat_status_and_crossjob_context_are_isolated`, `test_ownership_csrf`|다른 소유자의 chat status 404 및 다른 작업 context 검사|
|AC12|Papago 저작권 표기 준수|`test_ac12_papago_official_text_fallback_and_link_on_result_screen`, `docs/PAPAGO_ATTRIBUTION.md`|조회한 공식 정책의 시스템 폰트 텍스트 fallback/링크 대조|

## A-4 AT01–AT12 (PM 확인 매핑)

|ID|확인된 평가 항목|현재 상태 / 근거|
|---|---|---|
|AT01|MCP read|**PM 확인 완료** (handoff). 개발자 직접 재조회 완료라는 뜻은 아님|
|AT02|MCP write|**PM 확인 완료** (handoff, FLF-1/FLF-2 Stage Review). 개발자 YouTrack 쓰기 없음|
|AT03|실제 이력만 기록·가상 사건 금지|실제 도구 실행/실패/수정만 `TEST_EVIDENCE.md`에 기록. 장애 주입은 mock 테스트로 구분; 실운영 사건/가상 이슈를 만들지 않음|
|AT04|upload|실제 로컬 HTTP 업로드·동의·검사·명시 제출 테스트 통과|
|AT05|live STT|**PENDING** — mock 계약 검사만 수행|
|AT06|live translation|**PENDING** — mock 계약/분할/복구 검사만 수행|
|AT07|summary|로컬 계층 요약·제목/내용·retry 테스트; live 의미 품질 미검증|
|AT08|tabs|로컬 API 및 Node handler 검사; 실제 브라우저 시각/키보드 E2E 미완료|
|AT09|chat|로컬 mock/demo 근거·이력·SYSTEM context·격리·replay 검사; live 평가 미완료|
|AT10|평가자 연결|**PENDING** — `101.79.23.235:10000` 배포/연결 미검증|
|AT11|비허용 IP 차단|**PENDING** — pre-app ACL runbook만 제공, 실제 출발지 차단 미검증|
|AT12|실패 복구|로컬 queue/DB/save/TTL/삭제 tombstone 장애 주입 및 HTTP 재시작 smoke; 운영 장애 실증 아님|

## 요구사항·리뷰 추가 대응
- **FR12:** 문단→문장→최대 길이 강제 분할, 원문 문자/공백 전체 보존, 영속 chunk manifest와 내용 해시 ID. 이미 과금된 구 Draft 부분 작업은 기존 v1 경계를 유지해 재과금을 피한다.
- **FR23:** 모든 outbound Chat SYSTEM에 요약 JSON을 명시적 untrusted quote 경계로 포함. transcript/history/question은 USER 데이터로만 전달한다.
- **F1–F6:** 기존 scoped PASS 유지 여부를 회귀 테스트로 재확인. full/live VERIFIED 아님.
- **N1:** storage 접근/쓰기 차단에도 앱 부팅·업로드·탭·결과는 동작. paid chat만 차단하고 demo는 메모리 fallback.
- **N2:** capacity 선검사 때문에 기존 동일 파일 업로드도 한도에서 거부될 수 있음. 기존 job 조회/선택을 사용하며 이 보수적 정책을 문서화.
- **N3:** 삭제 intent/tombstone을 unlink 전에 commit; unlink 후 DB 완료 실패 시 runnable job으로 돌아가지 않고 숨김·복구 가능 상태를 유지.

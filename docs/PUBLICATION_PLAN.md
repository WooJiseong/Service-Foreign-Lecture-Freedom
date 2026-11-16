# Git 출판 승인 전 준비

## 대상 및 정확한 계획
- 원격 URL: `https://github.com/WooJiseong/Service-Foreign-Lecture-Freedom.git`
- 로컬 Git 루트: `/root/uos-project/FLF_Project` (상위 workspace/policies/configuration은 제외)
- 브랜치: `draft/flf-runnable`
- 원격 ref: `refs/heads/draft/flf-runnable`
- 예정 commit subject: **`feat(FLF-2): add runnable FLF lecture-learning draft`**
- 예정 commit body:
  ```text
  Implement a durable demo/live lecture pipeline, grounded Korean chat,
  ownership checks, resource limits, and PM-mapped acceptance regressions.

  Include local test evidence and a deployment runbook. Live provider APIs
  and external deployment remain unverified.
  ```
- 사용자 handoff에서 현재 Draft publication gate의 **최종 독립 scoped code review APPROVED**(FR12/FR23, N1–N3 포함)를 전달받았다. 전체 live acceptance는 NOT_VERIFIED다.
- 현재 commit ID 없음. **commit과 각 push의 실제 runtime 승인은 별도 필요**하다. 요청 자체나 도구 사용 가능 보고를 승인으로 간주하지 않는다.
- 이번 실행에 노출된 Bash API에는 승인 요청 인자가 없고 별도 permission-gated Git/승인 도구도 제공되지 않았다. 따라서 commit/push를 일반 실행으로 시험하지 않고 **승인 미획득 / PUBLISH_PENDING**으로 정지한다. 거절 결과를 받았다는 의미는 아니다. 승인 인터페이스 또는 해당 정확한 작업의 명시적 승인이 마련된 후 재개한다.

## 읽기 전용 원격 확인
이번 준비 실행에서 GitHub contents 조회는 `409 Git Repository is empty`, `git ls-remote --heads --tags`는 exit 0 / ref 출력 없음이었다. 기존 원격 내용을 삭제/변경하지 않았다. commit/push 승인 직전에 다시 조회해 새 내용이 생겼다면 fetch/비교 후 비파괴 통합 계획을 재확인한다.

`gh` CLI는 없고 Git 2.43.0 및 GitHub read 도구를 사용했다. 원격 설정/credential 설정은 변경하지 않는다. empty 저장소이므로 main/base 브랜치나 PR 생성 가능 상태를 가정하지 않으며, main 쓰기나 PR 생성은 별도 승인 없이 하지 않는다.

## 명시적 index 허용 목록 (27개)
```text
.gitignore
README.md
app.py
core.py
providers.py
media_runner.py
requirements.txt
deploy/RUNBOOK.md
deploy/nginx.conf.example
docs/DRAFT_NOTES.md
docs/REVIEW_FIXES.md
docs/TRACEABILITY.md
docs/TEST_EVIDENCE.md
docs/PAPAGO_ATTRIBUTION.md
docs/PUBLICATION_PLAN.md
static/app.js
static/chat_transport.js
static/index.html
static/style.css
tests/conftest.py
tests/smoke_server.py
tests/test_acceptance.py
tests/test_contracts.py
tests/test_review_regressions.py
tests/test_pm_acceptance.py
tests/test_chat_transport.js
tests/test_frontend_storage.js
```

`git add .` 대신 위 파일만 개별 지정한다. `data/`, DB/음성/쿠키/대화, `.env`, `.venv/`, 로그, cache, 상위 `AGENTS.md`, `.opencode/`, `opencode.json`, PII 문서는 포함하지 않는다. index diff 및 secret 검사는 commit 승인 전에 다시 실행한다. 테스트·검사 결과는 `TEST_EVIDENCE.md` 참조.

## 승인 이후에만 가능한 명령 (현재 미실행)
```bash
# 최종 scoped code review는 승인됨. 아래 commit의 별도 runtime 승인 이후에만:
git commit -m "feat(FLF-2): add runnable FLF lecture-learning draft" \
  -m "Implement a durable demo/live lecture pipeline, grounded Korean chat,
ownership checks, resource limits, and PM-mapped acceptance regressions.

Include local test evidence and a deployment runbook. Live provider APIs
and external deployment remain unverified."

# 별도 push 승인 이후, 원격을 다시 확인한 다음:
git push -u https://github.com/WooJiseong/Service-Foreign-Lecture-Freedom.git \
  HEAD:refs/heads/draft/flf-runnable
```

위 commit subject/body와 branch/ref가 이번 runtime 승인 요청의 정확한 범위다. force push/credential 설정 변경/자동 PR 생성은 계획에 없다.

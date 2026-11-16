# Papago 저작권 표기 적용 근거

## 공식 정책 조회
- 표준 가이드의 공식 index `https://guide.ncloud-docs.com/llms.txt`에서 정책 페이지 제목/경로를 확인했다:
  `https://guide.ncloud-docs.com/docs/naveropenapiv3-translation-copyright`
- 이 실행 환경에서 위 표준 페이지와 `.md` 요청은 HTTP 403이었다. 본문을 읽었다고 주장하지 않는다.
- 동일 Papago Translation의 **공식 NAVER Cloud 공공기관용 가이드**에서 정책 본문을 조회했다:
  https://guide-gov.ncloud-docs.com/docs/naveropenapiv3-translation-copyright
  도구 응답의 제목은 「Papago Translation 저작권 표기 정책」, 문서 updated/published는 2026-10-22였다. 이를 구현의 공식 표기 근거로 사용했으며, 표준 서비스 운영 전 최신 정책 적용 범위는 다시 확인해야 한다.

## 조회한 규칙과 적용
- 번역 결과 화면에 Papago 저작권 표기 필수.
- 브랜드 그래픽 적용이 불가하면 시스템/기본 폰트로 허용된 텍스트 중 하나 사용 가능: `Translated by Papago`, `Papago 번역`, `파파고 번역`.
- Papago 링크 목적지는 `https://papago.naver.com/`.
- 그래픽을 사용할 경우 최소 11px 및 왜곡/변형 금지. 이번 Draft는 배포 가능한 공식 그래픽을 번들하지 않는 텍스트 UI이므로 **공식 텍스트 fallback `Papago 번역`**을 그대로 사용한다. 유사 로고나 재현한 그래픽은 만들지 않았다.
- 결과 패널 바로 아래, 시스템 폰트 14px의 링크로 표시하고 demo는 Papago가 생성한 결과가 아님을 인접 문장에 명시한다. 링크는 `noopener noreferrer`를 사용한다.
- 정책의 브랜드 훼손/부적절한 서비스 제한 및 사전 공지 없는 변경 가능성은 운영 전 검토 대상이다. 이번 확인은 앱의 표기 구현 대조이며 법률 자문/운영 승인 또는 live 검증이 아니다.

`test_ac12_papago_official_text_fallback_and_link_on_result_screen`에서 정확한 문구·링크·결과 화면 위치·시스템 폰트/크기를 검사한다. 테스트는 외부 정책 페이지를 매번 호출하지 않는다. 정책 다운로드의 일시적 서명 URL은 코드/문서/커밋에 보관하지 않는다.

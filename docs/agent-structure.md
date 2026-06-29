# 에이전트 구조

## 현재 구현 수준

현재 MVP는 규칙 기반 함수와 저장·직접 수집 데이터로 동작합니다. `agents/`에는 이를 고도화할 내부 대화형 상담 계약을 정의했으며, 플랫폼 전체나 데이터 수집기를 에이전트로 간주하지 않습니다. 아직 서로 독립적으로 실행되는 다중 에이전트 시스템이 완성됐다는 의미는 아닙니다.

상세 역할은 다음 문서를 기준으로 합니다.

- `agents/orchestrator.md`
- `agents/policy-agent.md`
- `agents/eligibility-agent.md`
- `agents/announcement-agent.md`
- `agents/recommendation-agent.md`
- `agents/verification-agent.md`
- `integrations/announcement-pipeline.md`

## 에이전트 1: 청년주거전문상담가

- 사용자 질문 이해
- 나이, 지역, 무주택 여부, 소득 수준, 관심 유형 추출
- 조건이 부족하면 추가 질문 유도

현재는 `lib/parser`의 규칙 기반 조건 추출까지 구현되어 있습니다. 조건이 부족할 때 자동으로 후속 질문을 이어가는 기능은 향후 확장 범위입니다.

## 에이전트 2: 공고분석 에이전트

- 샘플 모드에서는 구조화된 `housing_programs.json` 데이터를 활용
- 실공고 모드에서는 LH 공개 API와 SH·GH 기관 HTML에서 공공주택만 직접 수집
- 공고 HTML·PDF·HWPX에서 자격요건, 신청기간, 공급대상, 준비서류 섹션 추출

직접 수집 데이터는 기관 원문 변경과 공공데이터 키 설정에 영향을 받으며, 결과 카드에서 출처와 확인 필요 상태를 구분합니다.

## 에이전트 3: 추천 에이전트

- 사용자 조건과 공고 데이터를 매칭
- 접수중, 모집예정, 마감 상태를 고려해 정렬
- 추천 이유와 확인 필요사항 제공

현재는 `lib/matcher`, `lib/status`, `lib/recommender`에 역할을 분리했습니다. 추천은 참고용이며 실제 자격 판정을 대신하지 않습니다.

## 목표 역할 연결

`사용자 질문 → Orchestrator → Policy / Announcement / Eligibility / Recommendation → Verification → 최종 상담 응답`

기관별 공고 데이터 수집 파이프라인은 Announcement Agent의 입력 데이터를 제공한다.

# 청년주거나침반 AI

사용자가 입력한 주거 조건을 구조화하고 LH·SH·GH 및 청약홈 국민주택 모집공고와 비교해 참고할 공고를 추천하는 공모전 출품용 MVP입니다.

## 현재 구현

- 한 번의 자연어 문장을 받는 대화형 입력 UI
- 규칙 기반 나이, 지역, 무주택 여부, 소득 수준, 관심 유형 추출
- LH·SH·GH 및 청약홈 국민주택 실제 모집공고 기반 추천과 샘플 최종 폴백
- 추천 이유, 신청기간, 지원내용, 원문 링크를 담은 결과 카드
- 신청기간 기준 접수중, 모집예정, 마감 상태 표시
- 접수중, 모집예정, 마감 순서의 정렬과 과거 공고 제공
- 모바일 화면 대응
- LH 공개 API, SH 기관 게시판, GH 청약센터, 청약홈 APT 국민주택 기반 직접 수집 모드
- 공식 상세 페이지와 PDF·HWPX 첨부파일 자동 수집
- 접수기간, 대상, 연령, 무주택, 소득·자산, 임대조건, 준비서류 규칙 기반 구조화
- 공고문 분석 품질 배지와 원문 근거를 반영한 추천 이유
- 청약 가점·공고 변동 추적·경쟁률 시범 모듈(화면 비활성)
- ICS 일정 내부 기능
- 공고 SQLite 누적 저장과 매일 오전 7시 증분 동기화 구조
- 검증된 마지막 실공고를 `data/live_housing_programs.json`에 보존하는 심사용 안전장치
- 후속 질문이 가능한 대화 흐름
- SQLite 기반 프로필·관심 공고 저장

기본 `npm run dev`는 저장된 마지막 실공고 스냅샷을 사용하고, 스냅샷도 없을 때만 출품용 샘플 데이터로 동작합니다. `npm run dev:full`은 별도 FastAPI 서비스가 기관 원본을 직접 수집합니다. 추천 카드는 모집 상태·추천 이유·신청기간만 표시하며 원문 추출 내용을 분석 결과나 지원내용으로 표시하지 않습니다. 원문 즉석 해석 버튼과 경쟁률·가점·변동 추적 UI도 신뢰도 검증 전까지 숨깁니다. 문서의 에이전트 구조는 역할을 구분한 설계이며 독립적으로 판단하는 다중 에이전트 시스템을 의미하지 않습니다.

실데이터 통합을 위한 `services/announcement-api`가 현재 화면과 연결돼 있습니다. 기본 설정은 기존 샘플 JSON을 사용하며 `dev:full` 또는 환경변수로 실공고 모드를 명시한 경우에만 외부 공고를 조회합니다.

## 청주나 내부 대화형 에이전트 구조

청주나는 플랫폼 전체가 아니라, 공공주택 상담을 위한 내부 대화형 AI 에이전트 팀으로 설계됩니다. 목표 상담 흐름은 `정책 설명 → 자격 진단 → 공고 해석 → 추천 → 검증`이며, 각 역할의 입력·출력과 안전 규칙은 `agents/`와 `rules/`에 정의합니다.

핵심 흐름:

```text
사용자 질문
↓
Orchestrator
↓
Policy / Eligibility / Announcement / Recommendation
↓
Verification
↓
최종 상담 응답
```

- Orchestrator는 질문을 분류하고 필요한 역할을 순서대로 연결합니다.
- Policy Agent는 정책과 용어를 설명합니다.
- Announcement Agent는 공고 원문을 구조화합니다.
- Eligibility Agent는 사용자 조건을 항목별로 진단하며, 가점 계산은 내부 Skill로만 수행합니다.
- Recommendation Agent는 당첨 예측이 아닌 우선 검토 순서를 제시합니다.
- Verification Agent는 근거, 최신성, 계산과 안전 표현을 최종 검증합니다.

기관별 공고 데이터 수집 파이프라인은 별도 에이전트가 아니라 추후 연결할 데이터 계층입니다. 수집 결과는 announcement database를 거쳐 Announcement Agent가 해석합니다. 현재 저장 실공고·규칙 기반 MVP 위에 이 내부 상담 계약을 단계적으로 연결하며, 완성된 독립 다중 에이전트 시스템으로 과장하지 않습니다.

현재 `/api/chat`은 질문을 정책·자격·공고·추천으로 분류해 담당 Agent의 답변을 만들고 Verification Agent 검사를 거칩니다. 지원 질문과 한계는 [`docs/conversation-capability-matrix.md`](docs/conversation-capability-matrix.md)에 정리되어 있습니다.

## 향후 고도화

- LH 상세 공고의 구조화 성공률 확대와 기관별 파서 회귀 테스트
- 스캔 PDF·구형 HWP 인식 및 근거 문장 인용을 강화한 RAG 기반 질의응답
- LH·SH·GH 공식 모집결과 기반 경쟁률 연동
- 사용자 피드백 기반 추천 개선
- 청약홈 기반 민간주택 영역 확장
- 알림, 카카오톡, 모바일 앱 확장

향후 상담 이력, 사용자 피드백, 신규 공고 데이터를 반영해 추천 품질을 고도화할 수 있는 구조를 지향합니다. 지속적으로 스스로 학습한다고 전제하지 않으며, 데이터와 피드백을 검토하고 평가해 개선하는 방식입니다.

## 프로젝트 구조

```text
app/
├─ page.tsx
├─ api/chat/route.ts
└─ components/
data/
├─ housing_programs.json
├─ lh/
├─ sh/
├─ gh/
└─ archive/
agents/
├─ orchestrator.md
├─ policy-agent.md
├─ eligibility-agent.md
├─ announcement-agent.md
├─ recommendation-agent.md
└─ verification-agent.md
integrations/
└─ announcement-pipeline.md
knowledge/
├─ policy/
├─ housing-types/
├─ eligibility/
└─ glossary/
rules/
├─ response-rules.md
├─ verification-rules.md
├─ recommendation-rules.json
└─ eligibility-schema.json
lib/
├─ agents/
├─ parser/
├─ matcher/
├─ recommender/
└─ status/
services/
└─ announcement-api/
   ├─ app/
   ├─ tests/
   └─ requirements.txt
docs/
├─ project-overview.md
├─ agent-structure.md
├─ conversation-capability-matrix.md
├─ integration-architecture.md
├─ development-backlog.md
├─ verification-report.md
├─ roadmap.md
└─ contest-notes.md
```

## 모집 상태

데이터는 `status` 필드를 지원하지만, 추천 결과에 표시되는 상태는 `apply_start`와 `apply_end`를 기준으로 다시 계산합니다. 결과는 접수중, 모집예정, 마감 순으로 정렬하며 마감 공고도 참고용으로 하단에 표시합니다.

## 실행

```bash
npm install
npm run dev
```

브라우저에서 `http://localhost:3000`에 접속합니다.

실공고 연동 개발 모드는 FastAPI 의존성을 한 번 설치한 뒤 실행합니다.

```bash
cd services/announcement-api
.venv/Scripts/pip install -r requirements-dev.txt
cd ../..
npm run dev:full
```

`dev:full`은 직접 수집 FastAPI와 Next.js를 함께 연결합니다. 기본 범위는 LH·SH·GH 공공주택과 청약홈 APT 국민주택입니다. 청약홈은 `HOUSE_SECD=01` 또는 `HOUSE_SECD_NM=국민`인 공고만 노출하고 민영주택은 저장 이력에 남아 있어도 제외합니다. `DATA_GO_KR_API_KEY`가 없으면 키가 필요 없는 SH·GH 채널만 수집하고 LH·청약홈은 건너뜁니다. `INCLUDE_PRIVATE_HOUSING=true`는 향후 민간주택 영역을 확장할 때만 사용합니다.

## 검증

```bash
npm run build
npm run test:integration
npm run test:live
cd services/announcement-api
.venv/Scripts/python -m unittest discover -s tests -v
```

`test:live`는 실제 외부 API를 사용하므로 네트워크와 원문 제공기관 상태에 영향을 받습니다.

## 배포

- Next.js 웹앱은 Vercel에 배포합니다.
- `render.yaml`은 `services/announcement-api`를 Render 웹 서비스로 배포합니다.
- 최초 실행은 최근 90일을 적재하고 이후 매일 오전 7시 최근 7일, 일요일 최근 90일을 재대조합니다. GitHub Actions는 검증을 통과한 결과만 정적 실공고 스냅샷으로 커밋합니다.
- Render 무료 인스턴스의 `/tmp` SQLite는 재시작 시 초기화될 수 있으므로 공고·프로필·관심 공고 저장은 출품용 시연 범위입니다.
- Render가 절전·재시작·오류 상태여도 Vercel은 저장된 마지막 실공고 스냅샷을 표시하며 샘플 데이터로 즉시 후퇴하지 않습니다.
- GitHub 예약 워크플로는 이 브랜치가 기본 브랜치에 병합된 후 실행됩니다.
- 웹앱의 `ANNOUNCEMENT_API_BASE_URL`에 배포된 FastAPI 주소를 설정하면 실공고 모드가 활성화됩니다.

## 주의사항

출품용 MVP는 과거 공고를 포함한 저장 실공고를 사용하며 모집 상태를 구분 표시합니다. 수집 실패 시에만 샘플 데이터로 후퇴합니다. 자동 추출 결과는 정보 탐색을 위한 참고용이며 실제 신청 자격을 확정하지 않습니다. 신청 전 반드시 해당 기관의 최신 공고 원문을 확인해야 합니다.

자세한 구현 범위는 `docs/project-overview.md`, 공고 수집 파이프라인 통합 설계는 `docs/integration-architecture.md`, 단계별 작업은 `docs/development-backlog.md`, 검증 결과는 `docs/verification-report.md`에서 확인할 수 있습니다.

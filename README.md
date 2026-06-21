# 청년주거나침반 AI

사용자가 입력한 주거 조건을 구조화하고 공공주거 샘플 데이터와 비교해 참고할 사업을 추천하는 공모전 출품용 MVP입니다.

## 현재 구현

- 한 번의 자연어 문장을 받는 대화형 입력 UI
- 규칙 기반 나이, 지역, 무주택 여부, 소득 수준, 관심 유형 추출
- 구조화된 샘플 데이터 기반 추천
- 추천 이유, 신청기간, 지원내용, 원문 링크를 담은 결과 카드
- 신청기간 기준 접수중, 모집예정, 마감 상태 표시
- 접수중, 모집예정, 마감 순서의 정렬과 과거 공고 제공
- 모바일 화면 대응
- LH 공개 API와 SH·GH HTML 기반 공공주택 직접 수집 모드
- 청약 가점·특별공급·1순위 사전 점검과 실공고 적합도
- ICS 일정과 공고 변동 추적 내부 기능
- 공고 SQLite 누적 저장과 매일 오전 7시 증분 동기화 구조
- 후속 질문이 가능한 대화 흐름
- SQLite 기반 프로필·관심 공고 저장

기본 `npm run dev`는 공모전 샘플 데이터로 동작합니다. `npm run dev:full`은 별도 FastAPI 서비스가 기관 원본을 직접 수집합니다. 공고 해석과 경쟁률 백엔드 시범 코드는 남아 있지만 데이터 완성도를 과장하지 않도록 현재 카드에서는 숨깁니다. 문서의 에이전트 구조는 역할을 구분한 설계이며 독립적으로 판단하는 다중 에이전트 시스템을 의미하지 않습니다.

실데이터 통합을 위한 `services/announcement-api`가 현재 화면과 연결돼 있습니다. 기본 설정은 기존 샘플 JSON을 사용하며 `dev:full` 또는 환경변수로 실공고 모드를 명시한 경우에만 외부 공고를 조회합니다.

## 향후 고도화

- 기관별 수집기를 청나주가 직접 운영하는 구조
- 근거 검색과 인용을 강화한 RAG 기반 공고 질의응답
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
lib/
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

`dev:full`은 직접 수집 FastAPI와 Next.js를 함께 연결합니다. 기본 범위는 LH·SH·GH 공공주택이며, 이미 저장된 청약홈 공고도 화면과 API 결과에서 제외합니다. `DATA_GO_KR_API_KEY`가 없으면 키가 필요 없는 SH·GH 채널만 수집하고 LH는 건너뜁니다. 향후 민간주택 영역을 확장할 때만 `INCLUDE_PRIVATE_HOUSING=true`로 청약홈 수집을 다시 활성화할 수 있습니다.

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
- 최초 실행은 최근 90일을 적재하고 이후 매일 오전 7시 최근 7일, 일요일 최근 90일을 재대조합니다.
- Render 무료 인스턴스의 `/tmp` SQLite는 재시작 시 초기화될 수 있으므로 공고·프로필·관심 공고 저장은 출품용 시연 범위입니다.
- GitHub 예약 워크플로는 이 브랜치가 기본 브랜치에 병합된 후 실행됩니다.
- 웹앱의 `ANNOUNCEMENT_API_BASE_URL`에 배포된 FastAPI 주소를 설정하면 실공고 모드가 활성화됩니다.

## 주의사항

현재 데이터는 공모전 시연을 위한 샘플입니다. 추천 결과는 정보 탐색을 위한 참고용이며 실제 신청 자격을 확정하지 않습니다. 신청 전 반드시 해당 기관의 최신 공고 원문을 확인해야 합니다.

자세한 구현 범위는 `docs/project-overview.md`, k-apt-alert 통합 설계는 `docs/integration-architecture.md`, 단계별 작업은 `docs/development-backlog.md`, 검증 결과는 `docs/verification-report.md`에서 확인할 수 있습니다.

# Announcement API

청년주거나침반의 공고 수집·정규화 경계를 담당할 독립 FastAPI 서비스입니다.

현재 단계에서는 세 가지 소스를 지원합니다.

- `sample`: 루트의 `data/housing_programs.json`을 읽는 기본 모드
- `direct`: 청약홈 5종·LH 공개 API와 SH·GH HTML을 기관 원본에서 직접 수집하는 모드
- `k_apt_alert`: `K_APT_ALERT_API_BASE_URL`로 지정한 k-apt-alert 호환 API를 호출해 공통 모델로 정규화하는 모드

Next.js 화면과 API 프록시로 연결되어 있습니다. 외부 API 환경변수를 설정하지 않으면 네트워크 요청 없이 샘플 모드로 동작합니다.

## 실행

Python 3.12 가상환경 사용을 권장합니다.

```bash
cd services/announcement-api
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/uvicorn app.main:app --reload --port 8001
```

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `ANNOUNCEMENT_SOURCE` | `sample` | `sample`, `direct`, `k_apt_alert` |
| `K_APT_ALERT_API_BASE_URL` | 없음 | k-apt-alert 호환 API 기본 URL |
| `DATA_GO_KR_API_KEY` | 없음 | 청약홈 5종·LH 직접 수집용 공공데이터 키 |
| `DIRECT_CACHE_TTL_SECONDS` | `900` | 직접 수집 메모리 캐시 시간 |
| `SAMPLE_DATA_PATH` | 루트 샘플 JSON | 샘플 데이터 경로 재정의 |
| `SOURCE_TIMEOUT_SECONDS` | `180` | 외부 API 요청 제한 시간 |
| `ANNOUNCEMENT_DATABASE_PATH` | `.local/compass.db` | 프로필·관심 공고 SQLite 경로 |

공공데이터 키 같은 로컬 설정은 Git에 포함되지 않는 `services/announcement-api/.env.local`에 저장합니다. `.env.example`을 복사하면 서비스 시작 시 자동으로 읽습니다.

`ANNOUNCEMENT_SOURCE=k_apt_alert`인데 API 주소가 없으면 서비스 시작 시 오류가 발생합니다. 조용히 샘플로 대체하지 않아 데이터 출처가 섞이지 않게 합니다.

`ANNOUNCEMENT_SOURCE=direct`에서 공공데이터 키가 없으면 SH·GH만 수집합니다. 기관별 수집 실패는 다른 채널을 막지 않으며 마지막 성공 캐시를 유지합니다.

## API

- `GET /health`: 소스와 서비스 상태
- `GET /v1/announcements`: 공고 목록
  - `region`: 지역 필터
  - `status`: `open`, `planned`, `closed`, `unknown`
  - `category`: 카테고리 필터
  - `months_back`: 직접 수집 또는 호환 API 조회 기간
- `POST /v1/eligibility/score`: 청약 가점·1순위·특별공급 사전 점검
- `POST /v1/announcements/match`: 공고와 프로필 적합도
- `GET /v1/notices/{id}/raw`: 공고 원문과 섹션 추출 결과
- `GET /v1/announcements/{id}/competition`: 경쟁률과 출처
- `GET /v1/announcements/{id}/calendar.ics`: 일정 파일
- `GET /v1/changes`: 신규·수정·삭제 변동 이력
- `GET/PUT/DELETE /v1/users/{user_id}/profile`: 로컬 MVP 프로필
- `GET/PUT/DELETE /v1/users/{user_id}/favorites`: 관심 공고

확장 엔드포인트는 직접 수집 모드 또는 `K_APT_ALERT_API_BASE_URL`이 설정된 경우 활성화됩니다. 결과에 포함된 실제값과 통계 추정값, 일정 미확인 상태를 클라이언트에서 구분해야 합니다.

사용자 API는 현재 인증이 없는 로컬 MVP 구조입니다. 외부 배포 전에는 인증된 사용자 ID만 서버에서 주입하도록 변경해야 합니다.

## Render 배포

루트 `render.yaml`의 Blueprint로 배포할 수 있습니다. 무료 인스턴스에서는 SQLite 경로를 `/tmp/compass.db`로 사용하므로 서버 재시작 후 프로필과 관심 공고가 초기화될 수 있습니다. 공모전 시연 이후에는 영속 데이터베이스로 교체해야 합니다.

## 테스트

```bash
cd services/announcement-api
python -m unittest discover -s tests -v
```

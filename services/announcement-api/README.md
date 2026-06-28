# Announcement API

청년주거나침반의 공고 수집·정규화 경계를 담당할 독립 FastAPI 서비스입니다.

현재 단계에서는 세 가지 소스를 지원합니다.

- `sample`: 루트의 `data/housing_programs.json`을 읽는 기본 모드
- `direct`: LH 공개 API, SH 게시판, GH 청약센터와 청약홈 APT 국민주택에서 공공주택을 직접 수집하는 모드
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
| `DATA_GO_KR_API_KEY` | 없음 | LH·청약홈 직접 수집용 공공데이터 키 |
| `DIRECT_CACHE_TTL_SECONDS` | `900` | 직접 수집 메모리 캐시 시간 |
| `DIRECT_SYNC_INTERVAL_SECONDS` | `86400` | 일반 조회가 자동 증분 동기화를 다시 허용하는 최소 간격 |
| `INCLUDE_PRIVATE_HOUSING` | `false` | `false`는 청약홈 국민주택만, `true`는 민간 채널까지 수집·노출 |
| `ANNOUNCEMENT_SYNC_TOKEN` | 없음 | 예약 동기화 엔드포인트 보호용 선택 토큰 |
| `SAMPLE_DATA_PATH` | 루트 샘플 JSON | 샘플 데이터 경로 재정의 |
| `SOURCE_TIMEOUT_SECONDS` | `180` | 외부 API 요청 제한 시간 |
| `ANNOUNCEMENT_DATABASE_PATH` | `.local/compass.db` | 프로필·관심 공고 SQLite 경로 |

공공데이터 키 같은 로컬 설정은 Git에 포함되지 않는 `services/announcement-api/.env.local`에 저장합니다. `.env.example`을 복사하면 서비스 시작 시 자동으로 읽습니다.

`ANNOUNCEMENT_SOURCE=k_apt_alert`인데 API 주소가 없으면 서비스 시작 시 오류가 발생합니다. 조용히 샘플로 대체하지 않아 데이터 출처가 섞이지 않게 합니다.

`ANNOUNCEMENT_SOURCE=direct`에서 공공데이터 키가 없으면 SH와 GH 청약센터만 수집합니다. GH 청약센터 두 채널이 모두 실패할 때만 기존 GH 본사 게시판을 대체 수집원으로 사용합니다. 기관별 수집 실패는 다른 채널을 막지 않으며 마지막 성공 캐시를 유지합니다.

기본 서비스 범위는 LH·SH·GH 공공주택과 청약홈 APT 국민주택입니다. `INCLUDE_PRIVATE_HOUSING=false`에서는 청약홈 응답의 `HOUSE_SECD=01` 또는 `HOUSE_SECD_NM=국민`인 공고만 수집·노출하며, 민영주택과 나머지 청약홈 채널은 SQLite에 과거 데이터가 남아 있어도 목록·변동·원문 조회에서 제외합니다.

## API

- `GET /health`: 소스와 서비스 상태
- `GET /v1/announcements`: 공고 목록
  - `region`: 지역 필터
  - `status`: `open`, `planned`, `closed`, `unknown`
  - `category`: 카테고리 필터
  - `months_back`: 직접 수집 또는 호환 API 조회 기간
  - `days_back`: 직접 수집 증분 조회 일수
  - `force_refresh`: 저장소를 무시하고 즉시 동기화
- `POST /v1/announcements/sync`: 예약 증분 동기화
  - 기본 최근 7일 중복 조회
  - `{ "full": true }`는 최근 90일 재대조
  - `ANNOUNCEMENT_SYNC_TOKEN`을 설정하면 `X-Sync-Token` 헤더가 필요
- `POST /v1/eligibility/score`: 청약 가점·1순위·특별공급 사전 점검
- `POST /v1/announcements/match`: 공고와 프로필 적합도
- `GET /v1/notices/{id}/raw`: 향후 확장용 원문·섹션 추출 시범 API(현재 카드 비노출)
- `GET /v1/announcements/{id}/competition`: 향후 확장용 경쟁률 시범 API(현재 카드 비노출)
- `GET /v1/announcements/{id}/calendar.ics`: 일정 파일
- `GET /v1/changes`: 신규·수정·삭제 변동 이력
- `GET/PUT/DELETE /v1/users/{user_id}/profile`: 로컬 MVP 프로필
- `GET/PUT/DELETE /v1/users/{user_id}/favorites`: 관심 공고

확장 엔드포인트는 직접 수집 모드 또는 `K_APT_ALERT_API_BASE_URL`이 설정된 경우 활성화됩니다. 결과에 포함된 실제값과 통계 추정값, 일정 미확인 상태를 클라이언트에서 구분해야 합니다.

사용자 API는 현재 인증이 없는 로컬 MVP 구조입니다. 외부 배포 전에는 인증된 사용자 ID만 서버에서 주입하도록 변경해야 합니다.

## Render 배포

루트 `render.yaml`의 Blueprint로 배포할 수 있습니다. `.github/workflows/daily-announcement-sync.yml`은 매일 오전 7시(KST)에 최근 7일을 중복 조회하고, 일요일에는 최근 90일을 재대조합니다. 공고는 `source_id` 기준으로 SQLite에 upsert하며 최초 발견·마지막 확인·변경 시각과 내용 해시를 저장합니다. 검증된 결과는 `data/live_housing_programs.json`에도 병합 저장해 Render 장애 시 웹앱의 실공고 폴백으로 사용합니다.

로컬 PC에 새 공고의 원문 PDF만 보관하려면 스냅샷 갱신 후 아래 스크립트를 실행합니다. 기본 저장 위치는 `C:\Users\nahah\Documents\Housing-Journey-P\공고문`이며, `.notice_pdf_archive_state.json`에 기록된 기존 `source_id`는 다시 받지 않습니다.

```powershell
python services/announcement-api/scripts/archive_notice_pdfs.py
```

블로그 콘텐츠화를 위한 주거 정책 보도자료는 대한민국 정책브리핑의 부처별 RSS를 수집해 Notion `정책 DB`에 저장합니다. 대상 RSS는 국무조정실, 국토교통부, 기획예산처이며 주거·주택·임대·청약·전월세·부동산시장 관련 항목만 남깁니다. `.github/workflows/daily-policy-rss-sync.yml`은 매일 오전 1시(KST)에 최근 1일치를 수집하고, 수동 실행 시 `days_back`으로 조회 기간을 조정할 수 있습니다.

```powershell
python services/announcement-api/scripts/sync_policy_rss.py --days-back 10
```

무료 인스턴스에서는 SQLite 경로가 `/tmp/compass.db`이므로 서버 재시작·재배포 시 공고, 프로필, 관심 공고가 초기화될 수 있습니다. 정적 실공고 스냅샷은 Git에 남으므로 추천 화면은 마지막 성공 데이터를 계속 표시합니다. 예약 워크플로는 기본 브랜치에 병합된 후 실행됩니다. `DATA_GO_KR_API_KEY`를 GitHub Actions secret으로 추가하면 Render를 거치지 않고 직접 수집하며, 키가 없을 때는 Render API 내보내기를 대체 경로로 사용합니다. 공모전 이후 실제 영속성을 보장하려면 외부 영속 데이터베이스 또는 Render 영구 디스크로 교체해야 합니다.

## 테스트

```bash
cd services/announcement-api
python -m unittest discover -s tests -v
```

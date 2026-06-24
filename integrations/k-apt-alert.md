# k-apt-alert Integration

## 위치와 역할

k-apt-alert는 Data Agent가 아니라 추후 연결할 공고 데이터 수집 파이프라인이다. 상담 판단이나 추천을 수행하지 않고 기관별 공고를 수집·정규화해 announcement database에 전달한다.

## 수집 범위

- 공고 제목
- 공고 원문 또는 원문에서 추출한 텍스트
- 공식 원문 URL
- 모집기간
- 공급기관
- 수집 시각과 원본 식별자

수집기는 자격 충족 여부, 가점, 추천 순위 또는 당첨 가능성을 판단하지 않는다.

## 소비 주체

수집된 데이터는 Announcement Agent가 해석한다. Announcement Agent가 공고 유형, 공급 유형, 자격 기준과 선정 방식을 구조화한 뒤 Eligibility Agent와 Recommendation Agent가 사용한다.

## 연결 흐름

```text
k-apt-alert
↓
announcement database
↓
Announcement Agent
↓
Eligibility Agent
↓
Recommendation Agent
```

모든 사용자 응답은 별도로 Verification Agent 검증을 거친다.

## 실패 처리

- 수집 실패는 자격 없음으로 해석하지 않는다.
- 원문이 없으면 Announcement Agent에 분석 품질 `low`로 전달한다.
- 일정이 없으면 접수중 상태를 추정하지 않는다.
- 동일 공고의 여러 버전은 원본 식별자와 수집 시각으로 추적한다.

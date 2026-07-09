# DMICU

전남·광주 통합특별시 응급의료기관 기능 재편과 완결응급의료 Trinity 전략 공람용 정적 페이지입니다.

GitHub Pages가 활성화되면 아래 주소에서 열람할 수 있습니다.

https://dallgoo119-commits.github.io/DMICU/

## Files

- `index.html`: 전략 보고서 본문
- `gwangju_emergency_map.html`: 보고서에 포함된 광주·전남 응급의료기관 실시간 병상 지도
- `visitor-stats.json`: 공람 페이지 접속 통계 표시용 JSON 자리
- `ems_anonymous_feedback_template.md`: 광주·전남 구급대원 무기명 현장 제보 설문 문항 템플릿
- `.github/workflows/update-beds.yml`: 외부 cron 또는 수동 실행으로 병상 현황을 다시 수집해 지도 HTML을 자동 커밋
- `scripts/update_emergency_map.py`: 내 손안의 응급실 API를 호출해 병상 현황과 추이 데이터를 갱신

## Emergency Bed Map Auto Update

가장 안정적인 운영 방식은 GitHub 자체 `schedule`에만 의존하지 않고, 외부 cron 서비스가 GitHub Actions를 직접 깨우는 방식입니다. GitHub 예약 실행은 저장소 부하와 GitHub 큐 상태에 따라 지연되거나 드롭될 수 있으므로, 이 저장소의 `schedule`은 6시간마다 도는 보조 안전망으로만 둡니다.

### 1. GitHub 토큰 만들기

GitHub에서 fine-grained personal access token을 하나 만들고 다음처럼 제한합니다.

- Repository access: `dallgoo119-commits/DMICU`만 선택
- Permissions: `Contents` read/write, `Metadata` read-only
- Expiration: 가능하면 90일 이상 또는 운영 정책에 맞게 설정

토큰은 외부 cron 서비스의 Authorization 헤더에만 넣고 저장소 파일에는 절대 커밋하지 않습니다.

### 2. cron-job.org 예시

cron-job.org에서 새 작업을 만들고 다음 값으로 설정합니다.

- URL: `https://api.github.com/repos/dallgoo119-commits/DMICU/dispatches`
- Method: `POST`
- Schedule: every 30 minutes
- Timezone: `Asia/Seoul`
- Header `Accept`: `application/vnd.github+json`
- Header `Authorization`: `Bearer YOUR_GITHUB_TOKEN`
- Header `X-GitHub-Api-Version`: `2022-11-28`
- Body:

```json
{"event_type":"update-beds"}
```

정상 호출이면 GitHub API가 `204 No Content`를 반환하고, Actions 탭에 `Update emergency bed map` 실행이 새로 생깁니다.

### 3. 수동 실행

외부 cron 없이도 GitHub Actions 탭에서 `Update emergency bed map` workflow를 선택해 `Run workflow`로 즉시 갱신할 수 있습니다.

## Public Comments

댓글은 GitHub Issues 기반의 utterances를 사용합니다.

1. https://github.com/apps/utterances 에서 앱을 설치합니다.
2. 설치 대상 저장소로 `dallgoo119-commits/DMICU`를 선택합니다.
3. 방문자는 GitHub 계정으로 공개 댓글을 남길 수 있습니다.

## Visitor Stats

GitHub Pages는 정적 호스팅이므로 자체적으로 실시간 접속자 수를 저장할 수 없습니다. `index.html`은 기본적으로 `visitor-stats.json`을 읽어 다음 형식의 값을 표시합니다.

```json
{
  "active": 3,
  "total": 1024,
  "today": 88,
  "updated_at": "2026-06-28T09:00:00+09:00"
}
```

실시간 집계가 필요하면 Cloudflare Worker, Firebase, GoatCounter 등 별도 통계 엔드포인트를 만들고 `window.DMICU_VISITOR_STATS_ENDPOINT`로 연결하면 됩니다.

## Anonymous EMS Feedback

구급대원 현장 불만은 공개 댓글과 분리해 무기명 설문으로 받는 것을 권장합니다.

- 이메일 수집, 로그인 요구, IP 수집 옵션을 끕니다.
- 이름, 연락처, 소속 센터명, 차량번호, 정확한 출동 주소를 묻지 않습니다.
- 구 단위 또는 권역 단위, 시간대, 질환군, 미수용 사유, 지연 시간, 개선 제안을 중심으로 묻습니다.
- 원자료는 비공개로 보관하고, 공개 보고서에는 익명화·집계된 내용만 반영합니다.

`ems_anonymous_feedback_template.md`의 문항을 Google Forms, Tally, Typeform 등에 옮긴 뒤, 생성된 설문 URL을 `window.DMICU_EMS_FEEDBACK_FORM_URL`에 연결하면 공람 페이지의 버튼이 활성화됩니다.

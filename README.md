# DMICU

전남·광주 통합특별시 응급의료기관 기능 재편과 완결응급의료 Trinity 전략 공람용 정적 페이지입니다.

GitHub Pages가 활성화되면 아래 주소에서 열람할 수 있습니다.

https://dallgoo119-commits.github.io/DMICU/

## Files

- `index.html`: 전략 보고서 본문
- `gwangju_emergency_map.html`: 보고서에 포함된 광주·전남 응급의료기관 실시간 병상 지도
- `visitor-stats.json`: 공람 페이지 접속 통계 표시용 JSON 자리
- `ems_anonymous_feedback_template.md`: 광주·전남 구급대원 무기명 현장 제보 설문 문항 템플릿
- `.github/workflows/update-beds.yml`: 2시간마다 병상 현황을 다시 수집해 지도 HTML을 자동 커밋
- `scripts/update_emergency_map.py`: 내 손안의 응급실 API를 호출해 병상 현황과 추이 데이터를 갱신

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

# DMICU

광주응급실·전남응급실 실시간 병상 현황 지도와 전남·광주 통합특별시 완결응급의료 Trinity 전략 공람용 정적 페이지입니다.

GitHub Pages가 활성화되면 아래 주소에서 열람할 수 있습니다.

[광주응급실·전남응급실 병상 현황 지도](https://dallgoo119-commits.github.io/DMICU/)

## Files

- `index.html`: 병상 현황 중심 첫 화면 (기존 `#part-1`, `#part-2` 링크 보존)
- `policy.html`: 전략 보고서와 공개 의견 (목표·가정·검증 대기 수치 구분)
- `methodology.html`: 데이터 시각, 결측값, 포화도 산식과 해석 한계
- `assets/`: 화면 스타일과 기관별 추이 지연 로딩
- `data/trends/local/*.json`, `data/trends/national/*.json`: 기관별 과거 관측 이력. 선택한 기관 파일만 브라우저에서 요청
- `gwangju_emergency_map.html`: 약 30분 주기로 수집한 광주·전남 응급의료기관 병상 현황 참고 지도
- `visitor-stats.json`: 공람 페이지 접속 통계 표시용 JSON 자리
- `ems_anonymous_feedback_template.md`: 광주·전남 구급대원 무기명 현장 제보 설문 문항 템플릿
- `.github/workflows/update-beds.yml`: 외부 cron 또는 수동 실행으로 병상 현황을 다시 수집해 지도 HTML을 자동 커밋
- `scripts/update_emergency_map.py`: 내 손안의 응급실 API를 호출해 병상 현황과 추이 데이터를 갱신
- `data/national_snapshots/YYYY-MM-DD.jsonl`: 완전 수집에 성공한 전국 기관의 30분 단위 연구용 원시 스냅샷
- `data/national_daily/YYYY-MM-DD.json`: 같은 날짜의 기관별 평균·최저·최고·표본 수를 정리한 연구용 일집계

전국 연구용 파일은 화면에서 직접 노출하지 않지만 공개 저장소에 함께 보존됩니다. 부분 지역 수집은 저장하지 않고, 완전 수집된 기관 단위 공개 API 값만 기록합니다. 현재 약 414~415개 유효 기관의 실제 생성 파일 기준 예상 용량은 30분 스냅샷 약 180MB/년, 일집계 약 70MB/년으로 합계 약 250MB/년입니다.

## Emergency Bed Map Auto Update

가장 안정적인 운영 방식은 GitHub 자체 `schedule`에만 의존하지 않고, 외부 cron 서비스가 GitHub Actions를 직접 깨우는 방식입니다. 현재 저장소의 `schedule`과 외부 cron 목표 주기는 모두 30분이지만, GitHub 예약 실행은 저장소 부하와 GitHub 큐 상태에 따라 지연되거나 드롭될 수 있습니다.

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

정책 페이지는 기존 Supabase 공개 의견과 GitHub Issues 기반 utterances를 유지합니다. 댓글 HTML은 텍스트로 표시합니다. 브라우저의 개인정보 패턴 안내는 보조 장치이며 서버 권한·도배 방지·신고 처리를 대체하지 않습니다. 로컬 미리보기에서는 댓글 전송과 방문 기록을 수행하지 않습니다.

1. https://github.com/apps/utterances 에서 앱을 설치합니다.
2. 설치 대상 저장소로 `dallgoo119-commits/DMICU`를 선택합니다.
3. 방문자는 GitHub 계정으로 공개 댓글을 남길 수 있습니다.

## Visitor Stats

GitHub Pages는 정적 호스팅이므로 방문 통계는 `policy.html`의 Supabase RPC 응답으로 표시합니다. 고정 가산값은 사용하지 않으며, 응답의 누락·음수·비정수 값은 오류로 처리합니다. `visitor-stats.json`은 기존 참고 파일로 남아 있습니다.

```json
{
  "active": 3,
  "total": 1024,
  "today": 88,
  "updated_at": "2026-06-28T09:00:00+09:00"
}
```

실패 시 방문자 수를 임의의 0으로 바꾸지 않고 오류 상태를 표시합니다. 운영 DB 권한과 RPC 구성은 `supabase_visitor_stats.sql`을 참고하세요.

## Anonymous EMS Feedback

구급대원 현장 불만은 공개 댓글과 분리해 무기명 설문으로 받는 것을 권장합니다.

- 이메일 수집, 로그인 요구, IP 수집 옵션을 끕니다.
- 이름, 연락처, 소속 센터명, 차량번호, 정확한 출동 주소를 묻지 않습니다.
- 구 단위 또는 권역 단위, 시간대, 질환군, 미수용 사유, 지연 시간, 개선 제안을 중심으로 묻습니다.
- 원자료는 비공개로 보관하고, 공개 보고서에는 익명화·집계된 내용만 반영합니다.

`ems_anonymous_feedback_template.md`는 별도 무기명 설문을 설계할 때 참고할 수 있습니다.

## Validation and local preview

```sh
python -m unittest discover -s tests -p "test_*.py"
node --test tests/*.test.mjs
python -m http.server 8765 --bind 127.0.0.1
```

`http://127.0.0.1:8765/`에서 미리 볼 수 있습니다. 수집기를 실행하면 실제 공개 API 관측을 새로 기록하므로 화면 수정만 확인할 때는 실행할 필요가 없습니다.

이력 분리 이전 HTML을 가져올 때만 `python scripts/migrate_dashboard_history.py`를 실행합니다. 수집 시각과 관측값을 변경하지 않고 JSON 이력을 기관별로 분리하며, 이후 수집기는 이 파일들을 읽고 갱신합니다. 배포 시 `data/trends/`와 `assets/`를 함께 포함해야 합니다.

병상 값은 유한 정수만 허용하고, 분모 0·음수 전체·전체보다 많은 가용 병상은 계산에서 제외합니다. 음수 가용 병상은 100% 초과 보고로 유지합니다. 지역 중복 값 충돌은 수집을 중단하고, 전국 충돌은 이전 완전본을 유지합니다. 기존 관측 이력은 재작성하거나 추정값으로 보정하지 않습니다.

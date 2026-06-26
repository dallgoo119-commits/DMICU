# DMICU

전남·광주 통합특별시 응급의료기관 기능 재편과 완결응급의료 Trinity 전략 공람용 정적 페이지입니다.

GitHub Pages가 활성화되면 아래 주소에서 열람할 수 있습니다.

https://dallgoo119-commits.github.io/DMICU/

## Files

- `index.html`: 전략 보고서 본문
- `gwangju_emergency_map.html`: 보고서에 포함된 광주·전남 응급의료기관 실시간 병상 지도
- `.github/workflows/update-beds.yml`: 2시간마다 병상 현황을 다시 수집해 지도 HTML을 자동 커밋
- `scripts/update_emergency_map.py`: 내 손안의 응급실 API를 호출해 병상 현황과 추이 데이터를 갱신

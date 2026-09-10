const trendRequests = new Map();
const loadedTrends = new Set();
let trendRequestVersion = 0;
function historyReady(scope, code) { return loadedTrends.has(`${scope}/${code}`); }
async function loadTrend(scope, code) {
  const version = ++trendRequestVersion;
  const key = `${scope}/${code}`;
  const note = document.getElementById('missingNote');
  note.textContent = '이 기관의 저장된 추이를 불러오는 중입니다.';
  for (const id of ['currentGeneralBeds','currentChildBeds','riskSignal','avgGeneral','avgChild','latestDate']) document.getElementById(id).textContent = '—';
  if (trendChart) { trendChart.destroy(); trendChart = null; }
  try {
    if (!loadedTrends.has(key)) {
      if (!trendRequests.has(key)) {
        const captured = scope === 'local' ? LOCALMETA[0]?.captured : NATMETA[0]?.captured;
        const url = `data/trends/${scope}/${encodeURIComponent(encodeURIComponent(code))}.json?v=${encodeURIComponent(captured || '')}`;
        trendRequests.set(key, fetch(url, {signal: AbortSignal.timeout(15000)})
          .then(response => { if (!response.ok) throw new Error('History unavailable'); return response.json(); })
          .then(records => {
            if (!Array.isArray(records) || records.some(r => r.code !== code || !isIsoDate(r.date))) throw new Error('Invalid history');
            const target = scope === 'local' ? HISTORY : NATIONAL_HISTORY;
            target.push(...records);
            loadedTrends.add(key);
          }).finally(() => trendRequests.delete(key)));
      }
      await trendRequests.get(key);
    }
    if (version !== trendRequestVersion || activeCode !== code || activeTrendScope !== scope) return;
    scope === 'local' ? drawTrend() : drawNationalTrend();
  } catch (error) {
    if (version !== trendRequestVersion) return;
    note.replaceChildren(document.createTextNode('추이를 가져오지 못했습니다. 병상 목록의 최근 수집 값은 계속 확인할 수 있습니다. '));
    const retry = document.createElement('button');
    retry.type = 'button'; retry.textContent = '다시 불러오기';
    retry.addEventListener('click', () => loadTrend(scope, code));
    note.append(retry);
  }
}

function timeLabel(iso) {
  const time = new Date(iso);
  if (!Number.isFinite(time.getTime())) return '시각 미확인';
  return new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(time) + ' KST';
}
function renderFreshness() {
  const local = LOCALMETA[0] || {}, national = NATMETA[0] || {};
  const stale = isStale(local.captured);
  const element = document.getElementById('freshness');
  element.classList.toggle('is-stale', stale);
  const age = relTime(local.captured);
  const future = Date.parse(local.captured) > Date.now() + 300000;
  element.innerHTML = `<div><strong>${future ? '수집 시각 확인 필요' : stale ? '갱신 지연 · 이전 자료' : '최근 수집 자료'}</strong><span>${esc(timeLabel(local.captured))}${age&&!future?' · '+esc(age):''}</span></div><p>수집 주기 목표 30분 · 원천 갱신 시각 미제공${stale ? ' · 현재 상태를 원천 기관에 확인해 주세요.' : ''}</p><p class="coverage">일반 집계 ${local.general_included??'—'}/${DATA.length}개 기관 · 소아 집계 ${local.child_included??'—'}/${DATA.length}개 기관 · <a href="methodology.html" target="_top">계산·제외 기준</a></p>`;
  const nationalNotice = document.getElementById('nationalFreshness');
  nationalNotice.textContent = `${isStale(national.captured) ? '갱신 지연 · ' : ''}전국 수집 ${timeLabel(national.captured)}${national.snapshot_status==='stale_partial_failure'?' · 일부 지역 실패 또는 값 충돌로 이전 완전본 유지':''}`;
  nationalNotice.classList.toggle('is-stale', isStale(national.captured)||national.snapshot_status==='stale_partial_failure');
}

const nationalNotice = document.createElement('p');
nationalNotice.id = 'nationalFreshness'; nationalNotice.className = 'national-freshness';
document.querySelector('.nat-head').append(nationalNotice);
document.getElementById('hospitalSearch').addEventListener('input', event => {
  searchQuery = event.target.value.trim().toLocaleLowerCase(); pageIndex = 0; renderTable(activeRegion);
});
for (const [id, delta] of [['previousPage', -1], ['nextPage', 1]]) {
  document.getElementById(id).addEventListener('click', () => {
    pageIndex += delta; renderTable(activeRegion);
    document.getElementById('institutionSection').scrollIntoView({block:'start'});
  });
}
// The nearby map is optional and never requests location on page load.
document.getElementById('nearbyDisclosure').addEventListener('toggle', event => {
  if (!event.target.open) return;
  if (!fieldMap) initFieldMap();
  requestAnimationFrame(() => fieldMap?.invalidateSize());
});
// Keep focus within the open dialog, then return to the invoking control.
let trendInvoker = null;
const originalShowTrendPanel = showTrendPanel;
showTrendPanel = function() {
  trendInvoker = document.activeElement;
  originalShowTrendPanel();
  document.getElementById('closeTrend').focus({preventScroll:true});
};
const originalCloseTrendPanel = closeTrendPanel;
closeTrendPanel = function() { ++trendRequestVersion; originalCloseTrendPanel(); trendInvoker?.focus?.({preventScroll:true}); };
// Replace listeners previously bound to the original function reference.
document.getElementById('closeTrend').removeEventListener('click', originalCloseTrendPanel);
document.getElementById('trendBackdrop').removeEventListener('click', originalCloseTrendPanel);
document.getElementById('closeTrend').addEventListener('click', closeTrendPanel);
document.getElementById('trendBackdrop').addEventListener('click', closeTrendPanel);
document.getElementById('trendPanel').addEventListener('keydown', event => {
  if (event.key !== 'Tab') return;
  const controls = [...event.currentTarget.querySelectorAll('button:not(:disabled),a[href],input,select')].filter(el => el.getClientRects().length);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
renderTable(); renderNational(); renderFreshness(); initMap(); setupMapDisclosure(); syncMapRegion(activeRegion);
setInterval(renderFreshness, 60000);
if (window.self !== window.top) {
  document.body.classList.add('embedded');
  let lastHeight = 0;
  const sendHeight = () => {
    const height = Math.ceil(document.body.getBoundingClientRect().height) + 8;
    if (height !== lastHeight) { lastHeight = height; parent.postMessage({type:'dmicu-height',height}, location.origin); }
  };
  new ResizeObserver(sendHeight).observe(document.body);
  sendHeight();
}

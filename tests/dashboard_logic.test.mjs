import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";


const html = fs.readFileSync(
  new URL("../gwangju_emergency_map.html", import.meta.url),
  "utf8",
);

const inlineScripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)]
  .map((match) => match[1])
  .filter((source) => source.trim());

test("dashboard prominently limits operational use of delayed bed data", () => {
  assert.match(html, /참고용 안내/);
  assert.match(html, /약 30분 주기로 갱신/);
  assert.match(html, /실제 수용 가능 여부를 반드시 확인/);
  assert.match(html, /https:\/\/mediboard\.nemc\.or\.kr\//);
  assert.doesNotMatch(html, /수용유연성/);
  assert.doesNotMatch(html, /실시간 포화/);
});

test("every inline dashboard script parses", () => {
  assert.ok(inlineScripts.length > 0);
  for (const source of inlineScripts) {
    assert.doesNotThrow(() => new vm.Script(source));
  }
});

const helperNames = new Set([
  "validBed",
  "inactiveBed",
  "invalidBed",
  "validSat",
  "bedText",
  "satText",
  "overallSat",
  "hasInvalidBedReport",
  "statusAvailabilityText",
  "satLevel",
  "statusPill",
  "isIsoDate",
  "addIsoDays",
  "isoRange",
  "dateLabel",
  "todayIso",
  "dateRange",
  "completedDateRange",
  "dailyValue",
  "dailyMin",
  "dailyMax",
  "dailyCount",
  "isDailyAggregate",
  "validDailyRecord",
  "analysisValue",
  "completedKstValue",
  "risk",
  "nationalDailyValue",
  "nationalDailyMin",
  "nationalDailyMax",
  "nationalDailyCount",
  "nationalIsDailyAggregate",
  "nationalValidDailyRecord",
  "nationalAnalysisValue",
  "nationalCompletedKstValue",
  "nearbyCountText",
]);

const dashboardScript = inlineScripts.at(-1);
const helperSource = dashboardScript
  .split(/\r?\n/)
  .filter((line) => {
    const match = line.match(/^function\s+([A-Za-z0-9_]+)\s*\(/);
    return match && helperNames.has(match[1]);
  })
  .join("\n");

const context = vm.createContext({ Intl, Date, Number, Math, Set });
vm.runInContext(helperSource, context);
vm.runInContext("todayIso = () => '2026-07-30';", context);

const currentData = JSON.parse(
  html.match(/const DATA=(\[[\s\S]*?\]);/)[1],
);
const currentNational = JSON.parse(
  html.match(/const NATIONAL=(\[[\s\S]*?\]);/)[1],
);

test("7, 30 and 90 day periods are trailing ranges without future dates", () => {
  assert.deepEqual(
    Array.from(vm.runInContext("dateRange(7)", context)),
    [
      "2026-07-24",
      "2026-07-25",
      "2026-07-26",
      "2026-07-27",
      "2026-07-28",
      "2026-07-29",
      "2026-07-30",
    ],
  );
  const thirty = Array.from(vm.runInContext("dateRange(30)", context));
  assert.equal(thirty.length, 30);
  assert.equal(thirty[0], "2026-07-01");
  assert.equal(thirty.at(-1), "2026-07-30");
  const ninety = Array.from(vm.runInContext("dateRange(90)", context));
  assert.equal(ninety.length, 90);
  assert.equal(ninety.at(-1), "2026-07-30");
});

test("completed 30 day risk window excludes the in-progress current day", () => {
  const completed = Array.from(vm.runInContext("completedDateRange(30)", context));
  assert.equal(completed.length, 30);
  assert.equal(completed[0], "2026-06-30");
  assert.equal(completed.at(-1), "2026-07-29");
});

test("all range uses observed dates and ignores future observations", () => {
  assert.deepEqual(
    Array.from(
      vm.runInContext(
        "dateRange('all', ['2026-06-25', '2026-06-27', '2026-08-01'])",
        context,
      ),
    ),
    ["2026-06-25", "2026-06-26", "2026-06-27"],
  );
});

test("analysis excludes one-off snapshots and holds risk until 30 KST days", () => {
  assert.equal(
    vm.runInContext(
      "analysisValue({general_saturation: 80, general_sample_count: 1}, 'general')",
      context,
    ),
    null,
  );
  assert.equal(
    vm.runInContext(
      "analysisValue({general_saturation_avg: 75, general_sample_count: 2}, 'general')",
      context,
    ),
    75,
  );
  assert.equal(
    vm.runInContext("risk(85, 29)", context),
    "산정 보류 (KST 29/30일)",
  );
  assert.equal(
    vm.runInContext("risk(85, 30)", context),
    "탐색 신호: 상시 포화 위험",
  );
});

test("period statistics use only completed KST days", () => {
  assert.equal(
    vm.runInContext(
      "completedKstValue({date_basis: 'UTC', general_saturation_avg: 75, general_sample_count: 2}, 'general', '2026-07-29')",
      context,
    ),
    null,
  );
  assert.equal(
    vm.runInContext(
      "completedKstValue({date_basis: 'Asia/Seoul', general_saturation_avg: 75, general_sample_count: 2}, 'general', '2026-07-30')",
      context,
    ),
    null,
  );
  assert.equal(
    vm.runInContext(
      "completedKstValue({date_basis: 'Asia/Seoul', general_saturation_avg: 75, general_sample_count: 2}, 'general', '2026-07-29')",
      context,
    ),
    75,
  );
});

test("invalid upstream bed values stay visible but are excluded from saturation", () => {
  assert.equal(vm.runInContext("bedText(null, 10)", context), "미수집");
  assert.equal(
    vm.runInContext("bedText(-2, 10)", context),
    "원천 -2/10 · 확인 필요",
  );
  assert.equal(
    vm.runInContext("satText(120, -2, 10)", context),
    "포화도 산정 제외",
  );
  assert.equal(vm.runInContext("validBed(2, 10)", context), true);
  assert.equal(vm.runInContext("validBed(-2, 10)", context), false);
  assert.equal(vm.runInContext("inactiveBed(0, 0)", context), true);
  assert.equal(vm.runInContext("invalidBed(0, 0)", context), false);
  assert.equal(vm.runInContext("bedText(0, 0)", context), "운영 병상 없음");
  assert.equal(vm.runInContext("validSat(100)", context), true);
  assert.equal(vm.runInContext("validSat(100.1)", context), false);
  context.invalidStatusRow = {
    general_available: -2,
    general_total: 10,
    general_saturation: null,
    child_available: 3,
    child_total: 4,
    child_saturation: 25,
  };
  assert.equal(
    vm.runInContext("statusAvailabilityText(invalidStatusRow)", context),
    "원천값 확인",
  );
  assert.match(
    vm.runInContext("statusPill(invalidStatusRow)", context),
    /status-gray[\s\S]*원천값 확인/,
  );
});

test("every current invalid report renders as a quality warning, never a percentage", () => {
  const localInvalid = currentData.filter(
    (row) => row.general_available != null
      && row.general_total != null
      && !(row.general_total > 0
        && row.general_available >= 0
        && row.general_available <= row.general_total),
  );
  assert.ok(localInvalid.length > 0);
  for (const row of localInvalid) {
    context.row = row;
    assert.match(
      vm.runInContext("bedText(row.general_available, row.general_total)", context),
      /확인 필요/,
    );
    assert.equal(
      vm.runInContext(
        "satText(row.general_saturation, row.general_available, row.general_total)",
        context,
      ),
      "포화도 산정 제외",
    );
    const overall = vm.runInContext("overallSat(row)", context);
    assert.ok(overall == null || (overall >= 0 && overall <= 100));
  }

  const nationalInvalid = currentNational.filter(
    (row) => !(row.o > 0 && row.a >= 0 && row.a <= row.o)
      || !(Number.isFinite(row.s) && row.s >= 0 && row.s <= 100),
  );
  assert.ok(nationalInvalid.length > 0);
  for (const row of nationalInvalid) {
    context.row = row;
    assert.equal(
      vm.runInContext("satText(row.s, row.a, row.o)", context),
      "포화도 산정 제외",
    );
  }
});

test("historical outlier days cannot distort statistics or chart axes", () => {
  assert.equal(
    vm.runInContext(
      "analysisValue({general_saturation_avg: 80, general_saturation_min: 20, general_saturation_max: 1766.7, general_sample_count: 20}, 'general')",
      context,
    ),
    null,
  );
  assert.equal(
    vm.runInContext(
      "analysisValue({general_saturation_avg: 80, general_saturation_min: 20, general_saturation_max: 100, general_sample_count: 20, general_invalid_sample_count: 3}, 'general')",
      context,
    ),
    80,
  );
  assert.equal(
    vm.runInContext(
      "nationalAnalysisValue({saturation_avg: 75, saturation_min: 10, saturation_max: 140, sample_count: 20})",
      context,
    ),
    null,
  );
  assert.match(html, /y:\{min:0,max:100/);
  assert.doesNotMatch(html, /suggestedMax:100/);
});

test("nearby result count explains the 18-item display cap", () => {
  assert.equal(
    vm.runInContext("nearbyCountText(33, 50)", context),
    "33곳 중 가까운 18곳 표시 · 반경 50km",
  );
  assert.equal(
    vm.runInContext("nearbyCountText(15, 10)", context),
    "15곳 · 반경 10km",
  );
  assert.equal(vm.runInContext("nearbyCountText(0, 10)", context), "0곳");
});

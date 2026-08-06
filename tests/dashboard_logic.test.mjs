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
  "bedText",
  "satText",
  "isIsoDate",
  "addIsoDays",
  "isoRange",
  "dateLabel",
  "todayIso",
  "dateRange",
  "completedDateRange",
  "dailyValue",
  "dailyCount",
  "isDailyAggregate",
  "analysisValue",
  "completedKstValue",
  "risk",
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

test("missing and negative availability are displayed without overclaiming", () => {
  assert.equal(vm.runInContext("bedText(null, 10)", context), "미수집");
  assert.equal(vm.runInContext("bedText(-2, 10)", context), "0/10 · 초과 2");
  assert.equal(
    vm.runInContext("satText(120)", context),
    "포화 120% · 초과 보고",
  );
});

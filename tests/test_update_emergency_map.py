import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_emergency_map as updater


class TimezoneTests(unittest.TestCase):
    def test_utc_timestamp_is_grouped_by_korean_calendar_date(self):
        self.assertEqual(
            updater.kst_date("2026-07-29T15:05:00+00:00"),
            "2026-07-30",
        )

    def test_kst_midnight_boundary_is_exact(self):
        self.assertEqual(
            updater.kst_date("2026-07-29T14:59:59+00:00"),
            "2026-07-29",
        )
        self.assertEqual(
            updater.kst_date("2026-07-29T15:00:00+00:00"),
            "2026-07-30",
        )

    def test_naive_timestamp_is_treated_as_korea_time(self):
        self.assertEqual(updater.kst_date("2026-07-30T00:05:00"), "2026-07-30")


class BedValueValidationTests(unittest.TestCase):
    def test_percentage_requires_empty_beds_within_total(self):
        self.assertEqual(updater.percent(2, 10), 80.0)
        self.assertIsNone(updater.percent(-1, 10))
        self.assertIsNone(updater.percent(11, 10))
        self.assertIsNone(updater.percent(0, 0))
        self.assertTrue(updater.valid_saturation_value(100))
        self.assertFalse(updater.valid_saturation_value(100.1))

    def test_invalid_values_are_identified_without_losing_raw_numbers(self):
        self.assertTrue(updater.invalid_bed_value(-9, 3))
        self.assertTrue(updater.invalid_bed_value(4, 3))
        self.assertFalse(updater.invalid_bed_value(None, 3))
        self.assertFalse(updater.invalid_bed_value(0, 0))
        self.assertTrue(updater.inactive_bed_value(0, 0))
        self.assertFalse(updater.invalid_bed_value(3, 3))


class HistoryAggregationTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "region": "전남",
            "code": "A2600001",
            "name": "시험병원",
            "type": "지역응급의료센터",
            "grade": "B",
            "general_available": 2,
            "general_total": 10,
            "general_saturation": 80.0,
            "child_available": None,
            "child_total": None,
            "child_saturation": None,
        }

    def test_legacy_value_counts_as_one_snapshot_when_merged(self):
        record = {"general_saturation": 70.0}
        updater.merge_saturation(record, "general", 90.0)
        self.assertEqual(record["general_sample_count"], 2)
        self.assertEqual(record["general_saturation_sum"], 160.0)
        self.assertEqual(record["general_saturation_avg"], 80.0)
        self.assertEqual(record["general_saturation_min"], 70.0)
        self.assertEqual(record["general_saturation_max"], 90.0)

    def test_first_kst_record_does_not_mix_with_legacy_utc_accumulator(self):
        legacy = {
            "date": "2026-07-30",
            "region": "전남",
            "code": self.row["code"],
            "name": self.row["name"],
            "type": self.row["type"],
            "grade": "B",
            "general_saturation": 40.0,
            "general_sample_count": 6,
        }
        result = updater.update_history(
            [legacy],
            [copy.deepcopy(self.row)],
            "2026-07-30T00:10:00+09:00",
        )
        record = next(item for item in result if item["code"] == self.row["code"])
        self.assertEqual(record["schema_version"], updater.HISTORY_SCHEMA_VERSION)
        self.assertEqual(record["date_basis"], "Asia/Seoul")
        self.assertEqual(record["general_sample_count"], 1)
        self.assertEqual(record["general_saturation_avg"], 80.0)

    def test_same_kst_day_uses_unrounded_sum_for_average(self):
        first = updater.update_history(
            [],
            [copy.deepcopy(self.row)],
            "2026-07-30T00:10:00+09:00",
        )
        second_row = copy.deepcopy(self.row)
        second_row["general_saturation"] = 81.0
        second = updater.update_history(
            first,
            [second_row],
            "2026-07-30T00:40:00+09:00",
        )
        record = next(item for item in second if item["code"] == self.row["code"])
        self.assertEqual(record["general_sample_count"], 2)
        self.assertEqual(record["general_saturation_sum"], 161.0)
        self.assertEqual(record["general_saturation_avg"], 80.5)
        self.assertEqual(record["first_sample_at"], "2026-07-30T00:10:00+09:00")
        self.assertEqual(record["last_sample_at"], "2026-07-30T00:40:00+09:00")

    def test_invalid_snapshot_is_excluded_and_counted(self):
        invalid_row = copy.deepcopy(self.row)
        invalid_row["general_available"] = -9
        invalid_row["general_total"] = 3
        invalid_row["general_saturation"] = None
        result = updater.update_history(
            [],
            [invalid_row],
            "2026-07-30T00:10:00+09:00",
        )
        record = next(item for item in result if item["code"] == self.row["code"])
        self.assertEqual(record["general_available"], -9)
        self.assertEqual(record["general_total"], 3)
        self.assertEqual(record["general_invalid_sample_count"], 1)
        self.assertNotIn("general_saturation_avg", record)
        self.assertNotIn("general_sample_count", record)

    def test_invalid_snapshot_does_not_change_existing_valid_average(self):
        first = updater.update_history(
            [],
            [self.row],
            "2026-07-30T00:10:00+09:00",
        )
        invalid_row = copy.deepcopy(self.row)
        invalid_row["general_available"] = -9
        invalid_row["general_total"] = 3
        invalid_row["general_saturation"] = None
        result = updater.update_history(
            first,
            [invalid_row],
            "2026-07-30T00:40:00+09:00",
        )
        record = next(item for item in result if item["code"] == self.row["code"])
        self.assertEqual(record["general_sample_count"], 1)
        self.assertEqual(record["general_saturation_avg"], 80.0)
        self.assertEqual(record["general_saturation_min"], 80.0)
        self.assertEqual(record["general_saturation_max"], 80.0)
        self.assertEqual(record["general_invalid_sample_count"], 1)

    def test_out_of_range_percentage_is_defensively_rejected(self):
        record = {}
        updater.merge_saturation(record, "general", 1766.7)
        self.assertEqual(record["general_invalid_sample_count"], 1)
        self.assertNotIn("general_saturation_avg", record)


class NationalDeduplicationTests(unittest.TestCase):
    def test_same_institution_from_two_region_responses_is_counted_once(self):
        item = {
            "emogCode": "A1500001",
            "emergencyRoomName": "중복시험병원",
            "emergencyInstitutionType": "지역응급의료센터",
            "generalEmergencyAvailable": 1,
            "generalEmergencyTotal": 10,
            "latitude": 35.1,
            "longitude": 126.8,
            "address": "광주",
        }
        panel, total, failed, ok_count, history, quality = updater.fetch_national(
            {"11": [copy.deepcopy(item)], "12": [copy.deepcopy(item)]},
            [],
        )
        self.assertEqual(total, 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(len(panel), 1)
        self.assertEqual(failed, [])
        self.assertEqual(ok_count, 2)
        self.assertEqual(quality["raw_item_count"], 2)
        self.assertEqual(quality["duplicate_count"], 1)
        self.assertEqual(quality["conflicting_duplicate_count"], 0)

    def test_invalid_bed_value_is_retained_as_flagged_raw_report(self):
        item = {
            "emogCode": "A2600068",
            "emergencyRoomName": "시험음수병원",
            "emergencyInstitutionType": "지역응급의료기관",
            "generalEmergencyAvailable": -9,
            "generalEmergencyTotal": 3,
            "latitude": 34.5,
            "longitude": 127.1,
            "address": "전남",
        }
        panel, total, _, _, history, quality = updater.fetch_national(
            {"12": [item]},
            [],
        )
        self.assertEqual(total, 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(len(panel), 1)
        self.assertEqual(panel[0]["a"], -9)
        self.assertIsNone(panel[0]["s"])
        self.assertEqual(panel[0]["q"], "invalid_availability")
        self.assertEqual(quality["invalid_bed_value_count"], 1)

    def test_national_invalid_sample_is_counted_without_polluting_average(self):
        valid = {
            "c": "A2600068",
            "r": "전남",
            "n": "시험병원",
            "t": "지역응급의료기관",
            "a": 1,
            "o": 5,
            "s": 80.0,
            "q": None,
            "m": 0,
        }
        first = updater.update_national_history(
            [], [valid], "2026-07-30T00:10:00+09:00"
        )
        invalid = dict(valid, a=-9, o=3, s=None, q="invalid_availability")
        result = updater.update_national_history(
            first, [invalid], "2026-07-30T00:40:00+09:00"
        )
        record = next(item for item in result if item["code"] == valid["c"])
        self.assertEqual(record["sample_count"], 1)
        self.assertEqual(record["saturation_avg"], 80.0)
        self.assertEqual(record["saturation_min"], 80.0)
        self.assertEqual(record["saturation_max"], 80.0)
        self.assertEqual(record["invalid_sample_count"], 1)

        defensive = {}
        updater.merge_national_saturation(defensive, 140.0)
        self.assertEqual(defensive["invalid_sample_count"], 1)
        self.assertNotIn("saturation_avg", defensive)


class CompletenessTests(unittest.TestCase):
    def test_empty_region_response_is_marked_failed(self):
        responses = [[]] + [[{"emogCode": f"A{index:07d}"}] for index in range(1, 16)]
        with (
            mock.patch.object(updater, "request_json", return_value={}),
            mock.patch.object(updater, "get_items", side_effect=responses),
            mock.patch.object(updater.time, "sleep"),
        ):
            items_by_code, failed = updater.fetch_all_regions()
        self.assertEqual(len(items_by_code), 15)
        self.assertEqual(failed, ["서울"])
        self.assertNotIn("11", items_by_code)

    def test_partial_attempt_metadata_does_not_replace_complete_denominator(self):
        previous = {
            "captured": "2026-07-30T00:00:00+09:00",
            "total": 414,
            "unique_institution_count": 414,
            "raw_item_count": 426,
            "duplicate_count": 9,
            "invalid_count": 3,
            "snapshot_status": "complete",
        }
        attempt_quality = {
            "raw_item_count": 100,
            "unique_institution_count": 96,
            "duplicate_count": 2,
            "conflicting_duplicate_count": 0,
            "invalid_count": 2,
        }
        result = updater.build_stale_national_meta(
            previous,
            "2026-07-30T00:30:00+09:00",
            ["서울"],
            15,
            attempt_quality,
        )
        self.assertEqual(result["captured"], previous["captured"])
        self.assertEqual(result["unique_institution_count"], 414)
        self.assertEqual(result["raw_item_count"], 426)
        self.assertEqual(result["last_attempt_failed"], ["서울"])
        self.assertEqual(result["last_attempt_quality"], attempt_quality)


class DisplaySummaryTests(unittest.TestCase):
    def test_negative_availability_does_not_cancel_other_empty_beds(self):
        rows = [
            {
                "region": "광주",
                "grade": "A",
                "general_available": 10,
                "general_total": 20,
                "child_available": None,
                "child_total": None,
            },
            {
                "region": "전남",
                "grade": "B",
                "general_available": -3,
                "general_total": 10,
                "child_available": None,
                "child_total": None,
            },
        ]
        result = updater.summary(rows)
        self.assertEqual(result["general_available"], 10)
        self.assertEqual(result["general_overflow"], 3)
        self.assertEqual(result["general_valid_count"], 1)
        self.assertEqual(result["general_invalid_count"], 1)
        self.assertEqual(result["general_total"], 20)
        self.assertEqual(result["general_saturation"], 50.0)


class StaticSafetyCopyTests(unittest.TestCase):
    def test_automatic_refresh_preserves_delayed_data_warning_copy(self):
        source = updater.MAP_HTML.read_text(encoding="utf-8")
        stats = {
            "total": 2,
            "gwangju": 1,
            "jeonnam": 1,
            "general_available": 3,
            "general_overflow": 0,
            "general_valid_count": 2,
            "general_invalid_count": 1,
            "general_total": 10,
            "general_saturation": 70.0,
            "child_available": 1,
            "child_overflow": 0,
            "child_valid_count": 1,
            "child_invalid_count": 0,
            "child_total": 2,
            "child_saturation": 50.0,
            "grades": {"A": 1, "B": 1, "C": 0, "-": 0},
        }

        updated = updater.update_static_text(
            source,
            "2026-08-07T00:30:00+09:00",
            stats,
        )

        self.assertIn("마지막 수집 2026-08-07T00:30:00+09:00", updated)
        self.assertIn("약 30분 주기로 갱신되는 병상 현황", updated)
        self.assertIn("최근 수집 포화 70.0%", updated)
        self.assertIn("일반 응급실 유효 보고 2곳", updated)
        self.assertIn("원천값 확인 1곳", updated)
        self.assertIn("참고용 안내", updated)
        self.assertIn("실제 수용 가능 여부를 반드시 확인", updated)
        self.assertNotIn("실시간 포화", updated)
        self.assertEqual(
            updater.update_static_text(
                updated, "2026-08-07T00:30:00+09:00", stats
            ),
            updated,
        )


class ResearchArchiveTests(unittest.TestCase):
    def test_complete_snapshot_is_compact_and_idempotent_by_capture_time(self):
        rows = [
            {"c": "A1", "a": 1, "o": 10, "s": 90.0, "m": 0},
            {"c": "A2", "a": -1, "o": 20, "s": 105.0, "m": 2},
        ]
        quality = {"unique_institution_count": 2}
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                updater, "NATIONAL_SNAPSHOT_DIR", Path(directory)
            ):
                first = updater.archive_national_snapshot(
                    rows,
                    "2026-07-30T00:00:00+09:00",
                    quality,
                )
                updater.archive_national_snapshot(
                    rows,
                    "2026-07-30T00:00:00+09:00",
                    quality,
                )
                updater.archive_national_snapshot(
                    rows,
                    "2026-07-30T00:30:00+09:00",
                    quality,
                )
            lines = first.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        payload = json.loads(lines[0])
        self.assertEqual(payload["institution_count"], 2)
        self.assertEqual(
            payload["columns"],
            [
                "institution_code",
                "available",
                "total",
                "saturation",
                "message_count",
            ],
        )
        self.assertEqual(payload["values"][1], ["A2", -1, 20, 105.0, 2])

    def test_daily_archive_allows_same_day_institution_contraction(self):
        history = [
            {
                "date": "2026-07-30",
                "schema_version": updater.HISTORY_SCHEMA_VERSION,
                "date_basis": "Asia/Seoul",
                "code": "A1",
                "region": "서울",
                "name": "유지병원",
                "type": "지역응급의료센터",
                "available": 1,
                "total": 10,
                "saturation_avg": 90.0,
                "saturation_min": 80.0,
                "saturation_max": 100.0,
                "sample_count": 2,
            },
            {
                "date": "2026-07-30",
                "schema_version": updater.HISTORY_SCHEMA_VERSION,
                "date_basis": "Asia/Seoul",
                "code": "A2",
                "region": "서울",
                "name": "앞선수집만존재",
                "type": "지역응급의료기관",
                "available": 2,
                "total": 10,
                "saturation_avg": 80.0,
                "saturation_min": 80.0,
                "saturation_max": 80.0,
                "sample_count": 1,
            },
        ]
        latest_rows = [{"c": "A1"}]
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(updater, "NATIONAL_RESEARCH_DIR", Path(directory)):
                path = updater.archive_national_daily(
                    history,
                    latest_rows,
                    "2026-07-30T01:00:00+09:00",
                    {"unique_institution_count": 1},
                )
                payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["daily_union_institution_count"], 2)
        self.assertEqual(payload["latest_snapshot_institution_count"], 1)
        presence = {
            item["code"]: item["present_in_latest_snapshot"]
            for item in payload["institutions"]
        }
        self.assertEqual(presence, {"A1": True, "A2": False})


if __name__ == "__main__":
    unittest.main()

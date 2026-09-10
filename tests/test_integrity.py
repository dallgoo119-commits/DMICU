import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_emergency_map as u


class IntegrityTests(unittest.TestCase):
    def item(self, **values):
        return dict(emogCode='A1500001', emergencyRoomName='시험병원',
                    generalEmergencyAvailable=2, generalEmergencyTotal=10, **values)

    def test_invalid_numbers_never_truncate_or_crash(self):
        for value in ['2.5', 'NaN', 'Infinity', '-Infinity', True, 'abc', '1e30']:
            with self.subTest(value=value):
                self.assertIsNone(u.number(value))
        self.assertEqual(u.number(' 2.0 '), 2)
        self.assertEqual(u.number('-2'), -2)

    def test_percent_rejects_invalid_denominators_and_retains_overflow(self):
        for available, total in [(1, 0), (1, -2), (12, 10), (None, 10), (1.5, 10)]:
            self.assertIsNone(u.percent(available, total))
        self.assertEqual(u.percent(-2, 10), 120)
        self.assertEqual(u.percent(11, 16), 31.3)

    def test_quality_distinguishes_missing_invalid_and_zero(self):
        self.assertEqual(u.bed_quality('2.5', 10), 'invalid')
        self.assertEqual(u.bed_quality(None, 10), 'missing')
        self.assertEqual(u.bed_quality(0, 0), 'zero_total')
        self.assertEqual(u.bed_quality(-1, 10), 'overflow_report')

    def test_local_duplicate_not_counted_twice(self):
        item = self.item()
        self.assertEqual(len(u.fetch_rows({}, [item, copy.deepcopy(item)])), 1)

    def test_local_conflicting_duplicates_fail_closed(self):
        item = self.item()
        other = dict(item, generalEmergencyAvailable=3)
        with self.assertRaisesRegex(RuntimeError, 'Conflicting'):
            u.fetch_rows({}, [item, other])

    def test_bad_coordinates_keep_hospital_in_list(self):
        row = u.fetch_rows({}, [self.item(latitude='broken', longitude=500)])[0]
        self.assertIsNone(row['lat'])
        self.assertIsNone(row['lon'])
        self.assertEqual(row['general_saturation'], 80)

    def test_invalid_source_beds_are_preserved_but_not_calculated(self):
        row = u.fetch_rows({}, [dict(self.item(), generalEmergencyAvailable='2.5')])[0]
        self.assertEqual(row['source_beds']['generalEmergencyAvailable'], '2.5')
        self.assertEqual(row['general_status'], 'invalid')
        self.assertIsNone(row['general_saturation'])

    def test_summary_excludes_invalid_pairs(self):
        rows = u.fetch_rows({}, [self.item(), dict(self.item(), emogCode='A2600001', generalEmergencyAvailable=11)])
        stats = u.summary(rows)
        self.assertEqual(stats['general_included'], 1)
        self.assertEqual(stats['general_total'], 10)
        self.assertEqual(stats['general_saturation'], 80)
        self.assertIsNone(stats['child_saturation'])

    def test_same_capture_time_is_not_double_counted(self):
        rows = u.fetch_rows({}, [self.item()])
        stamp = '2026-09-10T23:00:00+09:00'
        history = u.update_history([], rows, stamp)
        self.assertEqual(u.update_history(copy.deepcopy(history), rows, stamp), history)
        nat = u.fetch_national({'12':[self.item()]}, [])[4]
        history = u.update_national_history([], nat, stamp)
        self.assertEqual(u.update_national_history(copy.deepcopy(history), nat, stamp), history)

    def test_json_cannot_break_out_of_script(self):
        value = [{'notice':'</script><script>alert(1)</script>&'}]
        source = u.replace_array('const DATA=[];', 'DATA', value)
        self.assertNotIn('</script>', source)
        self.assertEqual(u.extract_array(source, 'DATA'), value)

    def test_split_history_roundtrips_without_data_loss(self):
        records = [{'code':'A2','date':'2026-09-01','x':None}, {'code':'A1','date':'2026-09-01','x':120}]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(u,'TREND_DIR',Path(directory)):
            u.write_history('HISTORY', records)
            self.assertEqual(u.load_history('const HISTORY=[];', 'HISTORY'), sorted(records,key=lambda r:r['code']))

    def test_update_roundtrip_keeps_new_files_and_changes_capture(self):
        original = u.MAP_HTML.read_text(encoding='utf-8')
        stamp = '2026-09-11T00:00:00+09:00'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root/'map.html'
            page.write_text(original, encoding='utf-8')
            with (mock.patch.object(u,'MAP_HTML',page), mock.patch.object(u,'ROOT',root),
                  mock.patch.object(u,'TREND_DIR',root/'trends'),
                  mock.patch.object(u,'NATIONAL_CODES',{'12':'광주전남'}),
                  mock.patch.object(u,'fetch_all_regions',return_value=({'12':[self.item()]},[])),
                  mock.patch.object(u,'capture_timestamp',return_value=stamp),
                  mock.patch.object(u,'archive_national_daily'), mock.patch.object(u,'archive_national_snapshot'),
                  mock.patch.object(u,'update_index_cache_buster')):
                u.main()
                updated = page.read_text(encoding='utf-8')
                self.assertEqual(u.extract_array(updated,'LOCALMETA')[0]['captured'],stamp)
                self.assertEqual(len(u.extract_array(updated,'NATIONAL_CURRENT')),1)
                self.assertEqual(u.extract_array(updated,'HISTORY'),[])
                self.assertEqual(len(u.load_history(updated,'HISTORY')),1)
                self.assertIn('assets/dashboard.js',updated)
                self.assertIn('산정 불가',updated)
                self.assertNotIn('None%',updated)


if __name__ == '__main__':
    unittest.main()

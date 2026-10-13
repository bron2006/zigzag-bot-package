import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('gold_history_audit',Path(__file__).resolve().parents[1]/'research_gold_breaker_20261013'/'audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class GoldHistoryAuditTest(unittest.TestCase):
    def rows(self):return [dict(ts=i*60,Open=2000.,High=2001.,Low=1999.,Close=2000.5) for i in range(60)]
    def test_complete_H1_uses_exactly_sixty_real_minutes(self):
        hours,bad=audit.hourly(self.rows())
        self.assertEqual(bad,0);self.assertEqual(len(hours),1)
        self.assertEqual(hours[0],dict(ts=0,Open=2000.,High=2001.,Low=1999.,Close=2000.5))
    def test_missing_minute_is_not_filled_into_eligible_H1(self):
        rows=self.rows();rows.pop(30)
        self.assertEqual(audit.hourly(rows),([],1))
    def test_duplicate_minute_is_not_complete_H1(self):
        rows=self.rows();rows.insert(30,rows[30])
        self.assertEqual(audit.hourly(rows),([],1))
    def test_fixed_protocol_scale_not_symbol_digits(self):
        b=audit.decode_bar(dict(low='199950000',deltaOpen='50000',deltaHigh='150000',deltaClose='100000',utcTimestampInMinutes='100'))
        self.assertEqual(b['Low'],1999.5)
        self.assertEqual(b['High'],2001.)

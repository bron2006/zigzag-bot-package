from datetime import date
import copy
import unittest
from ny_h4_reclaim import RULE,bounds,detect
from forward_structure_research import outcome


def fixture(day=date(2026,10,12)):
    start,end,_=bounds(day)
    bars=[dict(ts=t,Open=100.,High=105.,Low=95.,Close=100.) for t in range(start,end,300)]
    return bars,end


def bar(ts,o=94.,h=96.,l=93.,c=94.):return dict(ts=ts,Open=o,High=h,Low=l,Close=c)


class NewYorkReclaimTest(unittest.TestCase):
    def test_NY_wall_clock_range_automatically_uses_summer_and_winter_offsets(self):
        for day,start_hour,end_hour in [(date(2026,7,1),4,8),(date(2026,1,5),5,9)]:
            start,end,_=bounds(day)
            self.assertEqual(start%86400,start_hour*3600)
            self.assertEqual(end%86400,end_hour*3600)

    def test_DST_transition_anchor_requires_exact_local_midnight_to_four(self):
        self.assertEqual(bounds(date(2026,3,8))[1]-bounds(date(2026,3,8))[0],3*3600)
        self.assertEqual(bounds(date(2026,11,1))[1]-bounds(date(2026,11,1))[0],5*3600)

    def test_closed_lower_break_then_later_closed_reclaim_is_LONG(self):
        rows,end=fixture()
        rows+=[bar(end),bar(end+300,o=94.,h=94.5,l=92.,c=93.5),bar(end+600,o=93.5,h=97.,l=91.5,c=96.)]
        result=detect(rows);intent=result['intents'][0]
        self.assertEqual(intent['side'],1)
        self.assertEqual(intent['ts'],end+900)
        self.assertEqual(intent['stop'],91.5)
        self.assertEqual(intent['range_low'],95)
        self.assertEqual(intent['range_high'],105)
        self.assertEqual(intent['target_multiple'],2)

    def test_closed_upper_break_then_later_closed_reclaim_is_SHORT(self):
        rows,end=fixture()
        rows+=[bar(end,o=104,h=107,l=103,c=106),bar(end+300,o=106,h=109,l=102,c=104)]
        intent=detect(rows)['intents'][0]
        self.assertEqual(intent['side'],-1)
        self.assertEqual(intent['stop'],109)

    def test_wick_break_does_not_arm_a_setup(self):
        rows,end=fixture();rows.append(bar(end,o=100,h=101,l=90,c=99))
        result=detect(rows)
        self.assertEqual(result['intents'],[])
        self.assertEqual(result['states'][-1]['status'],'waiting_breakout')

    def test_wick_return_without_close_above_lower_line_is_not_entry(self):
        rows,end=fixture();rows+=[bar(end),bar(end+300,o=94,h=99,l=93,c=94)]
        result=detect(rows)
        self.assertEqual(result['intents'],[])
        self.assertEqual(result['states'][-1]['status'],'waiting_return')

    def test_close_on_line_is_not_confirmation(self):
        rows,end=fixture();rows.append(bar(end,o=96,h=96,l=94,c=95))
        self.assertEqual(detect(rows)['intents'],[])
        rows[-1]=bar(end);rows.append(bar(end+300,o=94,h=96,l=94,c=95))
        self.assertEqual(detect(rows)['intents'],[])

    def test_missing_anchor_or_missing_post_range_bar_fails_closed(self):
        rows,end=fixture();rows.pop(10);rows+=[bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        self.assertEqual(detect(rows)['intents'],[])
        rows,end=fixture();rows+=[bar(end),bar(end+600,o=94,h=97,l=94,c=96)]
        result=detect(rows)
        self.assertEqual(result['intents'],[])
        self.assertEqual(result['states'][-1]['status'],'post_range_data_gap')

    def test_future_poisoning_cannot_change_confirmed_setup_or_stop(self):
        rows,end=fixture();rows+=[bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        first=detect(rows)['intents']
        rows.append(bar(end+600,o=96,h=1000,l=1,c=500))
        self.assertEqual(detect(rows)['intents'],first)
        self.assertEqual(len(first),1)

    def test_no_entry_or_levels_before_H4_has_finished(self):
        rows,_=fixture();result=detect(rows[:-1])
        self.assertEqual(result['intents'],[])
        self.assertIsNone(result['states'][0]['high'])

    def test_actual_next_open_sets_two_R_target_not_return_candle_close(self):
        rows,end=fixture();rows+=[bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        intent=detect(rows)['intents'][0]
        rows.append(bar(end+600,o=97,h=105.1,l=96,c=100))
        result=outcome(intent,rows,end+1000,'base')
        self.assertEqual(result['entry'],97)
        self.assertEqual(result['stop'],93)
        self.assertEqual(result['target'],105)
        self.assertEqual(result['reason'],'target')

    def test_no_unrequested_fixed_time_or_session_exit(self):
        rows,end=fixture();rows+=[bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        intent=detect(rows)['intents'][0]
        rows.append(bar(end+600,o=96,h=97,l=95,c=96))
        result=outcome(intent,rows,end+20*3600,'stress')
        self.assertEqual(result['status'],'pending')
        self.assertEqual(result['reason'],'waiting_stop_or_target')

    def test_entry_gap_through_stop_is_skipped_not_negative_risk(self):
        rows,end=fixture();rows+=[bar(end),bar(end+300,o=94,h=97,l=94,c=96)]
        intent=detect(rows)['intents'][0]
        rows.append(bar(end+600,o=92,h=94,l=90,c=93))
        self.assertEqual(outcome(intent,rows,end+1000,'stress')['status'],'skipped')

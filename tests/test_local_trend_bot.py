import copy
import json
from pathlib import Path
import tempfile
import unittest
from local_trend_bot.strategy import DAY,decisions,execution_positions,latest_decision,validate
from local_trend_bot.backtest import simulate,stats,paired_lower
from local_trend_bot.bot import PaperBot,status,get_public


def history(count=400):
    return [[i*DAY,100+i,101+i,99+i,101+i] for i in range(count)]


def snapshot(rows,now):
    return dict(observed_ms=now,symbols={s:dict(rows=rows,bid=499.,ask=500.,quote_ms=now)
                                        for s in ('BTCUSDT','ETHUSDT')})


class TrendRulesTests(unittest.TestCase):
    def test_future_mutation_does_not_change_past(self):
        rows=history()
        changed=copy.deepcopy(rows)
        changed[-1][1:5]=[10000,10002,9999,10001]
        for rule in ('donchian55_20','momentum365'):
            self.assertEqual(decisions(rows,rule)[:-1],decisions(changed,rule)[:-1])
    def test_breakout_excludes_current_high(self):
        rows=history(60)
        rows[-1][1:5]=[200,250,199,240]
        self.assertEqual(decisions(rows,'donchian55_20')[-1],1)
    def test_breakdown_and_state_persistence(self):
        rows=history(65)
        rows[55][1:5]=[200,202,199,201]
        rows[56][1:5]=[190,192,189,191]
        rows[57][1:5]=[1,3,.5,2]
        state=decisions(rows,'donchian55_20')
        self.assertEqual(state[55:58],[1,1,0])
    def test_two_day_buffer(self):
        rows=history()
        desired=decisions(rows,'momentum365')
        self.assertEqual(execution_positions(rows,'momentum365'),[0,0]+desired[:-2])
    def test_latest_uses_day_before_yesterday(self):
        rows=history()
        now=400*DAY+1000
        for rule in ('donchian55_20','momentum365'):
            result=latest_decision(rows,rule,now)
            self.assertEqual(result['desired'],decisions(rows,rule)[-2])
            self.assertEqual(result['signal_day'],398*DAY)
    def test_forming_bar_never_used(self):
        rows=history(401)
        self.assertEqual(latest_decision(rows,'momentum365',400*DAY+1000),
                         latest_decision(rows[:-1],'momentum365',400*DAY+1000))
    def test_gap_duplicate_and_invalid_prices_rejected(self):
        for rows in (history()[:-2]+history()[-1:],history()+[history()[-1]],[[0,1,1,2,1]],[[0,float('nan'),2,1,1]]):
            with self.assertRaises(ValueError):validate(rows)
    def test_stale_history_rejected(self):
        with self.assertRaises(ValueError):latest_decision(history(),'momentum365',401*DAY)
    def test_cost_and_end_liquidation(self):
        curve,changes=simulate([[0,100,100,100,100]],[1],.003)
        self.assertAlmostEqual(curve[-1],.997**2)
        self.assertEqual(changes,2)
    def test_existing_holder_gets_gap_before_exit(self):
        curve,_=simulate([[0,100,110,100,110],[DAY,200,200,200,200]],[1,0],0)
        self.assertEqual(curve[-1],2)
    def test_cash_flat_and_drawdown_initial_peak(self):
        curve,_=simulate(history(3),[0,0,0],.003)
        self.assertEqual(curve,[1.,1.,1.])
        self.assertEqual(stats([.5,1.])['max_drawdown'],-.5)
    def test_paired_identical_control_is_zero(self):
        self.assertEqual(paired_lower([1.,1.2,1.1],[1.,1.2,1.1],100),0)
    def test_independent_equity_recurrence_matches_engine(self):
        rows=history(12)
        positions=[0,1,1,0,0,1,0,1,1,1,0,1]
        for fee in (0,.001,.003):
            curve,_=simulate(rows,positions,fee)
            value=1.
            previous_position=0
            independent=[]
            for i,(row,position) in enumerate(zip(rows,positions)):
                opening,close=map(float,(row[1],row[4]))
                if previous_position:
                    value*=opening/float(rows[i-1][4])
                if position!=previous_position:
                    value*=1-fee
                if position:
                    value*=close/opening
                independent.append(value)
                previous_position=position
            if previous_position:independent[-1]*=1-fee
            for actual,expected in zip(curve,independent):
                self.assertAlmostEqual(actual,expected,places=12)


class LocalBotTests(unittest.TestCase):
    def test_first_cycle_bootstrap_then_paper_entry_no_duplicate_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paper.sqlite3'
            bot=PaperBot(path,diagnostic=True)
            try:
                now=400*DAY+1000
                report=bot.cycle(snapshot(history(),now),now)
                self.assertTrue(all(r['action']=='bootstrap_cash' for r in report['records']))
                self.assertEqual(status(path)['paper_trades'],0)
                now=401*DAY+1000
                report=bot.cycle(snapshot(history(401),now),now)
                self.assertTrue(all(r['action']=='paper_buy' for r in report['records']))
                self.assertEqual(status(path)['paper_trades'],4)
                bot.cycle(snapshot(history(401),now),now)
                self.assertEqual(status(path)['paper_trades'],4)
            finally: bot.close()
            bot=PaperBot(path,diagnostic=True)
            try:
                bot.cycle(snapshot(history(401),now),now)
                self.assertEqual(status(path)['paper_trades'],4)
            finally:bot.close()
    def test_default_signals_only_never_trades(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=PaperBot(Path(folder)/'paper.sqlite3')
            try:
                for count in (400,401):
                    now=count*DAY+1000
                    report=bot.cycle(snapshot(history(count),now),now)
                self.assertTrue(all(r['units']==0 for r in report['records']))
                self.assertEqual(status(bot.path)['paper_trades'],0)
            finally:bot.close()
    def test_live_paper_exit_uses_bid_and_two_fees(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=PaperBot(Path(folder)/'paper.sqlite3',True)
            try:
                now=400*DAY+1000
                bot.cycle(snapshot(history(),now),now)
                rows=history(402)
                rows[400][1:5]=[2,3,.5,1]
                now=401*DAY+1000
                bot.cycle(snapshot(rows[:401],now),now)
                now=402*DAY+1000
                report=bot.cycle(snapshot(rows,now),now)
                self.assertTrue(all(r['action']=='paper_sell' for r in report['records']))
                for record in report['records']:
                    self.assertEqual(record['units'],0)
                    self.assertAlmostEqual(record['cash'],500*.997**2*499/500)
                self.assertEqual(status(bot.path)['paper_trades'],8)
            finally:bot.close()
    def test_invalid_second_asset_has_no_partial_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=PaperBot(Path(folder)/'paper.sqlite3',True)
            try:
                now=400*DAY+1000
                data=snapshot(history(),now)
                data['symbols']['ETHUSDT']['bid']=501
                with self.assertRaises(ValueError):bot.cycle(data,now)
                self.assertEqual(bot.db.execute('SELECT count(*) FROM decisions').fetchone()[0],0)
            finally:bot.close()
    def test_stale_quote_does_not_trade(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=PaperBot(Path(folder)/'paper.sqlite3',True)
            try:
                now=400*DAY+100000
                data=snapshot(history(),now)
                data['symbols']['BTCUSDT']['quote_ms']=now-45001
                with self.assertRaises(ValueError):bot.cycle(data,now)
            finally:bot.close()
    def test_single_writer_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paper.sqlite3'
            bot=PaperBot(path)
            try:
                with self.assertRaises(RuntimeError):PaperBot(path)
            finally:bot.close()
    def test_status_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'missing.sqlite3'
            self.assertEqual(status(path),dict(exists=False))
            self.assertFalse(path.exists())
    def test_private_api_route_impossible(self):
        with self.assertRaises(ValueError):get_public('order')
    def test_error_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            bot=PaperBot(Path(folder)/'paper.sqlite3')
            try:
                bot.error('test failure')
                self.assertEqual(status(bot.path)['health']['last_error']['message'],'test failure')
            finally:bot.close()


if __name__=='__main__':unittest.main()

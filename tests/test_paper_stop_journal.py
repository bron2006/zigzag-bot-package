from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
from paper_stop_journal import PaperStopJournal


def q(bid=100,ask=100.1,ts=1000):
    return dict(bid=bid,ask=ask,bid_ts=ts,ask_ts=ts,ts=ts)


class PersistentPaperStopTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.path=str(Path(self.folder.name)/'paper.sqlite3')
        self.book=PaperStopJournal(self.path)

    def tearDown(self):
        self.book.close()
        self.folder.cleanup()

    def open(self,side=1,intent='signal-1',pair='TESTUSD'):
        return self.book.open(intent,pair,side,q(),1000,98 if side==1 else 102,
                              103 if side==1 else 97,minimum=.1,step=.1,maximum=100,
                              quote_currency='USD')

    def test_buy_uses_ask_entry_and_bid_stop(self):
        opened=self.open()
        self.assertEqual(opened['entry'],100.1)
        result=self.book.observe('TESTUSD',q(97,97.1,1010),1010)
        self.assertEqual(result['status'],'closed')
        self.assertEqual(result['exit'],97)
        self.assertLess(float(result['pnl_usd']),-5) # gap exceeds planned .5%risk

    def test_short_uses_bid_entry_and_ask_stop(self):
        self.open(-1)
        result=self.book.observe('TESTUSD',q(101.95,102.05,1001),1001)
        self.assertEqual(result['reason'],'stop')
        self.assertEqual(result['exit'],102.05)

    def test_target_conservative_and_close_idempotent(self):
        self.open()
        result=self.book.observe('TESTUSD',q(105,105.1,1001),1001)
        self.assertEqual(result['exit'],103)
        before=self.book.status()['balance']
        self.book.observe('TESTUSD',q(105,105.1,1001),1001)
        self.assertEqual(before,self.book.status()['balance'])
        self.assertEqual(self.open()['status'],'already_recorded')

    def test_restart_preserves_position_and_cash(self):
        self.open()
        self.book.close()
        self.book=PaperStopJournal(self.path)
        self.assertEqual(self.book.status()['positions'][0]['state'],'open')
        self.book.observe('TESTUSD',q(103,103.1,1001),1001)
        before=self.book.status()['balance']
        self.book.close()
        self.book=PaperStopJournal(self.path)
        self.assertEqual(self.book.status()['balance'],before)

    def test_one_global_position(self):
        self.open()
        self.assertEqual(self.open(intent='other',pair='SECONDUSD')['reason'],'one_open_position')

    def test_open_spread_marks_equity_but_stale_mark_is_not_presented_as_live(self):
        self.open()
        live=self.book.status(now=1000)
        self.assertEqual(live['balance'],'1000.00')
        self.assertLess(float(live['equity_usd']),1000)
        stale=self.book.status(now=2000)
        self.assertFalse(stale['marks_fresh'])
        self.assertIsNone(stale['equity_usd'])

    def test_parallel_opens_reserve_one_position_atomically(self):
        def attempt(intent):
            book=PaperStopJournal(self.path)
            try:
                return book.open(intent,'TESTUSD',1,q(),1000,98,103,
                                 minimum=.1,step=.1,maximum=100,quote_currency='USD')['status']
            finally: book.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(attempt,['parallel-a','parallel-b']))
        self.assertEqual(sorted(statuses),['open','skipped'])
        self.assertEqual(len(self.book.status()['positions']),1)

    def test_stale_future_crossed_quotes_and_other_currency_rejected(self):
        for quote in (q(ts=990),q(ts=1001),q(101,100)):
            with self.assertRaises(ValueError):
                self.book.open('bad','TESTUSD',1,quote,1000,98,103,minimum=.1,step=.1,
                               maximum=100,quote_currency='USD')
        with self.assertRaises(ValueError):
            self.book.open('bad','TESTJPY',1,q(),1000,98,103,minimum=.1,step=.1,
                           maximum=100,quote_currency='JPY')
        self.assertEqual(self.book.status()['positions'],[])

    def test_contract_mismatch_never_resets_account(self):
        with self.assertRaises(ValueError): PaperStopJournal(self.path,initial=500)
        self.assertEqual(self.book.status()['balance'],'1000.00')

    def test_balance_and_positions_read_in_one_snapshot(self):
        statements=[]
        self.book.connection.set_trace_callback(statements.append)
        self.book.status()
        self.book.connection.set_trace_callback(None)
        self.assertEqual(statements[0],'BEGIN')
        self.assertEqual(statements[-1],'COMMIT')

    def test_no_fixed_time_expiry_and_old_quote_ignored(self):
        self.open()
        self.assertEqual(self.book.observe('TESTUSD',q(ts=3000),3000)['status'],'open')
        self.assertEqual(self.book.observe('TESTUSD',q(97,97.1,2999),3000)['status'],'ignored_old_or_duplicate_quote')

from pathlib import Path
import tempfile
import unittest
from paper_stop_journal import PaperStopJournal
from paper_stop_view import snapshot


def quote(ts=1000,bid=100,ask=100.1):
    return dict(ts=ts,bid_ts=ts,ask_ts=ts,bid=bid,ask=ask)


class PaperStopViewTest(unittest.TestCase):
    def test_older_pages_preserve_current_balance_and_open_position(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'paper.sqlite3')
            book=PaperStopJournal(path)
            try:
                for i in range(101):
                    ts=1000+2*i
                    book.open(str(i),'TESTUSD',1,quote(ts),ts,98,103,
                              minimum=.1,step=.1,maximum=100,quote_currency='USD')
                    book.observe('TESTUSD',quote(ts+1,103,103.1),ts+1)
                book.open('open','TESTUSD',1,quote(1300),1300,98,103,
                          minimum=.1,step=.1,maximum=100,quote_currency='USD')
                first=snapshot(path,1300)
                older=snapshot(path,1300,before=first['next_before'])
                self.assertEqual(len(first['closed_positions']),100)
                self.assertEqual(len(older['closed_positions']),1)
                self.assertEqual(older['closed_positions'][0]['id'],1)
                self.assertEqual(first['balance'],older['balance'])
                self.assertEqual(len(older['open_positions']),1)
                self.assertEqual(older['by_pair'][0]['closed'],101)
            finally: book.close()
    def test_absent_journal_is_not_fake_1000_balance_and_never_creates_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'absent.sqlite3'
            view=snapshot(None,1000)
            self.assertEqual(view['status'],'not_started')
            self.assertIsNone(view['balance'])
            with self.assertRaises(FileNotFoundError): snapshot(str(path),1000)
            self.assertFalse(path.exists())

    def test_existing_journal_exposes_levels_pnl_staleness_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'paper.sqlite3')
            book=PaperStopJournal(path)
            try:
                book.open('1','TESTUSD',1,quote(),1000,98,103,minimum=.1,step=.1,maximum=100,quote_currency='USD')
                view=snapshot(path,1001)
                self.assertEqual(view['balance'],1000)
                self.assertLess(view['equity'],1000)
                self.assertEqual(view['open_positions'][0]['stop'],98)
                self.assertEqual(view['open_positions'][0]['target'],103)
                self.assertIsNone(snapshot(path,2000)['equity'])
                book.observe('TESTUSD',quote(1002,103,103.1),1002)
                closed=snapshot(path,1010,{'TESTUSD':quote(1010)})
                self.assertEqual(closed['closed_positions'][0]['exit_ts'],1002)
                self.assertEqual(closed['closed_positions'][0]['reason'],'target')
                self.assertEqual(closed['open_positions'],[])
                self.assertGreater(closed['balance'],1000)
                self.assertEqual(closed['by_pair'][0]['closed'],1)
            finally: book.close()

    def test_invalid_account_contract_rejected_not_zeroed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'paper.sqlite3')
            book=PaperStopJournal(path)
            try:
                book.connection.execute("UPDATE account SET version='bad'")
                with self.assertRaises(ValueError): snapshot(path,1000)
                self.assertEqual(book.connection.execute('SELECT balance FROM account').fetchone()[0],'1000.00')
            finally: book.close()

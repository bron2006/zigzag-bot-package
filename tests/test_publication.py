import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from twisted.internet.defer import succeed, fail
import db
import scanner
import publication_tracking as receipts
import signal_accounting
import notifier
import signal_tracking


class EntryValidationTest(unittest.TestCase):
    def result(self, quote):
        return dict(is_trade_allowed=True,verdict_text='BUY',pair='TEST',price=100,
                    data_status={'price': {'mid':100}},timeframe='1m',ts=1000,
                    measurement_version='live_mid_v1',entry_quote=quote)

    def test_invalid_stale_future_or_single_sided_entry_not_recorded(self):
        valid = dict(ts=999,mid=100,bid=99,ask=101)
        for field, value in [('ts',994),('ts',1001),('mid',float('nan')),('mid',200),('bid',0),('ask',98),('bid',None)]:
            with patch.object(db,'create_signal_outcome') as write:
                self.assertIsNone(signal_tracking.maybe_record_signal(self.result(dict(valid,**{field:value}))))
                write.assert_not_called()

    def test_valid_entry_has_prepared_publication_before_publish(self):
        with patch.object(signal_tracking.time,'time',return_value=1000), \
             patch.object(db,'create_signal_outcome',return_value=42) as write, \
             patch('endpoint_sampler.register'):
            self.assertEqual(signal_tracking.maybe_record_signal(self.result(dict(ts=999,mid=100,bid=99,ask=101))),42)
        self.assertEqual(write.call_args.kwargs['evidence']['publication']['state'],'prepared')


class DeliveryTest(unittest.TestCase):
    def attempt(self, web, telegram):
        result = dict(signal_outcome_id=42, timeframe='5m')
        def dispatch(*args):
            return succeed(True)
        with patch.object(scanner.app_state, 'publish_signal_sse', return_value=web), \
             patch.object(scanner, 'get_chat_id', return_value=1), \
             patch.object(scanner.db, 'get_user_language', return_value='uk'), \
             patch.object(scanner.telegram_ui, '_format_signal_message', return_value='test'), \
             patch.object(scanner.telegram_ui, 'get_main_menu_kb', return_value=None), \
             patch.object(scanner.autotrader, 'maybe_enter_trade'), \
             patch.object(scanner, 'logger') as log, \
             patch.object(scanner, '_send_signal_async', side_effect=lambda *a,**k: fail(telegram) if isinstance(telegram,Exception) else succeed(telegram)), \
             patch.object(receipts, 'remember') as remember, \
             patch.object(scanner, 'deferToThreadPool', side_effect=dispatch):
            d = scanner._publish_recorded_signal('TEST', result, 90)
        return d.result, remember.call_args.args, log

    def test_false_is_failure_not_success_log(self):
        result, receipt, log = self.attempt(True, False)
        self.assertEqual(receipt, (42, 'queued', 'failed'))
        self.assertFalse(any('Telegram accepted' in str(c.args[0]) for c in log.info.call_args_list))

    def test_success_is_recorded(self):
        result, receipt, log = self.attempt(True, True)
        self.assertEqual(receipt, (42, 'queued', 'accepted'))
        self.assertTrue(any('Telegram accepted' in str(c.args[0]) for c in log.info.call_args_list))

    def test_both_fail_and_exception_are_not_a_signal(self):
        for telegram in (False, RuntimeError('network')):
            result, receipt, log = self.attempt(False, telegram)
            self.assertIsNone(result)
            self.assertEqual(receipt, (42, 'failed', 'failed'))

    def test_http_200_without_telegram_ok_is_not_success(self):
        response = Mock(ok=True)
        response.json.return_value = dict(ok=False)
        with patch.object(notifier, '_get_bot_token', return_value='offline'), \
             patch.object(notifier._requests, 'post', return_value=response):
            self.assertFalse(notifier._http_fallback(1, 'test'))


class PublicationDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.assertEqual(db.engine.url.database, ':memory:')
        db.Base.metadata.create_all(db.engine)
        self.evidence = dict(version='live_mid_v1', publication=dict(version=1,state='prepared'))
        self.id = db.create_signal_outcome(pair='ZZPUB',timeframe='1m',verdict='BUY',score=20,
            entry_price=100,horizon_seconds=300,entry_ts=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=400),evidence=self.evidence)

    def test_receipt_preserved_when_stale_resolver_writes(self):
        self.assertTrue(db.save_signal_publication(self.id, 'queued', 'failed'))
        self.assertTrue(db.resolve_signal_outcome(self.id,outcome='up_timed',exit_price=101,evidence=self.evidence))
        row = db.get_signal_endpoint_audit(self.id)
        self.assertEqual(row['evidence']['publication']['state'], 'unconfirmed')
        self.assertEqual(row['evidence']['publication']['telegram'], 'failed')
        self.assertFalse(db.save_signal_publication(self.id, 'failed', 'failed'))

    def test_no_fake_receipts_for_legacy(self):
        identifier = db.create_signal_outcome(pair='ZZPUB',timeframe='1m',verdict='BUY',score=20,
            entry_price=100,horizon_seconds=300,evidence=dict(version='live_mid_v1'))
        self.assertFalse(db.save_signal_publication(identifier,'queued','accepted'))

    def test_confirmed_receipt_survives_resolution_and_idempotent_retry(self):
        self.assertTrue(db.save_signal_publication(self.id, 'queued', 'accepted'))
        self.assertTrue(db.resolve_signal_outcome(self.id, outcome='down_timed', exit_price=99,
                                                 evidence=self.evidence))
        self.assertTrue(db.save_signal_publication(self.id, 'queued', 'accepted'))
        row = db.get_signal_endpoint_audit(self.id)
        self.assertEqual(row['evidence']['publication']['state'], 'confirmed')
        self.assertEqual(row['evidence']['publication']['telegram'], 'accepted')

    def test_retry_after_database_failure(self):
        with patch.object(receipts, '_pending', {}), patch.object(db,'save_signal_publication',side_effect=[False,True]):
            receipts.remember(self.id,'queued','accepted')
            self.assertFalse(receipts.save(self.id,'queued','accepted'))
            self.assertIn(self.id,receipts._pending)
            receipts.flush_pending()
            self.assertNotIn(self.id,receipts._pending)

    def test_unavailable_database_stops_retry_batch(self):
        with patch.object(receipts, '_pending', {}), \
             patch.object(db, 'save_signal_publication', return_value=False) as save:
            receipts.remember(self.id, 'queued', 'accepted')
            receipts.remember(self.id + 1, 'queued', 'accepted')
            receipts.flush_pending()
            self.assertEqual(save.call_count, 1)
            self.assertEqual(len(receipts._pending), 2)

    def test_unconfirmed_or_failed_publication_cannot_earn_money(self):
        row = SimpleNamespace(id=1,outcome='up_timed',entry_price=100,exit_price=101,verdict='BUY',pair='TEST',entry_ts=datetime(2026,10,10))
        for state, expected in [('prepared','unknown'),('unconfirmed','unknown'),('failed','cancelled'),('confirmed','win')]:
            audit = {1: dict(publication=dict(version=1,state=state))}
            result = signal_accounting.summarize([row],audit)
            self.assertEqual(result['counts'],{expected:1})
            self.assertEqual(result['scenario']['measured_pnl'],8 if state=='confirmed' else 0)

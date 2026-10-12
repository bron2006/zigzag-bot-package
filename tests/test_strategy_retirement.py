import os
from unittest import TestCase
from unittest.mock import patch
import scanner
import signal_tracking


class RetiredStrategyTest(TestCase):
    def test_retired_scanners_never_start_analysis_even_if_UI_flags_enabled(self):
        with patch.dict(os.environ,LEGACY_SIGNAL_TEST_ENABLED='false'),patch.object(scanner,'_process_one_asset') as process:
            scanner.scan_markets_once()
            scanner.scan_crypto_once()
            process.assert_not_called()

    def test_inflight_result_cannot_publish_or_send_Telegram(self):
        with patch.dict(os.environ,LEGACY_SIGNAL_TEST_ENABLED='false'), \
             patch.object(scanner.app_state,'publish_signal_sse') as web, \
             patch.object(scanner,'_send_signal_async') as telegram:
            self.assertIsNone(scanner._handle_analysis_result('EURUSD',dict(is_trade_allowed=True)).result)
            self.assertIsNone(scanner._publish_recorded_signal('EURUSD',{},99).result)
            web.assert_not_called()
            telegram.assert_not_called()

    def test_manual_analysis_cannot_restart_old_expiry_ledger(self):
        with patch.dict(os.environ,LEGACY_SIGNAL_TEST_ENABLED='false'),patch.object(signal_tracking.db,'create_signal_outcome') as write:
            self.assertIsNone(signal_tracking.maybe_record_signal(dict(is_trade_allowed=True,verdict_text='BUY')))
            write.assert_not_called()

    def test_background_services_do_not_schedule_retired_strategy_loops(self):
        import app
        with patch.dict(os.environ,LEGACY_SIGNAL_TEST_ENABLED='false',PAPER_STOP_JOURNAL_PATH='/data/paper_stops_v1.sqlite3'), \
             patch.object(app.app_state,'restore_scanner_state'),patch.object(app.bot,'start_telegram_bot'), \
             patch.object(app.ctrader,'start_ctrader_client'),patch.object(app,'_create_thread_pool'), \
             patch.object(app,'_paper_pool',None),patch.object(app,'_start_loop') as start:
            app._start_background_services()
            names={c.kwargs['name'] for c in start.call_args_list}
            self.assertTrue({'scanner','scanner_crypto','signal_outcome_resolver','threshold_advisor','threshold_milestone_check'}.isdisjoint(names))
            self.assertIn('paper_stop_control',names)

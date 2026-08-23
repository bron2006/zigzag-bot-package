import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import telegram_ui


def _fake_update(user_id=1064175237, query_data="vwapexec_on"):
    query = Mock()
    query.data = query_data
    query.message = SimpleNamespace(message_id=42, chat_id=1064175237)
    query.answer = Mock()

    user = SimpleNamespace(id=user_id, language_code="uk")
    chat = SimpleNamespace(id=1064175237)
    update = Mock()
    update.callback_query = query
    update.effective_user = user
    update.effective_chat = chat
    return update, query


def _fake_context():
    context = Mock()
    context.bot.send_message.return_value = SimpleNamespace(message_id=99)
    return context


class VwapExecutorButtonHandlerTest(unittest.TestCase):
    """Plan follow-up (2026-08-22): control panel with actual buttons
    (on/off/readonly-toggle/status), not typed commands - the buttons in
    get_vwap_executor_kb() dispatch through button_handler's "vwapexec"
    branch, tested here."""

    def setUp(self):
        patcher = patch.object(telegram_ui, "db")
        self.mock_db = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_db.is_admin_user.return_value = True
        self.mock_db.get_user_language.return_value = "uk"
        self.mock_db.get_vwap_executor_runtime_state.return_value = {
            "runtime_enabled": True, "read_only": False, "kill_switch_tripped": False,
            "kill_switch_reason": None, "kill_switch_cleared_at": None,
        }
        self.mock_db.count_open_vwap_trades.return_value = 0
        self.mock_db.get_consecutive_vwap_losses.return_value = 0
        self.mock_db.get_daily_vwap_pnl.return_value = 0.0

        bot_track_patcher = patch.object(telegram_ui, "bot_track_message")
        bot_track_patcher.start()
        self.addCleanup(bot_track_patcher.stop)

    def test_unauthorized_user_is_rejected_and_nothing_is_changed(self):
        self.mock_db.is_admin_user.return_value = False
        update, query = _fake_update(query_data="vwapexec_on")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        self.mock_db.set_vwap_executor_runtime_enabled.assert_not_called()

    def test_on_enables_runtime_and_clears_kill_switch(self):
        update, query = _fake_update(query_data="vwapexec_on")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        self.mock_db.set_vwap_executor_runtime_enabled.assert_called_once_with(True)
        self.mock_db.clear_vwap_executor_kill_switch.assert_called_once()

    def test_off_disables_runtime(self):
        update, query = _fake_update(query_data="vwapexec_off")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        self.mock_db.set_vwap_executor_runtime_enabled.assert_called_once_with(False)

    def test_readonly_toggles_from_current_state(self):
        self.mock_db.get_vwap_executor_runtime_state.return_value = {
            "runtime_enabled": True, "read_only": False, "kill_switch_tripped": False,
            "kill_switch_reason": None, "kill_switch_cleared_at": None,
        }
        update, query = _fake_update(query_data="vwapexec_readonly")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        self.mock_db.set_vwap_executor_read_only.assert_called_once_with(True)

    def test_status_refreshes_without_changing_anything(self):
        update, query = _fake_update(query_data="vwapexec_status")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        self.mock_db.set_vwap_executor_runtime_enabled.assert_not_called()
        self.mock_db.set_vwap_executor_read_only.assert_not_called()
        context.bot.send_message.assert_called_once()

    def test_unknown_subaction_is_ignored(self):
        update, query = _fake_update(query_data="vwapexec_bogus")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        context.bot.send_message.assert_not_called()

    def test_every_response_includes_the_control_keyboard(self):
        update, query = _fake_update(query_data="vwapexec_status")
        context = _fake_context()

        telegram_ui.button_handler(update, context)

        _, kwargs = context.bot.send_message.call_args
        self.assertIn("reply_markup", kwargs)


class GetVwapExecutorKbTest(unittest.TestCase):
    def test_reflects_read_only_state_in_the_button_label(self):
        kb_off = telegram_ui.get_vwap_executor_kb({"read_only": False})
        kb_on = telegram_ui.get_vwap_executor_kb({"read_only": True})

        label_off = kb_off.inline_keyboard[1][0].text
        label_on = kb_on.inline_keyboard[1][0].text
        self.assertNotEqual(label_off, label_on)

    def test_has_on_off_readonly_and_status_buttons(self):
        kb = telegram_ui.get_vwap_executor_kb({"read_only": False})
        callback_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertEqual(set(callback_data), {"vwapexec_on", "vwapexec_off", "vwapexec_readonly", "vwapexec_status"})


class GetMainMenuKbTest(unittest.TestCase):
    """2026-08-22: per explicit user request (no subscribers on this bot
    right now, so the earlier admin-only-menu caution doesn't apply),
    the VWAP executor controls are directly in the shared main menu, not
    behind a separate entry point - reuses get_vwap_executor_kb()'s own
    rows rather than a second definition of the same buttons."""

    def test_main_menu_includes_all_four_vwap_executor_buttons(self):
        with patch.object(telegram_ui.db, "get_vwap_executor_runtime_state", return_value={
            "runtime_enabled": True, "read_only": False, "kill_switch_tripped": False,
            "kill_switch_reason": None, "kill_switch_cleared_at": None,
        }), patch.object(telegram_ui.app_state, "get_scanner_state", return_value=True):
            kb = telegram_ui.get_main_menu_kb("uk")

        callback_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("vwapexec_on", callback_data)
        self.assertIn("vwapexec_off", callback_data)
        self.assertIn("vwapexec_readonly", callback_data)
        self.assertIn("vwapexec_status", callback_data)

    def test_main_menu_still_has_its_existing_buttons_too(self):
        with patch.object(telegram_ui.db, "get_vwap_executor_runtime_state", return_value={
            "runtime_enabled": True, "read_only": False, "kill_switch_tripped": False,
            "kill_switch_reason": None, "kill_switch_cleared_at": None,
        }), patch.object(telegram_ui.app_state, "get_scanner_state", return_value=True):
            kb = telegram_ui.get_main_menu_kb("uk")

        callback_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        self.assertIn("category_forex", callback_data)
        self.assertIn("toggle_scanner_forex", callback_data)


if __name__ == "__main__":
    unittest.main()

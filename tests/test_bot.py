import unittest
from unittest.mock import Mock, patch

import bot


class RegisterAdminCommandMenuTest(unittest.TestCase):
    """2026-08-22 fix: the VWAP-executor inline buttons only ever appeared
    attached to a command's own reply - there was no way to discover them
    in Telegram's UI without already knowing to type /vwap_executor_status
    by hand. This registers Telegram's native "/" command-menu button,
    scoped to ONLY the admin's chat (never the shared main menu every
    subscriber sees)."""

    def test_registers_commands_scoped_to_the_admin_chat(self):
        updater = Mock()
        with patch.object(bot, "DEV_USER_ID", 1064175237):
            bot._register_admin_command_menu(updater)

        updater.bot.set_my_commands.assert_called_once()
        _, kwargs = updater.bot.set_my_commands.call_args
        self.assertEqual(kwargs["scope"].chat_id, 1064175237)
        command_names = {c.command for c in kwargs["commands"]}
        self.assertEqual(
            command_names,
            {"vwap_executor_status", "vwap_executor_on", "vwap_executor_off", "vwap_executor_readonly"},
        )

    def test_does_nothing_when_no_admin_id_configured(self):
        updater = Mock()
        with patch.object(bot, "DEV_USER_ID", 0):
            bot._register_admin_command_menu(updater)
        updater.bot.set_my_commands.assert_not_called()

    def test_a_telegram_api_failure_does_not_propagate(self):
        updater = Mock()
        updater.bot.set_my_commands.side_effect = Exception("network error")
        with patch.object(bot, "DEV_USER_ID", 1064175237):
            bot._register_admin_command_menu(updater)  # must not raise


if __name__ == "__main__":
    unittest.main()

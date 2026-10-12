"""Explicit retirement gates; preserving history is not permission to trade."""
import os


def legacy_enabled():
    return os.getenv('LEGACY_SIGNAL_TEST_ENABLED','true').lower() in ('1','true','yes','on')


def paper_entries_enabled():
    return os.getenv('PAPER_STOP_ACCEPT_ENTRIES','true').lower() in ('1','true','yes','on')

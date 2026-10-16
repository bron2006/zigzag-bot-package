"""CI safety contract: temporary DB, no account credentials or order execution."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class CIEnvironmentTest(unittest.TestCase):
    def test_workflow_provides_temporary_database_and_disabled_order_executors(self):
        source=(ROOT/'.github/workflows/ci.yml').read_text('utf-8')
        for name,value in [('DATABASE_URL','sqlite:///:memory:'),
                           ('AUTOTRADE_ENABLED','false'),('BINOMO_EXECUTOR_ENABLED','false'),
                           ('AUTOTRADE_ACCOUNT_MODE','demo'),('BINOMO_ACCOUNT_MODE','demo')]:
            self.assertRegex(source,r'(?m)^      '+name+r": ['\"]"+re.escape(value)+r"['\"]$")
        self.assertNotIn('secrets.',source)
        self.assertIn('timeout-minutes: 10',source)
        self.assertIn('contents: read',source)

    def test_real_test_discovery_remains_enabled(self):
        source=(ROOT/'.github/workflows/ci.yml').read_text('utf-8')
        self.assertIn('python -m unittest discover -v',source)
        self.assertTrue((ROOT/'tests/__init__.py').is_file())
        self.assertNotIn('continue-on-error',source)


if __name__=='__main__':unittest.main()

"""Guard local credentials and order executors against cloud packaging."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CloudBuildTest(unittest.TestCase):
    def test_local_only_files_are_excluded(self):
        rules = set((ROOT / '.dockerignore').read_text(encoding='utf-8').splitlines())
        for rule in ('.env', '.env.*', '**/storage_state*.json', '.claude/',
                     'binomo_executor.py', 'vwap_executor.py', 'scripts/', 'logs/'):
            with self.subTest(rule=rule):
                self.assertIn(rule, rules)

    def test_full_build_checks_models_and_local_secrets(self):
        dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
        self.assertIn('FROM python:3.11-bookworm', dockerfile)
        self.assertIn('DATABASE_URL=sqlite:///:memory:', dockerfile)
        self.assertIn('AUTOTRADE_ENABLED=false', dockerfile)
        self.assertIn('BINOMO_EXECUTOR_ENABLED=false', dockerfile)
        self.assertIn('storage_state.json', dockerfile)
        self.assertIn('ml_models.load_models()', dockerfile)
        self.assertIn('predict_proba', dockerfile)

    def test_overlay_builds_remove_inherited_session(self):
        for name in ('Dockerfile.release', 'Dockerfile.hotfix'):
            with self.subTest(name=name):
                dockerfile = (ROOT / name).read_text(encoding='utf-8')
                self.assertIn('rm -f /app/storage_state.json /app/.env', dockerfile)
                self.assertIn('/app/binomo_executor.py /app/vwap_executor.py', dockerfile)


if __name__ == '__main__':
    unittest.main()

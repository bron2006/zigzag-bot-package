"""The central research index must remain navigable and not drop families."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


def registry():
    text=(ROOT/'CLAUDE.md').read_text('utf-8')
    return text.split('## Зведений реєстр стратегій і перевірок —',1)[1].split('\n## Контекст проєкту',1)[0]


class StrategyRegistryTests(unittest.TestCase):
    def test_unique_contiguous_ids_and_known_history(self):
        ids=re.findall(r'^\| (R\d{2,3}) \|',registry(),re.M)
        self.assertGreaterEqual(len(ids),45)
        self.assertEqual(ids,['R%02d'%n for n in range(1,len(ids)+1)])

    def test_referenced_source_documents_exist(self):
        refs=re.findall(r'`((?:research_[^`]+|local_trend_bot/[^`]+))`',registry())
        self.assertGreater(len(refs),50)
        # Generated JSON/cache evidence may legitimately be absent in a clean
        # checkout. Source protocols/findings, unlike those caches, must exist.
        missing=[ref for ref in refs if Path(ref).suffix in ('.md','.py') and not (ROOT/ref).is_file()]
        self.assertEqual(missing,[])

    def test_all_documented_research_directories_are_represented(self):
        refs=re.findall(r'`((?:research_[^`]+|local_trend_bot/[^`]+))`',registry())
        covered={ref.split('/')[0] for ref in refs}
        documented={p.name for p in ROOT.glob('research_*') if p.is_dir() and any(p.glob('*.md'))}
        self.assertEqual(sorted(documented-covered),[])


if __name__=='__main__':unittest.main()

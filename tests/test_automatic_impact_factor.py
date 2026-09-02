import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_DIR = (
    Path(__file__).resolve().parents[1]
    / "knowledge-base"
    / "system"
    / "zotero-sync"
)
sys.path.insert(0, str(MODULE_DIR))
SPEC = importlib.util.spec_from_file_location(
    "automatic_impact_factor", MODULE_DIR / "automatic_impact_factor.py"
)
assert SPEC and SPEC.loader
AUTOMATIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTOMATIC)


class AutomaticImpactFactorTest(unittest.TestCase):
    def test_metric_key_normalizes_issn(self):
        self.assertEqual(
            AUTOMATIC.metric_key({"ISSN": "1525-7797, 1526-4602"}),
            "issn:15257797",
        )

    def test_accepts_only_publisher_family_or_clarivate_url(self):
        self.assertTrue(
            AUTOMATIC.trusted_source_url(
                "https://www.sciencedirect.com/journal/example",
                ["linkinghub.elsevier.com"],
            )
        )
        self.assertTrue(
            AUTOMATIC.trusted_source_url(
                "https://clarivate.com/example",
                [],
            )
        )
        self.assertFalse(
            AUTOMATIC.trusted_source_url(
                "https://academic-accelerator.example/journal",
                ["linkinghub.elsevier.com"],
            )
        )

    def test_lookup_caches_verified_result(self):
        parent = {
            "data": {
                "publicationTitle": "Example Journal",
                "ISSN": "1234-5678",
                "url": "https://www.nature.com/example/article",
                "extra": "",
            }
        }
        payload = {
            "results": [
                {
                    "lookup_key": "issn:12345678",
                    "journal": "Example Journal",
                    "impact_factor": 4.9,
                    "impact_factor_year": "2025",
                    "source_url": "https://www.nature.com/example/",
                    "source_kind": "publisher",
                    "note": "Official journal metrics page",
                }
            ]
        }
        state = {}
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            AUTOMATIC, "run_codex_lookup", return_value=payload
        ) as lookup:
            resolved, changed = AUTOMATIC.refresh_automatic_impact_factors(
                config={"automatic_impact_factor": {"enabled": True}},
                vault=Path(directory),
                parents=[parent],
                state=state,
                logger=lambda _: None,
            )
        self.assertTrue(changed)
        self.assertEqual(resolved["issn:12345678"]["impact_factor"], 4.9)
        self.assertEqual(state["impact_factor_cache"]["issn:12345678"]["status"], "found")
        lookup.assert_called_once()

    def test_fresh_cache_skips_codex(self):
        checked = AUTOMATIC.now_iso()
        state = {
            "impact_factor_cache": {
                "issn:12345678": {
                    "schema_version": AUTOMATIC.CACHE_SCHEMA_VERSION,
                    "status": "found",
                    "checked_at": checked,
                    "impact_factor": 4.9,
                    "impact_factor_year": "2025",
                    "impact_factor_source": "https://www.nature.com/example/",
                    "impact_factor_retrieved_at": checked,
                }
            }
        }
        parent = {
            "data": {
                "publicationTitle": "Example Journal",
                "ISSN": "1234-5678",
                "url": "https://www.nature.com/example/article",
                "extra": "",
            }
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            AUTOMATIC, "run_codex_lookup"
        ) as lookup:
            resolved, changed = AUTOMATIC.refresh_automatic_impact_factors(
                config={"automatic_impact_factor": {"enabled": True}},
                vault=Path(directory),
                parents=[parent],
                state=state,
                logger=lambda _: None,
            )
        self.assertFalse(changed)
        self.assertEqual(resolved["issn:12345678"]["impact_factor"], 4.9)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()

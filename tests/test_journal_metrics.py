import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge-base"
    / "system"
    / "zotero-sync"
    / "journal_metrics.py"
)
SPEC = importlib.util.spec_from_file_location("journal_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)


class JournalMetricsTest(unittest.TestCase):
    def test_reads_impact_factor_year_and_source_from_zotero_extra(self):
        result = METRICS.resolve_journal_metrics(
            {
                "publicationTitle": "Biomacromolecules",
                "ISSN": "1525-7797",
                "extra": (
                    "Impact Factor: 5.5\n"
                    "Impact Factor Year: 2024\n"
                    "Impact Factor Source: Journal Citation Reports"
                ),
            }
        )
        self.assertEqual(result["impact_factor"], 5.5)
        self.assertEqual(result["impact_factor_year"], "2024")
        self.assertEqual(result["impact_factor_source"], "Journal Citation Reports")

    def test_accepts_year_in_metric_label(self):
        result = METRICS.impact_factor_from_extra("JIF 2024: 9.8")
        self.assertEqual(result["impact_factor"], 9.8)
        self.assertEqual(result["impact_factor_year"], "2024")

    def test_does_not_substitute_five_year_impact_factor(self):
        self.assertIsNone(METRICS.impact_factor_from_extra("5-year Impact Factor: 12.3"))

    def test_uses_catalog_by_journal_or_issn(self):
        parent = {"publicationTitle": "Example Journal", "ISSN": "1234-5678", "extra": ""}
        result = METRICS.resolve_journal_metrics(
            parent,
            {
                "12345678": {
                    "impact_factor": 4.2,
                    "year": "2025",
                    "source": "Journal Citation Reports",
                }
            },
        )
        self.assertEqual(result["impact_factor"], 4.2)
        self.assertEqual(result["impact_factor_year"], "2025")

    def test_matches_one_of_multiple_issns_without_treating_titles_as_issns(self):
        parent = {
            "publicationTitle": "Example Journal",
            "ISSN": "1525-7797, 1526-4602",
            "extra": "",
        }
        result = METRICS.resolve_journal_metrics(
            parent,
            {"15264602": {"impact_factor": 5.5, "year": "2024"}},
        )
        self.assertEqual(result["impact_factor"], 5.5)
        self.assertEqual(METRICS.normalize_issn("Example Journal"), "")

    def test_returns_explicit_missing_values(self):
        result = METRICS.resolve_journal_metrics({"publicationTitle": "Unknown"})
        self.assertIsNone(result["impact_factor"])
        self.assertEqual(result["impact_factor_year"], "")
        self.assertEqual(result["impact_factor_source"], "")


if __name__ == "__main__":
    unittest.main()

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge-base"
    / "system"
    / "knowledge"
    / "run_pipeline.py"
)
SPEC = importlib.util.spec_from_file_location("run_pipeline", MODULE_PATH)
assert SPEC and SPEC.loader
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class PipelineImpactFactorTest(unittest.TestCase):
    def test_backfills_existing_paper_note(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "paper.md"
            note.write_text(
                "---\ntype: paper\nyear: \"2024\"\nreviewed: false\n---\n\n# Paper\n",
                encoding="utf-8",
            )
            changed = PIPELINE.sync_paper_metadata_frontmatter(
                note,
                {
                    "journal": "Biomacromolecules",
                    "issn": "1525-7797",
                    "impact_factor": 5.5,
                    "impact_factor_year": "2024",
                    "impact_factor_source": "Journal Citation Reports",
                    "impact_factor_retrieved_at": "2026-09-02T12:00:00+08:00",
                },
            )
            text = note.read_text(encoding="utf-8")
            self.assertTrue(changed)
            self.assertIn('journal: "Biomacromolecules"', text)
            self.assertIn("impact_factor: 5.5", text)
            self.assertIn('impact_factor_retrieved_at: "2026-09-02T12:00:00+08:00"', text)
            self.assertTrue(text.endswith("\n# Paper\n"))

    def test_preserves_manual_value_when_upstream_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "paper.md"
            original = """---
type: paper
year: "2024"
impact_factor: 7.1
impact_factor_year: "2025"
impact_factor_source: "Manual verification"
impact_factor_retrieved_at: "2026-09-02T12:00:00+08:00"
---
"""
            note.write_text(original, encoding="utf-8")
            changed = PIPELINE.sync_paper_metadata_frontmatter(
                note,
                {
                    "impact_factor": None,
                    "impact_factor_year": "",
                    "impact_factor_source": "",
                    "impact_factor_retrieved_at": "",
                },
            )
            self.assertTrue(changed)  # Missing journal and ISSN are added as null.
            text = note.read_text(encoding="utf-8")
            self.assertIn("impact_factor: 7.1", text)
            self.assertIn('impact_factor_source: "Manual verification"', text)

    def test_accepts_matching_values(self):
        note = """---
impact_factor: 5.5
impact_factor_year: "2024"
impact_factor_source: "Journal Citation Reports"
impact_factor_retrieved_at: "2026-09-02T12:00:00+08:00"
---
"""
        PIPELINE.validate_impact_factor_properties(
            note,
            {
                "impact_factor": 5.5,
                "impact_factor_year": "2024",
                "impact_factor_source": "Journal Citation Reports",
                "impact_factor_retrieved_at": "2026-09-02T12:00:00+08:00",
            },
        )

    def test_accepts_explicit_null_values(self):
        note = """---
impact_factor: null
impact_factor_year: null
impact_factor_source: null
impact_factor_retrieved_at: null
---
"""
        PIPELINE.validate_impact_factor_properties(note, {"impact_factor": None})

    def test_rejects_invented_value(self):
        note = """---
impact_factor: 8.8
impact_factor_year: "2025"
impact_factor_source: "unknown"
impact_factor_retrieved_at: "2026-09-02T12:00:00+08:00"
---
"""
        with self.assertRaisesRegex(RuntimeError, "invented an impact factor"):
            PIPELINE.validate_impact_factor_properties(note, {"impact_factor": None})

    def test_requires_all_properties(self):
        with self.assertRaisesRegex(RuntimeError, "missing properties"):
            PIPELINE.validate_impact_factor_properties(
                "---\nimpact_factor: null\n---\n",
                {"impact_factor": None},
            )


if __name__ == "__main__":
    unittest.main()

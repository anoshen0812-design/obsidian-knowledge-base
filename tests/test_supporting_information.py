import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge-base"
    / "system"
    / "zotero-sync"
    / "supporting_information.py"
)
SPEC = importlib.util.spec_from_file_location("supporting_information", MODULE_PATH)
assert SPEC and SPEC.loader
SI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SI)


class SupportingInformationTest(unittest.TestCase):
    def test_normalizes_doi_urls(self):
        self.assertEqual(
            SI.normalize_doi("https://doi.org/10.1021/ACS.BIOMAC.4C00431"),
            "10.1021/acs.biomac.4c00431",
        )
        self.assertEqual(SI.normalize_doi("not a DOI"), "")

    def test_classifies_zotero_si_without_misclassifying_main_pdf(self):
        supporting = {
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "filename": "bm4c00431_si_001.pdf",
                "title": "Supporting Information",
            }
        }
        primary = {
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "filename": "paper.pdf",
                "title": "Full Text PDF",
            }
        }
        self.assertTrue(SI.is_supplementary_pdf_attachment(supporting))
        self.assertFalse(SI.is_supplementary_pdf_attachment(primary))

    def test_rejects_peer_review_pdf(self):
        self.assertLess(
            SI.candidate_score(
                "https://publisher.example/MOESM2_ESM.pdf",
                "Transparent Peer Review file (download PDF)",
            ),
            0,
        )

    def test_excludes_peer_review_attachment_from_primary_papers(self):
        peer_review = {
            "data": {
                "itemType": "attachment",
                "contentType": "application/pdf",
                "filename": "MOESM2_ESM.pdf",
                "title": "Transparent Peer Review file",
            }
        }
        self.assertFalse(SI.is_supplementary_pdf_attachment(peer_review))
        self.assertTrue(SI.is_auxiliary_pdf_attachment(peer_review))

    def test_accepts_explicit_supplementary_pdf(self):
        self.assertGreaterEqual(
            SI.candidate_score(
                "https://publisher.example/MOESM1_ESM.pdf",
                "Supplementary Information (download PDF)",
            ),
            8,
        )


if __name__ == "__main__":
    unittest.main()

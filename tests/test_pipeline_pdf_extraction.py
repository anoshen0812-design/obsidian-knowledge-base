import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge-base"
    / "system"
    / "knowledge"
    / "run_pipeline.py"
)
SPEC = importlib.util.spec_from_file_location("run_pipeline_pdf", MODULE_PATH)
assert SPEC and SPEC.loader
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class PipelinePdfExtractionTest(unittest.TestCase):
    def make_fixture(self, directory):
        vault = Path(directory)
        source = vault / "sources" / "literature" / "pdf" / "paper.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"%PDF-test")
        task = {
            "attachment_key": "ABC123",
            "extract_path": "extracts/papers/ABC123.md",
            "sha256": "a" * 64,
            "source_path": str(source.relative_to(vault)),
            "title": "Test paper",
        }
        config = {
            "mineru_backend": "pipeline",
            "mineru_fallback_to_pdftotext": True,
            "mineru_formula": True,
            "mineru_method": "auto",
            "mineru_path": "/test/mineru",
            "mineru_table": True,
            "minimum_extracted_characters": 1,
            "pdf_extractor": "mineru",
            "pdftotext_path": "/test/pdftotext",
            "vault": vault,
        }
        return config, task

    def test_mineru_rebuilds_page_markdown_and_copies_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            config, task = self.make_fixture(directory)

            def fake_run(command, **kwargs):
                self.assertEqual(command[0], config["mineru_path"])
                output_root = Path(command[command.index("-o") + 1])
                parse_dir = output_root / "paper" / "auto"
                image = parse_dir / "images" / "figure.jpg"
                image.parent.mkdir(parents=True)
                image.write_bytes(b"figure")
                content = [
                    {"type": "header", "text": "Journal header", "page_idx": 0},
                    {"type": "text", "text": "Introduction", "text_level": 1, "page_idx": 0},
                    {"type": "text", "text": "First-page evidence.", "page_idx": 0},
                    {"type": "equation", "text": "E = mc^2", "page_idx": 1},
                    {
                        "type": "table",
                        "table_caption": ["Table 1"],
                        "table_body": "<table><tr><td>42</td></tr></table>",
                        "img_path": "images/figure.jpg",
                        "page_idx": 1,
                    },
                ]
                (parse_dir / "paper_content_list.json").write_text(
                    json.dumps(content), encoding="utf-8"
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_run):
                destination = PIPELINE.extract_pdf(config, task)

            markdown = destination.read_text(encoding="utf-8")
            self.assertIn("extractor: mineru", markdown)
            self.assertIn("extractor_signature: mineru:pipeline:auto:v1", markdown)
            self.assertIn("## Page 1", markdown)
            self.assertIn("### Introduction", markdown)
            self.assertIn("## Page 2", markdown)
            self.assertIn("$$\nE = mc^2\n$$", markdown)
            self.assertIn("<table><tr><td>42</td></tr></table>", markdown)
            self.assertNotIn("Journal header", markdown)
            asset = (
                config["vault"]
                / "extracts"
                / "papers"
                / "assets"
                / "ABC123"
                / ("a" * 12)
                / "figure.jpg"
            )
            self.assertTrue(asset.is_file())
            self.assertIn(asset.relative_to(config["vault"]).as_posix(), markdown)

    def test_mineru_failure_falls_back_to_pdftotext(self):
        with tempfile.TemporaryDirectory() as directory:
            config, task = self.make_fixture(directory)

            def fake_run(command, **kwargs):
                if command[0] == config["mineru_path"]:
                    return subprocess.CompletedProcess(command, 1, "", "model unavailable")
                Path(command[-1]).write_text("Page one\fPage two", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(PIPELINE.subprocess, "run", side_effect=fake_run):
                destination = PIPELINE.extract_pdf(config, task)

            markdown = destination.read_text(encoding="utf-8")
            self.assertIn("extractor: pdftotext", markdown)
            self.assertIn("## Page 1\n\nPage one", markdown)
            self.assertIn("## Page 2\n\nPage two", markdown)

    def test_mineru_failure_can_disable_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            config, task = self.make_fixture(directory)
            config["mineru_fallback_to_pdftotext"] = False
            failure = subprocess.CompletedProcess([], 1, "", "model unavailable")
            with mock.patch.object(PIPELINE.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "model unavailable"):
                    PIPELINE.extract_pdf(config, task)

    def test_rejects_asset_path_outside_mineru_output(self):
        with tempfile.TemporaryDirectory() as directory:
            config, task = self.make_fixture(directory)
            parse_dir = Path(directory) / "mineru-output"
            parse_dir.mkdir()
            with self.assertRaisesRegex(RuntimeError, "escaped"):
                PIPELINE.safe_mineru_asset(config, task, parse_dir, "../secret.png")


if __name__ == "__main__":
    unittest.main()

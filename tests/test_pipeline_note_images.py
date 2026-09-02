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
SPEC = importlib.util.spec_from_file_location("run_pipeline_images", MODULE_PATH)
assert SPEC and SPEC.loader
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class PipelineNoteImagesTest(unittest.TestCase):
    def make_task(self):
        return PIPELINE.paper_note_identity(
            {"title": "A paper with figures", "creators": ["First Author"]},
            "2026-09-02",
        )

    def test_identity_assigns_one_exact_note_specific_image_directory(self):
        task = self.make_task()
        note_stem = Path(task["note_path"]).stem
        self.assertEqual(task["images_dir"], f"wiki/papers/images/{note_stem}")
        self.assertEqual(task["image_asset_subdir"], f"images/{note_stem}")

    def test_existing_note_image_identity_uses_the_existing_note_stem(self):
        note_path = "wiki/papers/2026-08-26 - First Author - Existing title.md"
        identity = PIPELINE.paper_image_identity(note_path)
        self.assertEqual(
            identity["images_dir"],
            "wiki/papers/images/2026-08-26 - First Author - Existing title",
        )
        self.assertEqual(
            identity["image_asset_subdir"],
            "images/2026-08-26 - First Author - Existing title",
        )

    def test_image_contract_accepts_own_existing_obsidian_embed(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            task = self.make_task()
            config = {"vault": vault}
            image_dir = PIPELINE.paper_images_dir(config, task, create=True)
            image = image_dir / "fig-01-mechanism.png"
            image.write_bytes(b"png")
            note_text = (
                "---\n"
                f'images_dir: "{task["images_dir"]}"\n'
                "---\n\n"
                f'![[{task["images_dir"]}/{image.name}]]\n'
            )
            PIPELINE.validate_paper_image_contract(config, task, note_text)

    def test_image_contract_rejects_another_papers_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            task = self.make_task()
            config = {"vault": vault}
            PIPELINE.paper_images_dir(config, task, create=True)
            note_text = (
                "---\n"
                f'images_dir: "{task["images_dir"]}"\n'
                "---\n\n"
                "![[wiki/papers/images/another-paper/fig-01.png]]\n"
            )
            with self.assertRaisesRegex(RuntimeError, "another paper"):
                PIPELINE.validate_paper_image_contract(config, task, note_text)

    def test_image_contract_rejects_missing_managed_image(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            task = self.make_task()
            config = {"vault": vault}
            PIPELINE.paper_images_dir(config, task, create=True)
            note_text = (
                "---\n"
                f'images_dir: "{task["images_dir"]}"\n'
                "---\n\n"
                f'![[{task["images_dir"]}/missing.png]]\n'
            )
            with self.assertRaisesRegex(RuntimeError, "missing managed image"):
                PIPELINE.validate_paper_image_contract(config, task, note_text)


if __name__ == "__main__":
    unittest.main()

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
SPEC = importlib.util.spec_from_file_location("run_pipeline_paragraph_reading", MODULE_PATH)
assert SPEC and SPEC.loader
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class PipelineParagraphReadingTest(unittest.TestCase):
    def make_task(self):
        task = PIPELINE.paper_note_identity(
            {"title": "A valuable paper", "creators": ["First Author"]},
            "2026-09-02",
        )
        task.update(PIPELINE.paper_paragraph_reading_identity(task["note_path"]))
        task["paragraph_reading_figures"] = False
        return task

    def test_companion_uses_separate_directory_and_same_filename(self):
        task = self.make_task()
        self.assertEqual(
            task["paragraph_reading_note_path"],
            f"wiki/papers/close-reading/{Path(task['note_path']).name}",
        )

    def test_controls_are_added_without_overwriting_human_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "paper.md"
            note.write_text(
                "---\n"
                "type: paper\n"
                "paragraph_reading: true\n"
                "paragraph_reading_status: partial\n"
                "---\n\n# Paper\n",
                encoding="utf-8",
            )
            self.assertTrue(PIPELINE.ensure_paper_reading_controls(note))
            values = PIPELINE.yaml_frontmatter_scalars(note.read_text(encoding="utf-8"))
            self.assertTrue(PIPELINE.yaml_boolean(values["paragraph_reading"]))
            self.assertEqual(
                PIPELINE.unquote_yaml_scalar(values["paragraph_reading_status"]),
                "partial",
            )
            self.assertIn("paragraph_reading_figures", values)
            self.assertIn("paragraph_reading_note", values)

    def test_start_requires_human_checkbox(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "paper.md"
            note.write_text(
                "---\ntype: paper\nparagraph_reading: false\n"
                "paragraph_reading_figures: false\n---\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "not checked"):
                PIPELINE.paragraph_reading_preferences(note)

    def test_mode_a_note_accepts_no_images_when_figures_are_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            task = self.make_task()
            PIPELINE.paper_images_dir({"vault": vault}, task, create=True)
            text = (
                "---\n"
                "type: paper-paragraph-reading\n"
                "status: draft\n"
                "reading_mode: A\n"
                f'source_note: "[[{task["note_path"]}]]"\n'
                f'images_dir: "{task["images_dir"]}"\n'
                "include_figures: false\n"
                "paragraph_reading_progress: partial\n"
                "---\n\n"
                f"# {task['display_title']}：逐段精读\n\n"
                "## 逐段精读\n\n#### PDF p.1 · ¶1\n\n> Source paragraph\n"
            )
            self.assertEqual(
                PIPELINE.validate_paragraph_reading_note({"vault": vault}, task, text),
                "partial",
            )

    def test_mode_a_note_rejects_images_when_figures_are_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            task = self.make_task()
            image_dir = PIPELINE.paper_images_dir({"vault": vault}, task, create=True)
            (image_dir / "fig-01.png").write_bytes(b"png")
            text = (
                "---\n"
                "type: paper-paragraph-reading\nstatus: draft\nreading_mode: A\n"
                f'source_note: "[[{task["note_path"]}]]"\n'
                f'images_dir: "{task["images_dir"]}"\n'
                "include_figures: false\nparagraph_reading_progress: complete\n---\n\n"
                f"# {task['display_title']}：逐段精读\n\n## 逐段精读\n\n"
                "> Source paragraph\n\n"
                f"![[{task['images_dir']}/fig-01.png]]\n"
            )
            with self.assertRaisesRegex(RuntimeError, "embedded figures"):
                PIPELINE.validate_paragraph_reading_note({"vault": vault}, task, text)

    def test_human_selected_note_runs_mode_a_without_changing_main_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            task = self.make_task()
            task.update(
                {
                    "id": "paper:ATTACH:0123456789abcdef",
                    "kind": "paper",
                    "status": "drafted",
                    "source_path": "sources/literature/pdf/paper.pdf",
                    "extract_path": "extracts/papers/ATTACH.md",
                    "title": "A valuable paper",
                }
            )
            source = vault / task["source_path"]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"paper pdf")
            task["sha256"] = PIPELINE.file_sha256(source)
            extract = vault / task["extract_path"]
            extract.parent.mkdir(parents=True)
            extract.write_text("## Page 1\n\nSource paragraph", encoding="utf-8")
            main_note = vault / task["note_path"]
            main_note.parent.mkdir(parents=True)
            main_note.write_text(
                "---\ntype: paper\nstatus: draft\nparagraph_reading: true\n"
                "paragraph_reading_figures: false\n"
                "paragraph_reading_status: not_requested\n"
                "paragraph_reading_note: null\n---\n\n# Main\n",
                encoding="utf-8",
            )
            queue = {"schema_version": 1, "items": [task]}
            queue_file = vault / "system/queue/pending.json"
            queue_file.parent.mkdir(parents=True)
            queue_file.write_text(json.dumps(queue), encoding="utf-8")

            def fake_codex(*_args, **_kwargs):
                companion = vault / task["paragraph_reading_note_path"]
                companion.parent.mkdir(parents=True)
                companion.write_text(
                    "---\ntype: paper-paragraph-reading\nstatus: draft\nreading_mode: A\n"
                    f'source_note: "[[{task["note_path"]}]]"\n'
                    f'images_dir: "{task["images_dir"]}"\n'
                    "include_figures: false\nparagraph_reading_progress: complete\n---\n\n"
                    f"# {task['display_title']}：逐段精读\n\n## 逐段精读\n\n"
                    "> Source paragraph\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess([], 0, stdout="ok", stderr="")

            config = {"vault": vault, "paragraph_reading_timeout_seconds": 30}
            with mock.patch.object(
                PIPELINE, "ensure_paragraph_reading_skill", return_value="paper-reading"
            ), mock.patch.object(PIPELINE, "extract_pdf", return_value=extract), mock.patch.object(
                PIPELINE, "codex_command", side_effect=fake_codex
            ):
                self.assertEqual(PIPELINE.paragraph_read_paper(config, task["note_path"]), 0)

            main_values = PIPELINE.yaml_frontmatter_scalars(
                main_note.read_text(encoding="utf-8")
            )
            self.assertEqual(
                PIPELINE.unquote_yaml_scalar(main_values["paragraph_reading_status"]),
                "completed",
            )
            saved_task = json.loads(queue_file.read_text(encoding="utf-8"))["items"][0]
            self.assertEqual(saved_task["status"], "drafted")
            self.assertEqual(saved_task["paragraph_reading_status"], "completed")


if __name__ == "__main__":
    unittest.main()

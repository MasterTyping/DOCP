"""Run with: python -m unittest test_server"""
import tempfile
import unittest
from pathlib import Path

import pymupdf

import server


class Documents(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.docs = self.root / "rag"
        self.docs.mkdir()
        original, server.PDF_DIR = server.PDF_DIR, str(self.docs)
        self.addCleanup(setattr, server, "PDF_DIR", original)

    def test_markdown_toc_skips_code_and_tracks_pages(self):
        lines = ["# 제목", "```bash", "# not a heading", "```"] + ["본문"] * 96 + ["## 둘째 ##", "안전 기준"]
        (self.docs / "a.md").write_text("\n".join(lines), encoding="utf-8")
        info = server.get_pdf_info("a.md")
        self.assertEqual(info["page_count"], 2)
        self.assertEqual(info["toc"], [{"level": 1, "title": "제목", "page": 1}, {"level": 2, "title": "둘째", "page": 2}])
        self.assertEqual(server.search_pdf("a.md", "안전   기준")["results"][0]["page"], 2)
        self.assertEqual(server.read_pdf_pages("a.md", 2, 2)["pages"][0]["text"], "## 둘째 ##\n안전 기준")
        with self.assertRaises(ValueError):
            server.read_pdf_pages("a.md", 3, 3)

    def test_empty_markdown_has_one_empty_page(self):
        (self.docs / "e.md").write_text("")
        self.assertEqual(server.get_pdf_info("e.md")["page_count"], 1)
        self.assertEqual(server.read_pdf_pages("e.md", 1, 1)["pages"][0]["text"], "")

    def test_markdown_outside_folder_and_non_utf8_are_rejected(self):
        (self.root / "secret.md").write_text("secret")
        (self.docs / "link.md").symlink_to(self.root / "secret.md")
        (self.docs / "bad.md").write_bytes(b"\xff\xfe\x00")
        for name in ("../secret.md", str(self.root / "secret.md"), "link.md", "bad.md"):
            with self.assertRaises(ValueError):
                server.search_pdf(name, "secret")

    def test_pdf_still_works(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "hello pdf")
        doc.save(self.docs / "a.pdf")
        doc.close()
        self.assertEqual(server.get_pdf_info("a.pdf")["page_count"], 1)
        self.assertEqual(server.search_pdf("a.pdf", "hello")["results"][0]["page"], 1)
        self.assertIn("hello pdf", server.read_pdf_pages("a.pdf", 1, 1)["pages"][0]["text"])


if __name__ == "__main__":
    unittest.main()

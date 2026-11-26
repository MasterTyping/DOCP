"""Run from the repo root: python -m unittest src.test_server"""
import asyncio
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import pymupdf

# server imports doc_export as a top-level module, as it is when installed.
sys.path.insert(0, str(Path(__file__).parent))

import doc_export  # noqa: E402
import src.server as server  # noqa: E402


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

    def test_resources_list_only_folder_documents_and_attach_outline(self):
        (self.root / "secret.md").write_text("secret")
        (self.docs / "link.md").symlink_to(self.root / "secret.md")
        (self.docs / ".hidden").mkdir()
        (self.docs / ".hidden" / "h.md").write_text("h")
        (self.docs / "note.txt").write_text("n")
        (self.docs / "sub").mkdir()
        (self.docs / "sub" / "한글 문서.md").write_text("# 제목\n본문 비밀값\n", encoding="utf-8")
        listed = asyncio.run(server.mcp.list_resources())
        self.assertEqual([r.name for r in listed], ["sub/한글 문서.md"])
        content = asyncio.run(server.mcp.read_resource(str(listed[0].uri)))[0].content
        self.assertIn("제목", content)
        self.assertNotIn("비밀값", content)
        for uri in ("doc://rag/../secret.md", "doc://rag/%2E%2E/secret.md", "doc://rag/" + str(self.root / "secret.md")):
            with self.assertRaises(ValueError):
                asyncio.run(server.mcp.read_resource(uri))

    def test_folder_scope_limits_documents_and_search(self):
        (self.root / "secret.md").write_text("안전")
        for name in ("법규/a.md", "법규/세부/b.md", "매뉴얼/c.md"):
            (self.docs / name).parent.mkdir(parents=True, exist_ok=True)
            (self.docs / name).write_text("안전 기준", encoding="utf-8")
        (self.docs / "법규/bad.md").write_bytes(b"\xff\xfe\x00")
        self.assertEqual(server.list_documents("법규")["documents"], ["법규/a.md", "법규/bad.md", "법규/세부/b.md"])
        self.assertEqual(len(server.list_documents()["documents"]), 4)
        found = server.search_folder("법규", "안전", 50)
        self.assertEqual([r["file_path"] for r in found["results"]], ["법규/a.md", "법규/세부/b.md"])
        self.assertEqual([s["file_path"] for s in found["skipped"]], ["법규/bad.md"])
        self.assertFalse(found["truncated"])
        limited = server.search_folder("법규", "안전", 1)
        self.assertEqual(len(limited["results"]), 1)
        self.assertTrue(limited["truncated"])
        for folder in ("..", str(self.root), "없는폴더", "법규/a.md"):
            with self.assertRaises(ValueError):
                server.list_documents(folder)
            with self.assertRaises(ValueError):
                server.search_folder(folder, "안전")
        with self.assertRaises(ValueError):
            server.search_folder("법규", "   ")

    def test_pdf_still_works(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "hello pdf")
        doc.save(self.docs / "a.pdf")
        doc.close()
        self.assertEqual(server.get_pdf_info("a.pdf")["page_count"], 1)
        self.assertEqual(server.search_pdf("a.pdf", "hello")["results"][0]["page"], 1)
        self.assertIn("hello pdf", server.read_pdf_pages("a.pdf", 1, 1)["pages"][0]["text"])

    def test_pdf_outside_folder_is_rejected(self):
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "secret")
        doc.save(self.root / "secret.pdf")
        doc.close()
        for name in ("../secret.pdf", str(self.root / "secret.pdf")):
            with self.assertRaises(ValueError):
                server.get_pdf_info(name)

    def test_search_falls_back_to_all_words_and_ranks_documents(self):
        (self.docs / "a.md").write_text("안전의 관리 기준", encoding="utf-8")
        found = server.search_pdf("a.md", "안전 관리")
        self.assertEqual((found["mode"], found["results"][0]["page"]), ("all_words", 1))
        (self.docs / "b.md").write_text("안전 관리\n안전 관리\n안전 관리", encoding="utf-8")
        ranked = server.search_folder("", "안전 관리", 2)
        self.assertEqual(ranked["mode"], "phrase")
        self.assertEqual([r["file_path"] for r in ranked["results"]], ["b.md", "b.md"])
        self.assertTrue(ranked["truncated"])

    def test_read_is_capped_by_characters(self):
        (self.docs / "big.md").write_text("\n".join(["가" * 500] * 100), encoding="utf-8")
        read = server.read_pdf_pages("big.md", 1, 1)
        self.assertTrue(read["truncated"])
        self.assertEqual(len(read["pages"][0]["text"]), server.MAX_READ_CHARS)

    def test_scanned_pdf_is_flagged(self):
        doc = pymupdf.open()
        doc.new_page()
        doc.save(self.docs / "scan.pdf")
        doc.close()
        info = server.get_pdf_info("scan.pdf")
        self.assertEqual(info["pages_without_text"], 1)
        self.assertIn("warning", info)

    def test_skim_modes(self):
        lines = ["# 개요", "개요 본문"] + ["x"] * 98 + ["# 결론", "결론 본문 핵심"]
        (self.docs / "s.md").write_text("\n".join(lines), encoding="utf-8")
        toc = server.skim_document("s.md")
        self.assertEqual(toc["mode"], "toc")
        self.assertEqual([(e["page"], e["title"]) for e in toc["excerpts"]], [(1, "개요"), (2, "결론")])
        self.assertTrue(toc["excerpts"][1]["text"].startswith("결론 결론 본문 핵심"))
        hit = server.skim_document("s.md", query="핵심")
        self.assertEqual((hit["mode"], [e["page"] for e in hit["excerpts"]]), ("query", [2]))
        (self.docs / "plain.md").write_text("본문만 있음", encoding="utf-8")
        self.assertEqual(server.skim_document("plain.md")["mode"], "pages")

    def test_notion_export_saves_backup_and_requires_login_steps(self):
        out = self.root / "exports"
        with unittest.mock.patch.dict("os.environ", {"PDF_RAG_OUT": str(out)}):
            res = server.export_document("# 제목\n본문", "notion", "회의록")
        self.assertEqual(Path(res["saved_markdown"]).read_text(encoding="utf-8"), "# 제목\n본문")
        self.assertIn("/mcp", res["login_guide"])
        self.assertTrue(any("stop" in step for step in res["next_steps"]))


class Export(unittest.TestCase):
    MD = "# 보고서\n\n## 요약\n\n- 첫째 **항목**\n- 둘째\n\n| 구분 | 값 |\n|---|---|\n| 안전 | 3 |\n\n```\ncode\n```\n"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_every_format_and_no_overwrite(self):
        from docx import Document
        from pptx import Presentation

        for fmt in ("md", "html", "pdf", "docx", "pptx"):
            path = doc_export.export(self.MD, fmt, self.out, "../보고서.txt")
            self.assertEqual(path, (self.out / f"보고서.{fmt}").resolve())
        self.assertIn("<h2>요약</h2>", (self.out / "보고서.html").read_text(encoding="utf-8"))
        with pymupdf.open(self.out / "보고서.pdf") as pdf:
            self.assertIn("첫째 항목", pdf[0].get_text())
        docx = Document(self.out / "보고서.docx")
        self.assertEqual([p.text for p in docx.paragraphs][:3], ["보고서", "요약", "첫째 항목"])
        self.assertEqual(docx.tables[0].cell(1, 0).text, "안전")
        slides = Presentation(self.out / "보고서.pptx").slides
        self.assertEqual([s.shapes.title.text for s in slides], ["보고서", "요약"])
        self.assertEqual(doc_export.export("x", "md", self.out, "보고서").name, "보고서-1.md")
        with self.assertRaises(ValueError):
            doc_export.export("x", "exe", self.out, "a")


if __name__ == "__main__":
    unittest.main()

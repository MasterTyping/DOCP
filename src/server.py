"""Local PDF and Markdown search MCP server (stdio). stdout is reserved for the protocol."""
import json
import logging
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote

import pymupdf
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource, ToolAnnotations

import doc_export

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
# MuPDF writes warnings to stdout by default, which would corrupt the MCP stream.
pymupdf.set_messages(stream=sys.stderr)

MAX_PAGES_PER_READ = 5
MAX_SEARCH_RESULTS = 50
SNIPPET_RADIUS = 100
# 5 pages of dense tables can still flood the context, so cap characters too.
MAX_READ_CHARS = 40_000
READ_ONLY = ToolAnnotations(readOnlyHint=True)
# Markdown has no pages, so fixed line blocks give the page-based tools stable numbers.
MD_LINES_PER_PAGE = 100
MD_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)$")
MD_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")

DOC_URI = "doc://rag/"
MAX_LISTED_DOCS = 500

PDF_DIR = os.environ.get("PDF_RAG_DIR")


def _documents(subfolder: str = "") -> list[Path]:
    """Return documents under a subfolder of the registered folder, relative to the registered folder."""
    if not PDF_DIR:
        return []
    root, docs = Path(PDF_DIR).resolve(), []
    start = (root / Path(subfolder).expanduser()).resolve()
    if not start.is_dir() or not start.is_relative_to(root):
        raise ValueError(f"Folder not found inside the document folder: {subfolder}. Paths are relative to the document folder itself, e.g. 'manual.pdf' or 'sub/a.md'; use '' for all documents.")
    for folder, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "node_modules")
        for name in sorted(files):
            path = Path(folder) / name
            if (
                path.suffix.lower() in (".pdf", ".md")
                and not name.startswith(".")
                and path.is_file()
                and path.resolve().is_relative_to(root)  # A symlink must not reveal outside files.
            ):
                docs.append(path.relative_to(root))
                if len(docs) == MAX_LISTED_DOCS:  # shortcut: later files are not suggested, paginate if a folder exceeds this
                    return docs
    return docs


class DocServer(FastMCP):
    """Expose documents as resources, which Claude Code offers in @ autocomplete."""

    async def list_resources(self) -> list[Resource]:
        return [
            Resource(
                uri=DOC_URI + quote(doc.as_posix()),
                name=doc.as_posix(),
                description=doc.as_posix(),  # The menu percent-encodes non-ASCII URIs, so show the real name here.
                mimeType="text/plain",
            )
            for doc in _documents()
        ]

    async def read_resource(self, uri) -> list[ReadResourceContents]:
        if not str(uri).startswith(DOC_URI):
            return list(await super().read_resource(uri))
        name = unquote(str(uri)[len(DOC_URI):])
        if not PDF_DIR:
            raise ValueError("No document folder is registered")
        # Only the outline: attaching a whole PDF to the prompt could exhaust the context.
        text = (
            f"Use search_pdf and read_pdf_pages with file_path={json.dumps(name, ensure_ascii=False)} to read this document.\n"
            + json.dumps(get_pdf_info(name), ensure_ascii=False, indent=2)
        )
        return [ReadResourceContents(content=text, mime_type="text/plain")]


mcp = DocServer(
    "pdf-rag",
    instructions=(
        f"Default document folder: {PDF_DIR}. Tools read .pdf and .md files. Relative file_path values resolve against it. "
        "When the user names a subfolder, call list_documents or search_folder with it and reference only documents inside it. "
        if PDF_DIR else "Tools read .pdf and .md files. "
    ) + (
        "For a large document call skim_document before read_pdf_pages. "
        "To save tokens, delegate bulk reading or summarizing to the doc-skimmer subagent when it is available. "
        "When the user asks to save or export a result (e.g. 'PPT로', '워드로', 'PDF로 저장', 'HTML', '마크다운'), "
        "call export_document with the matching format, including format notion for Notion, and follow its next_steps."
    ),
)


def _resolve(file_path: str) -> Path:
    root = Path(PDF_DIR or ".").resolve()
    path = (root / Path(file_path).expanduser()).resolve()
    # Documents are often private, so nothing loads from outside the registered folder.
    if not path.is_relative_to(root):
        raise ValueError(f"File is outside the document folder: {file_path}. Paths are relative to the document folder itself, e.g. 'manual.pdf' or 'sub/a.md'; use '' for all documents.")
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    return path


def _is_md(path: Path) -> bool:
    return path.suffix.lower() == ".md"


def _md_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as e:
        raise ValueError(f"Markdown file is not UTF-8: {path}") from e


def _md_toc(lines: list[str]) -> list[dict]:
    toc, fence = [], ""
    for i, line in enumerate(lines):
        m = MD_FENCE.match(line)
        if fence:  # A "# comment" inside a code block is not a heading.
            if m and m[1][0] == fence[0] and len(m[1]) >= len(fence) and not m[2].strip():
                fence = ""
        elif m and not (m[1][0] == "`" and "`" in m[2]):
            fence = m[1]
        elif (h := MD_HEADING.match(line)) and h[2]:
            toc.append({"level": len(h[1]), "title": h[2], "page": i // MD_LINES_PER_PAGE + 1})
    return toc


# shortcut: whole-text cache in memory (a few MB per large PDF), move to disk if many huge PDFs are used.
@lru_cache(maxsize=16)
def _cached_pages(path: Path, mtime_ns: int, size: int) -> tuple[str, ...]:
    if _is_md(path):
        lines = _md_lines(path)
        return tuple(
            "\n".join(lines[i:i + MD_LINES_PER_PAGE]) for i in range(0, len(lines), MD_LINES_PER_PAGE)
        ) or ("",)
    with _open_pdf(path) as doc:
        return tuple(page.get_text() for page in doc)


def _pages(file_path: str) -> tuple[Path, tuple[str, ...]]:
    """Text of every page; re-extracted only when the file changes."""
    path = _resolve(file_path)
    st = path.stat()
    return path, _cached_pages(path, st.st_mtime_ns, st.st_size)


def _toc(path: Path, pages: tuple[str, ...]) -> list[dict]:
    if _is_md(path):
        return _md_toc([line for page in pages for line in page.split("\n")])
    with _open_pdf(path) as doc:
        return [{"level": l, "title": t, "page": p} for l, t, p in doc.get_toc()]


def _flat(text: str) -> str:
    # PDF text wraps arbitrarily, so collapse all whitespace.
    return " ".join(text.split())


def _matches(pages: tuple[str, ...], words: list[str], mode: str, limit: int) -> tuple[list[dict], int]:
    """Return up to limit hits and the total count. mode "all_words" matches pages containing every word."""
    phrase = re.compile(r"\s+".join(map(re.escape, words)), re.IGNORECASE)
    first = re.compile(re.escape(words[0]), re.IGNORECASE)
    hits, total = [], 0
    for n, raw in enumerate(pages):
        text = _flat(raw)
        if mode == "phrase":
            found = list(phrase.finditer(text))
        elif all(w.lower() in text.lower() for w in words):
            found = [first.search(text)]
        else:
            found = []
        total += len(found)
        for m in found[:max(0, limit - len(hits))]:
            hits.append({"page": n + 1, "snippet": text[max(0, m.start() - SNIPPET_RADIUS):m.end() + SNIPPET_RADIUS]})
    return hits, total


def _query_words(query: str, max_results: int) -> tuple[list[str], int]:
    words = query.split()
    if not words:
        raise ValueError("query must not be empty")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    # Korean particles break exact phrases ("안전의 관리"), so fall back to all words on the page.
    return words, min(max_results, MAX_SEARCH_RESULTS)


def _modes(words: list[str]) -> tuple[str, ...]:
    return ("phrase", "all_words") if len(words) > 1 else ("phrase",)


def _open_pdf(path: Path) -> pymupdf.Document:
    try:
        # Explicit filetype: otherwise MuPDF happily opens .txt, images, etc.
        doc = pymupdf.open(path, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Not a readable PDF: {path} ({e})") from e
    if doc.needs_pass:
        doc.close()
        raise ValueError(f"PDF is password-protected: {path}")
    return doc


@mcp.tool(annotations=READ_ONLY)
def get_pdf_info(file_path: str) -> dict:
    """Return page count, metadata and table of contents of a .pdf or .md file. Call this first to learn its structure. A Markdown page is 100 lines."""
    path, pages = _pages(file_path)
    if _is_md(path):
        return {
            "file_path": str(path),
            "page_count": len(pages),
            "metadata": {"format": "markdown", "lines_per_page": MD_LINES_PER_PAGE},
            "toc": _toc(path, pages),
        }
    with _open_pdf(path) as doc:
        metadata = {k: v for k, v in doc.metadata.items() if v}
    info = {"file_path": str(path), "page_count": len(pages), "metadata": metadata, "toc": _toc(path, pages)}
    empty = sum(not p.strip() for p in pages)
    if empty:
        info["pages_without_text"] = empty
        if empty == len(pages):
            info["warning"] = "No text layer (likely a scanned PDF). OCR is not supported, so search and read return nothing."
    return info


@mcp.tool(annotations=READ_ONLY)
def search_pdf(file_path: str, query: str, max_results: int = 5) -> dict:
    """Case-insensitive keyword search across all pages of a .pdf or .md file. Tries the exact phrase first, then pages containing every word. Returns 1-based page numbers with context snippets."""
    words, limit = _query_words(query, max_results)
    _, pages = _pages(file_path)
    for mode in _modes(words):
        hits, total = _matches(pages, words, mode, limit)
        if total:
            break
    return {"query": query, "mode": mode, "results": hits, "truncated": total > len(hits)}


@mcp.tool(annotations=READ_ONLY)
def list_documents(folder: str = "") -> dict:
    """List .pdf and .md files under a subfolder of the document folder, including nested folders. Empty folder means all documents."""
    docs = _documents(folder)
    return {
        "folder": folder,
        "documents": [doc.as_posix() for doc in docs],
        "truncated": len(docs) == MAX_LISTED_DOCS,
    }


@mcp.tool(annotations=READ_ONLY)
def search_folder(folder: str, query: str, max_results: int = 5) -> dict:
    """Keyword search limited to the .pdf and .md files under a subfolder, documents with the most matches first. Returns file_path, 1-based page and snippet; unreadable files are listed in skipped."""
    words, limit = _query_words(query, max_results)
    docs = _documents(folder)
    loaded, skipped = [], []
    for doc in docs:
        name = doc.as_posix()
        try:
            loaded.append((name, _pages(name)[1]))
        except ValueError as e:  # One bad file must not hide matches in the others.
            skipped.append({"file_path": name, "error": str(e)})
    for mode in _modes(words):
        ranked = []
        for name, pages in loaded:
            hits, total = _matches(pages, words, mode, limit)
            if total:
                ranked.append((total, name, hits))
        if ranked:
            break
    ranked.sort(key=lambda r: -r[0])  # Stable, so ties keep file name order.
    results = [{"file_path": name, **hit} for _, name, hits in ranked for hit in hits][:limit]
    truncated = len(docs) == MAX_LISTED_DOCS or sum(r[0] for r in ranked) > len(results)
    return {"folder": folder, "query": query, "mode": mode, "results": results, "skipped": skipped, "truncated": truncated}


@mcp.tool(annotations=READ_ONLY)
def read_pdf_pages(file_path: str, start_page: int, end_page: int) -> dict:
    """Read full text of a 1-based inclusive page range of a .pdf or .md file, at most 5 pages and 40,000 characters per call."""
    if start_page < 1 or end_page < start_page:
        raise ValueError("Require 1 <= start_page <= end_page")
    if end_page - start_page + 1 > MAX_PAGES_PER_READ:
        raise ValueError(f"Can read at most {MAX_PAGES_PER_READ} pages per call")
    _, pages = _pages(file_path)
    if end_page > len(pages):
        raise ValueError(f"end_page {end_page} exceeds page count {len(pages)}")
    out, budget, truncated = [], MAX_READ_CHARS, False
    for n in range(start_page - 1, end_page):
        text = pages[n][:budget]
        out.append({"page": n + 1, "text": text})
        budget -= len(text)
        if len(text) < len(pages[n]) or (budget <= 0 and n + 1 < end_page):
            truncated = True
            break
    return {"page_count": len(pages), "pages": out, "truncated": truncated}


@mcp.tool(annotations=READ_ONLY)
def skim_document(file_path: str, query: str = "", max_chars: int = 6000) -> dict:
    """Read only the key parts of a large .pdf or .md file within max_chars (1000-20000).
    With query: the pages that mention it most. With a table of contents: the opening of each section.
    Otherwise: the opening of evenly spaced pages. Use read_pdf_pages afterwards for details."""
    max_chars = max(1000, min(max_chars, 20_000))
    path, pages = _pages(file_path)
    flat = [_flat(p) for p in pages]
    picks = []  # (page index, start offset, title)

    if query.split():
        words = [w.lower() for w in query.split()]
        scores = [sum(t.lower().count(w) for w in words) for t in flat]
        best = sorted((i for i, sc in enumerate(scores) if sc), key=lambda i: -scores[i])[:max(1, max_chars // 600)]
        for i in sorted(best):
            at = min(flat[i].lower().find(w) for w in words if w in flat[i].lower())
            picks.append((i, at, None))
        mode = "query"
    else:
        toc = [e for e in _toc(path, pages) if e["level"] <= 2 and 1 <= e["page"] <= len(pages)]
        if len(toc) * 200 > max_chars:
            toc = [e for e in toc if e["level"] == 1] or toc
        if toc:
            for e in toc[:max_chars // 200]:
                i = e["page"] - 1
                picks.append((i, max(0, flat[i].lower().find(e["title"].lower())), e["title"]))
            mode = "toc"
        else:
            filled = [i for i, t in enumerate(flat) if t]
            k = min(len(filled), max(1, max_chars // 400))
            picks = [(filled[j * len(filled) // k], 0, None) for j in range(k)] if k else []
            mode = "pages"

    per = max_chars // max(1, len(picks))
    excerpts = []
    for i, at, title in picks:
        start = max(0, at - per // 4) if mode == "query" else at
        excerpt = {"page": i + 1, "text": flat[i][start:start + per]}
        if title:
            excerpt["title"] = title
        excerpts.append(excerpt)
    return {"file_path": str(path), "page_count": len(pages), "mode": mode, "excerpts": excerpts}


NOTION_STEPS = [
    "Check your own tool list for a Notion page-creation tool (e.g. notion-create-pages). This server cannot see other servers.",
    "If it exists: create the page from the content you passed (backup at saved_markdown) and report its link.",
    "If it does not exist or fails with an auth error: do NOT create the page, do NOT substitute another format, and stop. "
    "Tell the user Notion login is required, show login_guide, and wait for them to confirm they logged in.",
    "After they confirm: re-check the Notion tool and create the page from saved_markdown. If it is still missing, ask them to restart the client.",
]
NOTION_LOGIN_GUIDE = (
    "Notion 로그인이 필요합니다.\n"
    "1) 연결: claude mcp add --transport http notion https://mcp.notion.com/mcp  (claude.ai 계정이면 Settings > Connectors 에서 Notion 연결)\n"
    "2) 로그인: Claude Code에서 /mcp 입력 → notion 선택 → Authenticate → 브라우저에서 Notion 로그인·권한 허용\n"
    "3) 완료되면 '로그인했어'라고 알려주세요. 저장해 둔 내용으로 바로 이어서 작업합니다."
)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def export_document(content: str, format: doc_export.Format | Literal["notion"], file_name: str) -> dict:
    """Save Markdown content as md, html, pdf, docx or pptx in the exports folder and return its path.
    Pick format from the user's words: 마크다운/md, HTML/웹페이지, PDF, 워드/docx, PPT/파워포인트/슬라이드, 노션/Notion.
    For pptx, each # or ## heading starts a slide. Existing files are never overwritten.
    format notion saves a Markdown backup and returns next_steps that you must follow (Notion login is required first)."""
    out_dir = Path(os.environ.get("PDF_RAG_OUT") or Path.cwd() / "exports")
    if format == "notion":
        # Saved first, so the content survives the login detour or a restart.
        path = doc_export.export(content, "md", out_dir, file_name)
        return {"format": "notion", "saved_markdown": str(path), "next_steps": NOTION_STEPS, "login_guide": NOTION_LOGIN_GUIDE}
    path = doc_export.export(content, format, out_dir, file_name)
    return {"path": str(path), "format": format}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

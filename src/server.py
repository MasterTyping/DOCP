"""Local PDF and Markdown search MCP server (stdio). stdout is reserved for the protocol."""
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, unquote

import pymupdf
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource, ToolAnnotations

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
# MuPDF writes warnings to stdout by default, which would corrupt the MCP stream.
pymupdf.set_messages(stream=sys.stderr)

MAX_PAGES_PER_READ = 5
MAX_SEARCH_RESULTS = 50
SNIPPET_RADIUS = 100
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
        raise ValueError(f"Folder not found inside the document folder: {subfolder}")
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
        if not PDF_DIR or not _resolve(name).is_relative_to(Path(PDF_DIR).resolve()):
            raise ValueError(f"Document is outside the registered folder: {name}")
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
        "When the user names a subfolder, call list_documents or search_folder with it and reference only documents inside it."
        if PDF_DIR else "Tools read .pdf and .md files."
    ),
)


def _resolve(file_path: str) -> Path:
    path = (Path(PDF_DIR or ".") / Path(file_path).expanduser()).resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    return path


def _is_md(path: Path) -> bool:
    return path.suffix.lower() == ".md"


def _md_lines(path: Path) -> list[str]:
    # Private notes are often .md, so unlike PDFs these never load from outside the registered folder.
    if not path.is_relative_to(Path(PDF_DIR or ".").resolve()):
        raise ValueError(f"Markdown files must be inside the document folder: {path}")
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


@contextmanager
def _open_pages(file_path: str):
    """Yield (page_count, text_of_zero_based_page) for a PDF or Markdown file."""
    path = _resolve(file_path)
    if _is_md(path):
        lines = _md_lines(path)
        pages = [
            "\n".join(lines[i:i + MD_LINES_PER_PAGE]) for i in range(0, len(lines), MD_LINES_PER_PAGE)
        ] or [""]
        yield len(pages), pages.__getitem__
    else:
        with _open_pdf(path) as doc:
            yield doc.page_count, lambda n: doc[n].get_text()


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
    path = _resolve(file_path)
    if _is_md(path):
        lines = _md_lines(path)
        return {
            "file_path": str(path),
            "page_count": max(1, (len(lines) + MD_LINES_PER_PAGE - 1) // MD_LINES_PER_PAGE),
            "metadata": {"format": "markdown", "lines_per_page": MD_LINES_PER_PAGE},
            "toc": _md_toc(lines),
        }
    with _open_pdf(path) as doc:
        return {
            "file_path": doc.name,
            "page_count": doc.page_count,
            "metadata": {k: v for k, v in doc.metadata.items() if v},
            "toc": [{"level": l, "title": t, "page": p} for l, t, p in doc.get_toc()],
        }


@mcp.tool(annotations=READ_ONLY)
def search_pdf(file_path: str, query: str, max_results: int = 5) -> dict:
    """Case-insensitive keyword search across all pages of a .pdf or .md file. Returns 1-based page numbers with context snippets."""
    words = query.split()
    if not words:
        raise ValueError("query must not be empty")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    limit = min(max_results, MAX_SEARCH_RESULTS)
    # PDF text wraps arbitrarily, so any whitespace in the query matches any whitespace in the page.
    pattern = re.compile(r"\s+".join(map(re.escape, words)), re.IGNORECASE)

    results = []
    with _open_pages(file_path) as (page_count, text_of):
        for n in range(page_count):
            text = " ".join(text_of(n).split())
            for m in pattern.finditer(text):
                if len(results) == limit:
                    return {"query": query, "results": results, "truncated": True}
                start, end = max(0, m.start() - SNIPPET_RADIUS), m.end() + SNIPPET_RADIUS
                results.append({"page": n + 1, "snippet": text[start:end]})
    return {"query": query, "results": results, "truncated": False}


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
    """Keyword search limited to the .pdf and .md files under a subfolder. Returns file_path, 1-based page and snippet; unreadable files are listed in skipped."""
    if not query.split():
        raise ValueError("query must not be empty")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    limit = min(max_results, MAX_SEARCH_RESULTS)
    docs = _documents(folder)
    results, skipped, truncated = [], [], len(docs) == MAX_LISTED_DOCS
    for doc in docs:
        if len(results) == limit:  # Remaining documents were not searched.
            truncated = True
            break
        name = doc.as_posix()
        try:
            found = search_pdf(name, query, limit - len(results))
        except ValueError as e:  # One bad file must not hide matches in the others.
            skipped.append({"file_path": name, "error": str(e)})
            continue
        results += [{"file_path": name, **r} for r in found["results"]]
        truncated = truncated or found["truncated"]
    return {"folder": folder, "query": query, "results": results, "skipped": skipped, "truncated": truncated}


@mcp.tool(annotations=READ_ONLY)
def read_pdf_pages(file_path: str, start_page: int, end_page: int) -> dict:
    """Read full text of a 1-based inclusive page range of a .pdf or .md file, at most 5 pages per call."""
    if start_page < 1 or end_page < start_page:
        raise ValueError("Require 1 <= start_page <= end_page")
    if end_page - start_page + 1 > MAX_PAGES_PER_READ:
        raise ValueError(f"Can read at most {MAX_PAGES_PER_READ} pages per call")
    with _open_pages(file_path) as (page_count, text_of):
        if end_page > page_count:
            raise ValueError(f"end_page {end_page} exceeds page count {page_count}")
        return {
            "page_count": page_count,
            "pages": [
                {"page": n + 1, "text": text_of(n)}
                for n in range(start_page - 1, end_page)
            ],
        }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

"""Local PDF search MCP server (stdio). stdout is reserved for the protocol."""
import logging
import os
import re
import sys
from pathlib import Path

import pymupdf
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
# MuPDF writes warnings to stdout by default, which would corrupt the MCP stream.
pymupdf.set_messages(stream=sys.stderr)

MAX_PAGES_PER_READ = 5
MAX_SEARCH_RESULTS = 50
SNIPPET_RADIUS = 100
READ_ONLY = ToolAnnotations(readOnlyHint=True)

PDF_DIR = os.environ.get("PDF_RAG_DIR")

mcp = FastMCP(
    "pdf-rag",
    instructions=f"Default PDF folder: {PDF_DIR}. Relative file_path values resolve against it." if PDF_DIR else None,
)


def _open_pdf(file_path: str) -> pymupdf.Document:
    path = (Path(PDF_DIR or ".") / Path(file_path).expanduser()).resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
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
    """Return page count, metadata and table of contents. Call this first to learn the document structure."""
    with _open_pdf(file_path) as doc:
        return {
            "file_path": doc.name,
            "page_count": doc.page_count,
            "metadata": {k: v for k, v in doc.metadata.items() if v},
            "toc": [{"level": l, "title": t, "page": p} for l, t, p in doc.get_toc()],
        }


@mcp.tool(annotations=READ_ONLY)
def search_pdf(file_path: str, query: str, max_results: int = 5) -> dict:
    """Case-insensitive keyword search across all pages. Returns 1-based page numbers with context snippets."""
    words = query.split()
    if not words:
        raise ValueError("query must not be empty")
    if max_results < 1:
        raise ValueError("max_results must be at least 1")
    limit = min(max_results, MAX_SEARCH_RESULTS)
    # PDF text wraps arbitrarily, so any whitespace in the query matches any whitespace in the page.
    pattern = re.compile(r"\s+".join(map(re.escape, words)), re.IGNORECASE)

    results = []
    with _open_pdf(file_path) as doc:
        for page in doc:
            text = " ".join(page.get_text().split())
            for m in pattern.finditer(text):
                if len(results) == limit:
                    return {"query": query, "results": results, "truncated": True}
                start, end = max(0, m.start() - SNIPPET_RADIUS), m.end() + SNIPPET_RADIUS
                results.append({"page": page.number + 1, "snippet": text[start:end]})
    return {"query": query, "results": results, "truncated": False}


@mcp.tool(annotations=READ_ONLY)
def read_pdf_pages(file_path: str, start_page: int, end_page: int) -> dict:
    """Read full text of a 1-based inclusive page range, at most 5 pages per call."""
    if start_page < 1 or end_page < start_page:
        raise ValueError("Require 1 <= start_page <= end_page")
    if end_page - start_page + 1 > MAX_PAGES_PER_READ:
        raise ValueError(f"Can read at most {MAX_PAGES_PER_READ} pages per call")
    with _open_pdf(file_path) as doc:
        if end_page > doc.page_count:
            raise ValueError(f"end_page {end_page} exceeds page count {doc.page_count}")
        return {
            "page_count": doc.page_count,
            "pages": [
                {"page": n + 1, "text": doc[n].get_text()}
                for n in range(start_page - 1, end_page)
            ],
        }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

"""Render Markdown to md, html, pdf, docx or pptx files."""
import html
from pathlib import Path
from typing import Literal

import pymupdf
from markdown_it import MarkdownIt

Format = Literal["md", "html", "pdf", "docx", "pptx"]
CSS = (
    "body{font-family:sans-serif;line-height:1.6;max-width:50em;margin:2em auto;padding:0 1em}"
    "table{border-collapse:collapse}th,td{border:1px solid #999;padding:4px 8px}"
    "pre{background:#f4f4f4;padding:8px;white-space:pre-wrap}"
)
_md = MarkdownIt("commonmark").enable("table")


def export(content: str, fmt: str, out_dir: Path, file_name: str) -> Path:
    if fmt not in Format.__args__:
        raise ValueError(f"Unsupported format: {fmt}. Use one of {', '.join(Format.__args__)}")
    if not content.strip():
        raise ValueError("content must not be empty")
    stem = Path(file_name).stem.strip() or "export"  # .name/.stem drop any directory part, so no traversal.
    out_dir.mkdir(parents=True, exist_ok=True)
    path, n = out_dir / f"{stem}.{fmt}", 1
    while path.exists():  # Never overwrite an earlier export.
        path, n = out_dir / f"{stem}-{n}.{fmt}", n + 1
    {"md": _md_file, "html": _html_file, "pdf": _pdf_file, "docx": _docx_file, "pptx": _pptx_file}[fmt](content, path, stem)
    return path.resolve()


def _md_file(content: str, path: Path, title: str) -> None:
    path.write_text(content, encoding="utf-8")


def _html(content: str, title: str) -> str:
    return (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
        f"<body>{_md.render(content)}</body></html>"
    )


def _html_file(content: str, path: Path, title: str) -> None:
    path.write_text(_html(content, title), encoding="utf-8")


def _pdf_file(content: str, path: Path, title: str) -> None:
    story = pymupdf.Story(_md.render(content), user_css=CSS.replace("max-width:50em;margin:2em auto;", ""))
    page = pymupdf.paper_rect("a4")
    writer = pymupdf.DocumentWriter(str(path))
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(page + (50, 50, -50, -50))
        story.draw(device)
        writer.end_page()
    writer.close()


def _blocks(content: str) -> list[tuple]:
    """Flatten Markdown into (kind, level, text) blocks; kind is heading, para, bullet, number, code or table."""
    blocks, lists, row, rows = [], [], None, None
    for tok in _md.parse(content):
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            lists.append("bullet" if tok.type == "bullet_list_open" else "number")
        elif tok.type in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif tok.type == "table_open":
            rows = []
        elif tok.type == "table_close":
            blocks.append(("table", 0, rows))
            rows = None
        elif tok.type == "tr_open":
            row = []
            rows.append(row)
        elif tok.type in ("fence", "code_block"):
            blocks.append(("code", 0, tok.content.rstrip("\n")))
        elif tok.type == "heading_open":
            blocks.append(("heading", int(tok.tag[1]), None))
        elif tok.type == "inline":
            text = _plain(tok)
            if rows is not None:
                row.append(text)
            elif blocks and blocks[-1][0] == "heading" and blocks[-1][2] is None:
                blocks[-1] = ("heading", blocks[-1][1], text)
            elif lists:
                blocks.append((lists[-1], len(lists), text))
            else:
                blocks.append(("para", 0, text))
    return blocks


def _plain(tok) -> str:
    # shortcut: inline bold/italic/links become plain text in docx and pptx; map runs if styling is needed.
    return "".join(
        c.content if c.type in ("text", "code_inline") else "\n" if c.type in ("softbreak", "hardbreak") else ""
        for c in tok.children or []
    )


def _docx_file(content: str, path: Path, title: str) -> None:
    from docx import Document

    doc = Document()
    for kind, level, text in _blocks(content):
        if kind == "heading":
            doc.add_heading(text or "", min(level, 9))
        elif kind in ("bullet", "number"):
            style = "List Bullet" if kind == "bullet" else "List Number"
            doc.add_paragraph(text, style=style + (f" {min(level, 3)}" if level > 1 else ""))
        elif kind == "code":
            doc.add_paragraph().add_run(text).font.name = "Consolas"
        elif kind == "table":
            if text:
                table = doc.add_table(rows=len(text), cols=max(map(len, text)), style="Table Grid")
                for r, cells in enumerate(text):
                    for c, cell in enumerate(cells):
                        table.cell(r, c).text = cell
        else:
            doc.add_paragraph(text)
    doc.save(path)


def _pptx_file(content: str, path: Path, title: str) -> None:
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()
    slides = []  # [title, [(level, text)]]
    for kind, level, text in _blocks(content):
        if kind == "heading" and level <= 2:
            slides.append([text or "", []])
            continue
        if not slides:
            slides.append([title, []])
        body = slides[-1][1]
        if kind == "table":
            body += [(0, " | ".join(cells)) for cells in text]
        elif kind == "heading":
            body.append((0, text or ""))
        else:
            body += [(max(level - 1, 0), line) for line in text.splitlines() if line.strip()]

    for i, (heading, body) in enumerate(slides):
        if i == 0 and not body:  # A lone top heading becomes the title slide.
            prs.slides.add_slide(prs.slide_layouts[0]).shapes.title.text = heading
            continue
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = heading
        frame = slide.placeholders[1].text_frame
        # shortcut: long sections overflow one slide; split body by line count if decks get crowded.
        for j, (level, line) in enumerate(body):
            para = frame.paragraphs[0] if j == 0 else frame.add_paragraph()
            para.text, para.level = line, min(level, 4)
            if len(body) > 8:
                para.font.size = Pt(14)
    prs.save(path)

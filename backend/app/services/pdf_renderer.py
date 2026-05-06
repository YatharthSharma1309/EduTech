"""
Renders PDF pages to PNG and crops individual question images.

Workflow:
  1. render_pdf_pages()  — full page PNGs at configured DPI
  2. crop_question_images() — one PNG per detected question boundary
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PageImage:
    page_number: int   # 1-indexed
    file_path: str
    width: int
    height: int


@dataclass
class QuestionCrop:
    question_number: int
    page_number: int   # 1-indexed
    file_path: str
    y_top: float       # relative to page, 0-1
    y_bottom: float


def render_pdf_pages(pdf_path: str, output_dir: str, dpi: int = 150) -> list[PageImage]:
    """Render every page of the PDF as a PNG. Returns list of PageImage."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    zoom = dpi / 72  # 72 is PDF base DPI
    mat = fitz.Matrix(zoom, zoom)
    results: list[PageImage] = []

    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=mat, alpha=False)
        path = out / f"page_{i:03d}.png"
        pix.save(str(path))
        results.append(PageImage(
            page_number=i,
            file_path=str(path),
            width=pix.width,
            height=pix.height,
        ))

    doc.close()
    return results


# Patterns that mark the start of a new question
_Q_PATTERNS = [
    re.compile(r"^\s*Q\.?\s*(\d+)", re.IGNORECASE),       # Q1, Q.1, Q 1
    re.compile(r"^\s*(\d+)\.\s"),                           # 1. text
    re.compile(r"^\s*(\d+)\s*\)"),                          # 1) text
]


def _detect_question_starts(page: fitz.Page) -> list[tuple[int, float]]:
    """
    Return list of (question_number, y_top_absolute) for each question
    boundary found on this page using text block positions.

    Mohak fix: sort blocks by (y, x) for correct reading order in multi-column
    layouts, and enforce sequential numbering to avoid matching answer-choice
    labels (e.g. "1)" inside a question) as question starts.
    """
    blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
    # Sort top-to-bottom, left-to-right (fixes multi-column PDFs)
    blocks = sorted(blocks, key=lambda b: (b[1], b[0]))

    hits: list[tuple[int, float]] = []
    expected_num = 1  # enforce sequential numbering

    for block in blocks:
        if block[6] != 0:  # skip image blocks
            continue
        text = block[4].strip()
        first_line = text.split("\n")[0].strip()
        for pattern in _Q_PATTERNS:
            m = pattern.match(first_line)
            if m:
                q_num = int(m.group(1))
                # Only accept if this is the next expected question number
                if q_num == expected_num:
                    hits.append((q_num, float(block[1])))
                    expected_num += 1
                break

    return hits


def crop_question_images(
    pdf_path: str,
    output_dir: str,
    dpi: int = 150,
) -> list[QuestionCrop]:
    """
    Detect question boundaries across all pages and save one cropped PNG
    per question. Falls back to one PNG per page if no markers found.
    """
    out = Path(output_dir) / "questions"
    out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)

    # Collect (page_idx 0-based, q_num, y_top_pts) across all pages
    all_markers: list[tuple[int, int, float]] = []
    page_heights: list[float] = []

    for page_idx, page in enumerate(doc):
        page_heights.append(page.rect.height)
        for q_num, y_top in _detect_question_starts(page):
            all_markers.append((page_idx, q_num, y_top))

    crops: list[QuestionCrop] = []

    if not all_markers:
        # Fallback: one crop per full page
        for page_idx, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            path = out / f"q_page_{page_idx + 1:03d}.png"
            pix.save(str(path))
            crops.append(QuestionCrop(
                question_number=page_idx + 1,
                page_number=page_idx + 1,
                file_path=str(path),
                y_top=0.0,
                y_bottom=1.0,
            ))
        doc.close()
        return crops

    # Sort by page then y position
    all_markers.sort(key=lambda m: (m[0], m[2]))

    for i, (page_idx, q_num, y_top) in enumerate(all_markers):
        page = doc[page_idx]
        h = page_heights[page_idx]

        # Bottom boundary: next marker on same page, or bottom of page
        if i + 1 < len(all_markers) and all_markers[i + 1][0] == page_idx:
            y_bottom = all_markers[i + 1][2]
        else:
            y_bottom = h

        # Mohak fix: first question starts from top of page to capture any
        # reference diagram printed above the Q1 marker.
        # All others get a 5-point upward pad to avoid clipping the first line.
        if i == 0:
            y_top_clip = 0.0
        else:
            y_top_clip = max(0.0, y_top - 5)

        # Mohak fix: skip degenerate clips that would crash PyMuPDF
        if y_bottom - y_top_clip < 1:
            continue

        clip = fitz.Rect(0, y_top_clip, page.rect.width, y_bottom)
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        path = out / f"q_{q_num:04d}.png"
        pix.save(str(path))

        crops.append(QuestionCrop(
            question_number=q_num,
            page_number=page_idx + 1,
            file_path=str(path),
            y_top=y_top / h,
            y_bottom=y_bottom / h,
        ))

    doc.close()
    return crops

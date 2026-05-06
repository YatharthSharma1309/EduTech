"""
Extracts embedded figures from a PDF and assigns each figure to the question
whose vertical region it falls within.

Approach adapted from MohakGuptaWhilter/QuestionAnswerTesting:
  - Compute exact (page, y_top, y_bottom) bounding box per question.
  - Assign each figure to the question whose box contains the figure's y position.
  - Falls back to nearest question only when no box contains the figure.
"""

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class ExtractedFigure:
    page_number: int       # 1-indexed
    y_top: float           # absolute y in PDF points
    file_path: str
    matched_question: int | None = None


def extract_and_assign_figures(
    pdf_path: str,
    output_dir: str,
    question_crops: list,   # list[QuestionCrop] from pdf_renderer
    page_heights: dict[int, float],
) -> dict[int, list[str]]:
    """
    Extract all embedded images from the PDF and assign each to a question
    using the question's bounding box.

    Returns {question_number: [figure_path, ...]} — only questions with figures included.
    """
    out = Path(output_dir) / "figures"
    out.mkdir(parents=True, exist_ok=True)

    # Build per-question bounding boxes: {q_num: (page_number, y_top_abs, y_bottom_abs)}
    q_boxes: dict[int, tuple[int, float, float]] = {}
    for crop in question_crops:
        h = page_heights.get(crop.page_number, 800.0)
        q_boxes[crop.question_number] = (
            crop.page_number,
            crop.y_top * h,
            crop.y_bottom * h,
        )

    doc = fitz.open(pdf_path)
    seen_xrefs: set[int] = set()
    q_figures: dict[int, list[str]] = {}
    fig_idx = 0

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1

        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            base_image = doc.extract_image(xref)
            if not base_image:
                continue
            if base_image["width"] < 50 or base_image["height"] < 50:
                continue

            # Get figure's y position on its page
            img_y = _get_image_y(page, xref)

            # Find which question's bounding box contains this figure
            assigned_q = _assign_to_question(page_num, img_y, q_boxes)
            if assigned_q is None:
                continue

            ext = base_image["ext"]
            fig_idx += 1
            path = out / f"fig_{fig_idx:04d}_q{assigned_q}.{ext}"
            path.write_bytes(base_image["image"])

            q_figures.setdefault(assigned_q, []).append(str(path))

    doc.close()
    return q_figures


def _get_image_y(page: fitz.Page, xref: int) -> float:
    # Mohak fix: get_image_rects is a direct O(1) lookup vs the O(n) loop
    # over get_image_info that we had before.
    rects = page.get_image_rects(xref)
    if rects:
        return float(rects[0].y0)
    return 0.0


def _assign_to_question(
    page_num: int,
    img_y: float,
    q_boxes: dict[int, tuple[int, float, float]],
) -> int | None:
    """
    Return the question number whose bounding box contains (page_num, img_y).
    Falls back to the nearest question on the same page if no exact match.

    Mohak fix: figures that appear above the first question marker on the page
    are explicitly assigned to the lowest-numbered question on that page
    (previously dropped silently).
    """
    same_page = {q: (yt, yb) for q, (pg, yt, yb) in q_boxes.items() if pg == page_num}
    if not same_page:
        return None

    for q_num, (y_top, y_bottom) in same_page.items():
        if y_top <= img_y <= y_bottom:
            return q_num

    # Figure is above the first question marker — assign to lowest Q on this page
    first_q = min(same_page, key=lambda q: same_page[q][0])
    if img_y < same_page[first_q][0]:
        return first_q

    # Nearest question by distance (below last marker)
    best_q = min(same_page, key=lambda q: min(abs(img_y - same_page[q][0]), abs(img_y - same_page[q][1])))
    return best_q

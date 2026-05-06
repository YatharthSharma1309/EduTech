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
    for item in page.get_image_info(xrefs=True):
        if item.get("xref") == xref:
            return float(item["bbox"][1])
    return 0.0


def _assign_to_question(
    page_num: int,
    img_y: float,
    q_boxes: dict[int, tuple[int, float, float]],
) -> int | None:
    """
    Return the question number whose bounding box contains (page_num, img_y).
    Falls back to the nearest question on the same page if no exact match.
    """
    best_q = None
    best_dist = float("inf")

    for q_num, (q_page, y_top, y_bottom) in q_boxes.items():
        if q_page != page_num:
            continue
        if y_top <= img_y <= y_bottom:
            return q_num
        dist = min(abs(img_y - y_top), abs(img_y - y_bottom))
        if dist < best_dist:
            best_dist = dist
            best_q = q_num

    return best_q

"""
Extracts embedded figures from a PDF and matches each figure
to its nearest question by y-position proximity.
"""

import base64
from dataclasses import dataclass, field
from pathlib import Path

import fitz


@dataclass
class ExtractedFigure:
    page_number: int       # 1-indexed
    y_top: float           # absolute y in PDF points
    file_path: str
    base64_data: str
    matched_question: int | None = None   # filled after matching


def extract_figures(pdf_path: str, output_dir: str) -> list[ExtractedFigure]:
    """
    Extract all embedded raster images from the PDF.
    Skips tiny images (likely decorations) under 50x50 px.
    De-duplicates by xref so the same image isn't saved twice.
    """
    out = Path(output_dir) / "figures"
    out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    seen_xrefs: set[int] = set()
    figures: list[ExtractedFigure] = []
    fig_idx = 0

    for page_idx, page in enumerate(doc):
        img_list = page.get_images(full=True)

        for img_info in img_list:
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            # Get image bytes
            base_image = doc.extract_image(xref)
            if not base_image:
                continue

            w, h = base_image["width"], base_image["height"]
            if w < 50 or h < 50:
                continue

            ext = base_image["ext"]
            img_bytes = base_image["image"]

            fig_idx += 1
            path = out / f"fig_{fig_idx:04d}_p{page_idx + 1}.{ext}"
            path.write_bytes(img_bytes)

            # Find y position of this image on the page via image bbox
            y_top = _get_image_y(page, xref)

            figures.append(ExtractedFigure(
                page_number=page_idx + 1,
                y_top=y_top,
                file_path=str(path),
                base64_data=base64.b64encode(img_bytes).decode(),
            ))

    doc.close()
    return figures


def _get_image_y(page: fitz.Page, xref: int) -> float:
    """Return the top y-coordinate (PDF points) of an image on its page."""
    for item in page.get_image_info(xrefs=True):
        if item.get("xref") == xref:
            return float(item["bbox"][1])
    return 0.0


def match_figures_to_questions(
    figures: list[ExtractedFigure],
    question_crops: list,   # list[QuestionCrop] — avoid circular import
    page_heights: dict[int, float],
) -> list[ExtractedFigure]:
    """
    For each figure, find the question whose y-range on the same page
    contains (or is closest to) the figure's y_top.
    Mutates matched_question on each ExtractedFigure.
    """
    for fig in figures:
        best_q = None
        best_dist = float("inf")

        for crop in question_crops:
            if crop.page_number != fig.page_number:
                continue

            h = page_heights.get(fig.page_number, 800.0)
            q_y_top_abs = crop.y_top * h
            q_y_bot_abs = crop.y_bottom * h

            # Inside the question's vertical range
            if q_y_top_abs <= fig.y_top <= q_y_bot_abs:
                best_q = crop.question_number
                break

            # Otherwise find nearest by distance
            dist = min(abs(fig.y_top - q_y_top_abs), abs(fig.y_top - q_y_bot_abs))
            if dist < best_dist:
                best_dist = dist
                best_q = crop.question_number

        fig.matched_question = best_q

    return figures

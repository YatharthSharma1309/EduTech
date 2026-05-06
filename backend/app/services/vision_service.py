"""
Ollama vision model wrapper.
Sends a question crop image to qwen2.5vl and extracts structured fields:
  question stem, four choices, and [Figure N] placeholders.

Prompt approach adapted from MohakGuptaWhilter/QuestionAnswerTesting:
  Step 1 — scan entire image for visual elements first
  Step 2 — extract text top-to-bottom, inserting [Figure N] at each visual
"""

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings


@dataclass
class VisionResult:
    question_number: int
    question_text: str
    c1: str
    c2: str
    c3: str
    c4: str
    raw_text: str          # full vision model output before parsing
    tokens_used: int = 0
    error: str = ""        # non-empty if vision call failed


_FIGURE_RULE_PRESENT = """\
- This question has {n} embedded visual element(s).
- As you read top-to-bottom, each time a figure, diagram, graph, or image appears \
insert the next numbered placeholder: [Figure 1] for the first, [Figure 2] for the \
second, and so on.
- If an answer option IS a visual (not a text value), write it as the choice text \
followed by [Figure N].
- Place each [Figure N] exactly where the visual sits — do NOT group them at the end."""

_FIGURE_RULE_ABSENT = """\
- No figures were detected by the PDF parser for this question.
- If you can still see a figure, graph, diagram, or image in the crop, insert \
[Figure 1] at that position (and [Figure 2], etc. for additional visuals).
- If there are truly no visual elements, do not write any [Figure N] token."""

_PROMPT_TEMPLATE = """\
You are an expert exam question extractor.

STEP 1 — SCAN THE ENTIRE IMAGE FOR VISUAL ELEMENTS:
Before reading any text, look at the whole image and identify every figure, graph, \
diagram, or image — both inside the question stem and inside any answer options.

STEP 2 — EXTRACT AND RETURN JSON with these exact keys:
  "question_text": the question stem only (no choice labels),
  "c1": text of choice 1 (strip labels like A), (1), 1.),
  "c2": text of choice 2,
  "c3": text of choice 3,
  "c4": text of choice 4

FIGURE PLACEHOLDER RULES:
{figure_instruction}

EXTRACTION RULES:
- Extract text exactly as visible. Do not rephrase or summarise.
- Write math in plain Unicode: x² not x^2, √x not \\sqrt{{x}}, α not \\alpha.
- Ignore watermarks, footers, page numbers, source labels (e.g. JEE Main 2024, MathonGo).
- If fewer than 4 choices exist, leave missing ones as "".
- Do NOT include answer keys — extract question and choices only.
- Return ONLY valid JSON. No explanation, no markdown fences.
"""


def extract_question_from_image(
    image_path: str,
    question_number: int,
    figure_count: int = 0,
) -> VisionResult:
    """Call Ollama vision model on a question crop image."""
    img_bytes = Path(image_path).read_bytes()
    b64 = base64.b64encode(img_bytes).decode()

    figure_instruction = (
        _FIGURE_RULE_PRESENT.format(n=figure_count)
        if figure_count > 0
        else _FIGURE_RULE_ABSENT
    )
    prompt = _PROMPT_TEMPLATE.format(figure_instruction=figure_instruction)

    payload = {
        "model": settings.ollama_vision_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 1024},
    }

    try:
        resp = httpx.post(
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
            timeout=None,
        )
        resp.raise_for_status()
        body = resp.json()
        tokens = body.get("prompt_eval_count", 0) + body.get("eval_count", 0)
        raw = body["message"]["content"]
        parsed = _parse_vision_json(raw)

        return VisionResult(
            question_number=question_number,
            question_text=parsed.get("question_text", "").strip(),
            c1=parsed.get("c1", "").strip(),
            c2=parsed.get("c2", "").strip(),
            c3=parsed.get("c3", "").strip(),
            c4=parsed.get("c4", "").strip(),
            raw_text=raw,
            tokens_used=tokens,
        )

    except Exception as exc:
        return VisionResult(
            question_number=question_number,
            question_text="",
            c1="", c2="", c3="", c4="",
            raw_text="",
            tokens_used=0,
            error=str(exc),
        )


def _parse_vision_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}

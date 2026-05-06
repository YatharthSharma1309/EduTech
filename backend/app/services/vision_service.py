"""
Ollama vision model wrapper.
Sends a question crop image to qwen2.5vl and extracts structured text:
  question stem, four choices, and any [IMAGE] placeholders.
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


_VISION_PROMPT = """Look at this exam question image carefully.

Extract the following and return as a JSON object with these exact keys:
  "question_text": the question stem (no option labels),
  "c1": text of option/choice 1 (strip any label like A), (1), 1.),
  "c2": text of option/choice 2,
  "c3": text of option/choice 3,
  "c4": text of option/choice 4

Rules:
- Where a diagram or figure appears in the question or an option, write [IMAGE] as a placeholder.
- Convert all math to plain Unicode (e.g. x² not x^2, α not \\alpha).
- Do NOT include answer keys — only extract the question and choices.
- If fewer than 4 choices exist, leave missing ones as "".
- Return ONLY valid JSON. No explanation, no markdown fences.
"""


def extract_question_from_image(
    image_path: str,
    question_number: int,
) -> VisionResult:
    """Call Ollama vision model on a question crop image."""
    img_bytes = Path(image_path).read_bytes()
    b64 = base64.b64encode(img_bytes).decode()

    payload = {
        "model": settings.ollama_vision_model,
        "messages": [
            {
                "role": "user",
                "content": _VISION_PROMPT,
                "images": [b64],
            }
        ],
        "stream": False,
        "format": "json",
        "options": {"num_predict": 300},
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

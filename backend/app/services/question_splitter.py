"""
Extracts raw text from PDF and uses Ollama to split it into
structured questions (with choices) and answers.

Output per question:
  { question_number, question_text, c1, c2, c3, c4, answer }
"""

import json
import re
from dataclasses import dataclass

import fitz
import httpx

from app.config import settings


@dataclass
class ParsedQuestion:
    question_number: int
    question_text: str
    c1: str
    c2: str
    c3: str
    c4: str
    answer: str        # raw answer string from PDF (e.g. "(2)", "B", "12.5")


def extract_pdf_text(pdf_path: str) -> str:
    """Extract all text from PDF using PyMuPDF, page-separated."""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if text:
            pages.append(f"--- Page {i} ---\n{text}")
    doc.close()
    return "\n\n".join(pages)


_SYSTEM_PROMPT = """You are a PDF question parser. Given raw text extracted from an exam paper PDF, extract all MCQ questions and their answers.

For each question return a JSON object with these exact keys:
  question_number (int),
  question_text (string — the question stem only, no choices),
  c1 (string — option/choice 1 text, without the label like "A)" or "(1)"),
  c2 (string — option/choice 2),
  c3 (string — option/choice 3),
  c4 (string — option/choice 4),
  answer (string — the correct answer value, e.g. "1", "2", "B", "12.5")

Rules:
- If choices are labeled (A)(B)(C)(D) or (1)(2)(3)(4) or 1.2.3.4., strip the label and keep only the text.
- If the answer key is at the end of the PDF, match each answer to its question number.
- If a question has no answer in the PDF, use "" for answer.
- If a question has fewer than 4 choices, fill missing ones with "".
- Return ONLY a valid JSON array of objects. No explanation, no markdown.
"""


def split_questions_with_llm(pdf_text: str) -> list[ParsedQuestion]:
    """Send PDF text to Ollama and parse the returned JSON."""
    payload = {
        "model": settings.ollama_text_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": pdf_text[:12000]},  # stay within context
        ],
        "stream": False,
        "format": "json",
    }

    resp = httpx.post(
        f"{settings.ollama_base_url}/api/chat",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()

    raw = resp.json()["message"]["content"]
    data = _safe_parse_json(raw)

    results: list[ParsedQuestion] = []
    for item in data:
        try:
            results.append(ParsedQuestion(
                question_number=int(item.get("question_number", 0)),
                question_text=str(item.get("question_text", "")).strip(),
                c1=str(item.get("c1", "")).strip(),
                c2=str(item.get("c2", "")).strip(),
                c3=str(item.get("c3", "")).strip(),
                c4=str(item.get("c4", "")).strip(),
                answer=str(item.get("answer", "")).strip(),
            ))
        except (TypeError, ValueError):
            continue

    results.sort(key=lambda q: q.question_number)
    return results


def _safe_parse_json(raw: str) -> list[dict]:
    """Try to parse JSON, stripping markdown fences if present."""
    raw = raw.strip()
    # strip ```json ... ``` fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            # sometimes model wraps in {"questions": [...]}
            for v in parsed.values():
                if isinstance(v, list):
                    return v
    except json.JSONDecodeError:
        pass
    return []

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


_CHUNK_SIZE = 6000   # chars per LLM call — keeps responses fast and within context


def split_questions_with_llm(pdf_text: str) -> tuple[list[ParsedQuestion], int]:
    """
    Split pdf_text into chunks and call Ollama on each.
    Returns (questions, total_tokens_used).
    """
    chunks = _chunk_text(pdf_text, _CHUNK_SIZE)
    all_results: dict[int, ParsedQuestion] = {}
    total_tokens = 0

    for chunk in chunks:
        items, tokens = _call_ollama(chunk)
        total_tokens += tokens
        for item in items:
            q_num = item.question_number
            if q_num not in all_results:
                all_results[q_num] = item
            elif item.answer and not all_results[q_num].answer:
                all_results[q_num].answer = item.answer

    return sorted(all_results.values(), key=lambda q: q.question_number), total_tokens


def _chunk_text(text: str, size: int) -> list[str]:
    """Split text into overlapping chunks on page boundaries where possible."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        # try to break at a page boundary so questions aren't split mid-way
        if end < len(text):
            boundary = text.rfind("--- Page", start, end)
            if boundary > start:
                end = boundary
        chunks.append(text[start:end])
        start = end
    return chunks


def _call_ollama(chunk: str) -> tuple[list[ParsedQuestion], int]:
    """Returns (questions, tokens_used)."""
    payload = {
        "model": settings.ollama_text_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": chunk},
        ],
        "stream": False,
        "format": "json",
    }

    try:
        resp = httpx.post(
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
            timeout=None,
        )
        resp.raise_for_status()
    except httpx.TimeoutException:
        print("[question_splitter] Ollama timeout on chunk — skipping", flush=True)
        return [], 0

    body = resp.json()
    tokens = body.get("prompt_eval_count", 0) + body.get("eval_count", 0)
    raw = body["message"]["content"]
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
    return results, tokens


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

"""
Verification: validates vision-extracted content against the original PDF crop image.

Strategy (adapted from MohakGuptaWhilter/QuestionAnswerTesting):
  1. Send the question crop image + our transcription to the vision model.
  2. VLM returns {match: bool, issues: [...], confidence: 0-1}.
  3. If confidence < VLM_CONFIDENCE_THRESHOLD → flag as text error with issues list.
  4. Fuzzy string match used as fast pre-filter: high similarity skips VLM call.
  5. If no crop image available, fall back to fuzzy-only.
"""

import base64
import json

import httpx
from rapidfuzz import fuzz

from app.config import settings
from app.services.excel_builder import ExcelRow
from app.services.question_splitter import ParsedQuestion
from app.services.vision_service import VisionResult

FUZZY_SKIP_THRESHOLD = 92     # above this → trusted, skip VLM call entirely
VLM_CONFIDENCE_THRESHOLD = 0.7  # below this → flag as text error

_VLM_VALIDATE_PROMPT = """\
You are a precise exam-question validator.

The image shows a question cropped from the original exam PDF.
Below is the text that was transcribed for this question:

TRANSCRIPTION:
{transcription}

Decide whether the transcription is an accurate and complete representation \
of the question in the image.

Evaluate:
1. Is the question stem word-for-word correct (wording, numbers, math, units)?
2. Are all answer choices present and correctly transcribed?
3. Is mathematical notation (fractions, exponents, symbols) accurately captured?

Return ONLY valid JSON with no surrounding text:
{{"match": true/false, "issues": ["describe each discrepancy"], "confidence": 0.0-1.0}}
"""


def _vlm_validate(image_path: str, transcription: str) -> dict:
    """Send PDF crop + transcription to vision model. Returns {match, issues, confidence}."""
    prompt = _VLM_VALIDATE_PROMPT.format(
        transcription=transcription.strip() or "(empty)"
    )
    try:
        with open(image_path, "rb") as fh:
            image_b64 = base64.b64encode(fh.read()).decode()
        if settings.use_anthropic_vision:
            payload = {
                "model": settings.anthropic_model,
                "max_tokens": 300,
                "system": "Return only valid JSON.",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            }
            headers = {
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=60.0,
            )
            resp.raise_for_status()
            body = resp.json()
            raw = "".join(
                block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
            ).strip()
            usage = body.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        else:
            payload = {
                "model": settings.ollama_vision_model,
                "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 512},
            }
            resp = httpx.post(
                f"{settings.ollama_base_url}/api/chat",
                json=payload,
                timeout=None,
            )
            resp.raise_for_status()
            raw = resp.json()["message"]["content"].strip()
            tokens = (
                resp.json().get("prompt_eval_count", 0)
                + resp.json().get("eval_count", 0)
            )

        # Extract JSON even if model wraps it in text
        start, end = raw.find("{"), raw.rfind("}") + 1
        result = json.loads(raw[start:end]) if start != -1 else {}
        return {**result, "_tokens": tokens}
    except Exception as exc:
        return {"match": True, "issues": [], "confidence": 1.0, "_tokens": 0, "_error": str(exc)}


def verify_and_build_rows(
    vision_results: list[VisionResult],
    llm_questions: list[ParsedQuestion],
    figure_map: dict[int, str],
    crop_paths: dict[int, str] | None = None,  # question_number → crop image path
) -> tuple[list[ExcelRow], int]:
    """
    Merge vision results with LLM-parsed questions, validate via VLM image comparison.
    Returns (rows, total_tokens_used).
    """
    llm_by_num = {q.question_number: q for q in llm_questions}
    crop_paths = crop_paths or {}
    rows: list[ExcelRow] = []
    total_tokens = 0

    for vr in vision_results:
        llm_q = llm_by_num.get(vr.question_number)
        text_error = ""

        # If vision failed entirely, promote LLM data so the row isn't blank
        if vr.error:
            text_error = f"Vision failed: {vr.error}"
            if llm_q:
                vr.question_text = vr.question_text or llm_q.question_text
                vr.c1 = vr.c1 or llm_q.c1
                vr.c2 = vr.c2 or llm_q.c2
                vr.c3 = vr.c3 or llm_q.c3
                vr.c4 = vr.c4 or llm_q.c4

        elif vr.question_text:
            crop_path = crop_paths.get(vr.question_number)
            full_transcription = "\n".join(filter(None, [
                vr.question_text, vr.c1, vr.c2, vr.c3, vr.c4
            ]))

            # Fast path 1: no LLM questions at all (image-only PDF) → nothing to
            # validate against, skip VLM entirely to avoid re-running the same
            # vision model on the same crop it just processed in Stage 4.
            skip_vlm = not bool(llm_by_num)

            # Fast path 2: high fuzzy similarity against LLM text → skip VLM call
            if llm_q and not skip_vlm:
                sim = fuzz.ratio(vr.question_text, llm_q.question_text)
                if sim >= FUZZY_SKIP_THRESHOLD:
                    skip_vlm = True

            # VLM image validation
            if crop_path and not skip_vlm:
                result = _vlm_validate(crop_path, full_transcription)
                total_tokens += result.get("_tokens", 0)
                if not result.get("match", True) and result.get("confidence", 1.0) < VLM_CONFIDENCE_THRESHOLD:
                    issues = "; ".join(result.get("issues", []))
                    conf = result.get("confidence", 0)
                    text_error = f"VLM mismatch (conf {conf:.0%}): {issues}"

        rows.append(ExcelRow(
            question_number=vr.question_number,
            question_text=vr.question_text or (llm_q.question_text if llm_q else ""),
            c1=vr.c1 or (llm_q.c1 if llm_q else ""),
            c2=vr.c2 or (llm_q.c2 if llm_q else ""),
            c3=vr.c3 or (llm_q.c3 if llm_q else ""),
            c4=vr.c4 or (llm_q.c4 if llm_q else ""),
            answer=llm_q.answer if llm_q else "",
            figure_path=figure_map.get(vr.question_number),
            text_error=text_error,
            error_answer="",
        ))

    # Questions vision missed entirely — use LLM text only
    vision_nums = {vr.question_number for vr in vision_results}
    for llm_q in llm_questions:
        if llm_q.question_number not in vision_nums:
            rows.append(ExcelRow(
                question_number=llm_q.question_number,
                question_text=llm_q.question_text,
                c1=llm_q.c1, c2=llm_q.c2, c3=llm_q.c3, c4=llm_q.c4,
                answer=llm_q.answer,
                figure_path=figure_map.get(llm_q.question_number),
                text_error="Vision crop not found — text only",
            ))

    rows.sort(key=lambda r: r.question_number)
    return rows, total_tokens

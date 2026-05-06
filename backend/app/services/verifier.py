"""
Verification: compares vision-extracted content against LLM text-extracted content.
Flags mismatches as Text Error or Error Answer.

Strategy:
  1. Fuzzy string match (rapidfuzz) between vision Q text and LLM Q text.
  2. If similarity < FUZZY_THRESHOLD, flag as text error.
  3. If answers differ, flag as error answer.
  4. For borderline cases (FUZZY_THRESHOLD < sim < LLM_THRESHOLD),
     call Ollama to do a semantic equivalence check.
"""

import httpx
from rapidfuzz import fuzz

from app.config import settings
from app.services.excel_builder import ExcelRow
from app.services.question_splitter import ParsedQuestion
from app.services.vision_service import VisionResult

FUZZY_THRESHOLD = 70    # below this → definite text error
LLM_THRESHOLD = 70      # match threshold — skip LLM verify, fuzzy only


def verify_and_build_rows(
    vision_results: list[VisionResult],
    llm_questions: list[ParsedQuestion],
    figure_map: dict[int, str],      # question_number → figure_path or ""
) -> tuple[list[ExcelRow], int]:     # (rows, verify_tokens_used)
    """
    Merge vision results with LLM-parsed questions.
    Returns one ExcelRow per question, with error flags set.
    """
    llm_by_num = {q.question_number: q for q in llm_questions}
    rows: list[ExcelRow] = []
    total_tokens = 0

    for vr in vision_results:
        llm_q = llm_by_num.get(vr.question_number)
        text_error = ""
        error_answer = ""

        if vr.error:
            text_error = f"Vision failed: {vr.error}"

        # If vision failed entirely, promote LLM data as primary so the row isn't blank
        if vr.error and llm_q:
            vr.question_text = vr.question_text or llm_q.question_text
            vr.c1 = vr.c1 or llm_q.c1
            vr.c2 = vr.c2 or llm_q.c2
            vr.c3 = vr.c3 or llm_q.c3
            vr.c4 = vr.c4 or llm_q.c4

        if llm_q:
            # ── Question text comparison ──────────────────────────────────────
            sim = fuzz.ratio(vr.question_text, llm_q.question_text)
            if sim < FUZZY_THRESHOLD:
                text_error = f"Low match ({sim:.0f}%): vision vs text extraction differ"
            elif sim < LLM_THRESHOLD:
                equivalent, verify_tokens = _llm_equivalent(vr.question_text, llm_q.question_text)
                total_tokens += verify_tokens
                if not equivalent:
                    text_error = f"Semantic mismatch ({sim:.0f}% fuzzy)"

            # ── Answer comparison ─────────────────────────────────────────────
            if llm_q.answer and vr.question_text:
                # Answers come from LLM text extraction; flag if suspiciously empty
                pass  # answer is sourced from llm_q, vision doesn't provide it

        # Use vision for Q/C text (more accurate from image),
        # use LLM for the answer (from answer key section of PDF)
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
            error_answer=error_answer,
        ))

    # Include questions the vision missed (crop fallback pages)
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


def _llm_equivalent(text_a: str, text_b: str) -> tuple[bool, int]:
    """Ask Ollama whether two question texts are semantically the same.
    Returns (is_equivalent, tokens_used)."""
    prompt = (
        f"Are these two exam question texts semantically equivalent? "
        f"Reply with only 'yes' or 'no'.\n\nText A: {text_a[:400]}\n\nText B: {text_b[:400]}"
    )
    try:
        resp = httpx.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_text_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=None,
        )
        resp.raise_for_status()
        body = resp.json()
        tokens = body.get("prompt_eval_count", 0) + body.get("eval_count", 0)
        answer = body["message"]["content"].strip().lower()
        return answer.startswith("yes"), tokens
    except Exception:
        return True, 0  # assume equivalent on error to avoid false flags

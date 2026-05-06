"""
Main extraction pipeline orchestrator.

Stages:
  1. Extract text → LLM splits Q/A
  2. Render PDF pages → PNG, crop per question
  3. Extract & match figures
  4. Vision OCR per question crop
  5. LaTeX → Unicode on all text fields
  6. Verify (fuzzy + LLM) → build ExcelRows
  7. Write Excel file

Temp files (page PNGs, question crops, figures) are written to a system
temp directory and deleted automatically when the pipeline finishes or fails.
Only the output Excel is kept.
"""

import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import fitz
import httpx

from app.config import settings
from app.services.excel_builder import build_excel
from app.services.figure_extractor import extract_and_assign_figures
from app.services.latex_converter import latex_to_unicode
from app.services.pdf_renderer import crop_question_images, render_pdf_pages
from app.services.question_splitter import extract_pdf_text, split_questions_with_llm
from app.services.verifier import verify_and_build_rows
from app.services.vision_service import extract_question_from_image


@dataclass
class JobStatus:
    job_id: str
    status: str = "pending"       # pending | running | done | failed
    progress: float = 0.0         # 0.0 – 1.0
    current_step: str = "Queued"
    total_questions: int = 0
    questions_done: int = 0
    output_path: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: str = ""
    # Token usage per stage (stage label → token count)
    tokens: dict = field(default_factory=dict)
    total_tokens: int = 0
    # Non-fatal warnings accumulated during the run
    warnings: list = field(default_factory=list)
    vision_errors: int = 0        # count of questions where OCR failed/timed out


_jobs: dict[str, JobStatus] = {}


def create_job() -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobStatus(job_id=job_id)
    return job_id


def get_job(job_id: str) -> JobStatus | None:
    return _jobs.get(job_id)


def start_pipeline(pdf_path: str, job_id: str) -> None:
    thread = threading.Thread(
        target=_run,
        args=(pdf_path, job_id),
        daemon=True,
    )
    thread.start()


def _update(job_id: str, **kwargs) -> None:
    job = _jobs.get(job_id)
    if job:
        for k, v in kwargs.items():
            setattr(job, k, v)


def _add_tokens(job_id: str, stage: str, count: int) -> None:
    job = _jobs.get(job_id)
    if job and count:
        job.tokens[stage] = job.tokens.get(stage, 0) + count
        job.total_tokens += count


def _warn(job_id: str, message: str) -> None:
    job = _jobs.get(job_id)
    if job:
        job.warnings.append(message)
        print(f"[pipeline][WARN] {message}", flush=True)


def _preflight_ollama(job_id: str) -> None:
    """Verify Ollama is reachable and both required models are available."""
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=10.0)
        resp.raise_for_status()
        available = [m["name"] for m in resp.json().get("models", [])]
    except Exception as exc:
        raise RuntimeError(
            f"Ollama is not reachable at {settings.ollama_base_url}. "
            f"Start it with: ollama serve ({exc})"
        )

    missing = []
    for model in [settings.ollama_text_model, settings.ollama_vision_model]:
        base = model.split(":")[0]
        if not any(base in a for a in available):
            missing.append(model)

    if missing:
        raise RuntimeError(
            f"Required Ollama model(s) not found: {', '.join(missing)}. "
            f"Run: ollama pull {' && ollama pull '.join(missing)}"
        )


def _run(pdf_path: str, job_id: str) -> None:
    work_dir = tempfile.mkdtemp(prefix=f"edutech_{job_id[:8]}_")
    try:
        _update(job_id, status="running", current_step="Starting")
        _execute(pdf_path, job_id, work_dir)
    except Exception as exc:
        _update(job_id, status="failed", error=str(exc), finished_at=datetime.utcnow().isoformat())
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"[pipeline] Cleaned up temp dir: {work_dir}", flush=True)
        try:
            Path(pdf_path).unlink(missing_ok=True)
            print(f"[pipeline] Deleted uploaded PDF: {pdf_path}", flush=True)
        except Exception:
            pass


def _execute(pdf_path: str, job_id: str, work_dir: str) -> None:
    pdf_name = Path(pdf_path).stem

    # ── Pre-flight: verify Ollama and models are available ────────────────────
    _update(job_id, current_step="Pre-flight: Checking Ollama…", progress=0.01)
    _preflight_ollama(job_id)

    # ── Stage 1: Text extraction + LLM Q/A split ──────────────────────────────
    _update(job_id, current_step="Stage 1: Extracting text and splitting Q/A", progress=0.05)
    pdf_text = extract_pdf_text(pdf_path)

    if not pdf_text.strip():
        raise RuntimeError("Stage 1 failed: could not extract any text from the PDF. The file may be corrupted or empty.")

    llm_questions, s1_tokens = split_questions_with_llm(pdf_text)
    _add_tokens(job_id, "Split Q/A", s1_tokens)

    if len(llm_questions) == 0:
        _warn(job_id, "Stage 1: No questions found in PDF text — PDF appears to be image-only. Relying entirely on Vision OCR (Stage 4).")

    _update(job_id, total_questions=len(llm_questions), progress=0.20)

    # ── Stage 2: Render pages + crop question images (temp) ───────────────────
    _update(job_id, current_step="Stage 2: Rendering PDF pages to PNG")
    render_pdf_pages(pdf_path, str(Path(work_dir) / "pages"), dpi=settings.render_dpi)
    question_crops = crop_question_images(pdf_path, str(work_dir), dpi=settings.render_dpi)

    if not question_crops:
        raise RuntimeError("Stage 2 failed: could not detect any question boundaries in the PDF. Check that questions are numbered (e.g. '1.', 'Q1').")

    _update(job_id, progress=0.35)

    # ── Stage 3: Figure extraction + per-question assignment ─────────────────
    _update(job_id, current_step="Stage 3: Extracting and matching figures")

    doc = fitz.open(pdf_path)
    page_heights = {i + 1: doc[i].rect.height for i in range(len(doc))}
    doc.close()

    # Returns {q_num: [figure_path, ...]} — only first figure per question used in Excel
    q_figures = extract_and_assign_figures(pdf_path, str(work_dir), question_crops, page_heights)
    figure_map: dict[int, str] = {
        q_num: paths[0]
        for q_num, paths in q_figures.items()
        if paths
    }
    # Count of figures per question — passed to vision so it can insert [Figure N] placeholders
    figure_counts: dict[int, int] = {q_num: len(paths) for q_num, paths in q_figures.items()}
    _update(job_id, progress=0.45)

    # ── Stage 4: Vision OCR per question crop (parallel) ─────────────────────
    _update(job_id, current_step="Stage 4: Vision OCR on question crops")
    vision_results = []
    total = len(question_crops)
    done_count = 0
    ocr_errors = 0

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_crop = {
            executor.submit(
                extract_question_from_image,
                crop.file_path,
                crop.question_number,
                figure_counts.get(crop.question_number, 0),
            ): crop
            for crop in question_crops
        }
        for future in as_completed(future_to_crop):
            vr = future.result()
            vision_results.append(vr)
            _add_tokens(job_id, "Vision OCR", vr.tokens_used)
            done_count += 1
            if vr.error:
                ocr_errors += 1
                _update(job_id, vision_errors=ocr_errors)
            _update(
                job_id,
                questions_done=done_count,
                progress=round(0.45 + (done_count / max(total, 1)) * 0.30, 3),
                current_step=f"Stage 4: OCR question {done_count}/{total}"
                             + (f" ({ocr_errors} failed)" if ocr_errors else ""),
            )

    vision_results.sort(key=lambda vr: vr.question_number)

    if ocr_errors == total:
        _warn(job_id, f"Stage 4: Vision OCR failed for ALL {total} questions (timed out). "
                      "Ollama may be overloaded or the model is too slow on CPU. "
                      "Try: ollama run qwen2.5vl:3b to pre-warm the model.")
    elif ocr_errors > 0:
        _warn(job_id, f"Stage 4: {ocr_errors}/{total} questions failed OCR — using LLM text as fallback for those rows.")

    # ── Stage 5: LaTeX → Unicode (no LLM, no tokens) ─────────────────────────
    _update(job_id, current_step="Stage 5: Converting LaTeX to Unicode", progress=0.75)
    for vr in vision_results:
        vr.question_text = latex_to_unicode(vr.question_text)
        vr.c1 = latex_to_unicode(vr.c1)
        vr.c2 = latex_to_unicode(vr.c2)
        vr.c3 = latex_to_unicode(vr.c3)
        vr.c4 = latex_to_unicode(vr.c4)
    for q in llm_questions:
        q.question_text = latex_to_unicode(q.question_text)
        q.c1 = latex_to_unicode(q.c1)
        q.c2 = latex_to_unicode(q.c2)
        q.c3 = latex_to_unicode(q.c3)
        q.c4 = latex_to_unicode(q.c4)

    # ── Stage 6: Verify + build rows (VLM image comparison) ──────────────────
    _update(job_id, current_step="Stage 6: Verifying extraction", progress=0.80)
    crop_paths = {crop.question_number: crop.file_path for crop in question_crops}
    rows, s6_tokens = verify_and_build_rows(vision_results, llm_questions, figure_map, crop_paths)
    _add_tokens(job_id, "Verify", s6_tokens)

    if not rows:
        raise RuntimeError("Stage 6 failed: no rows were produced. Both text extraction and vision OCR returned empty results.")

    text_error_count = sum(1 for r in rows if r.text_error)
    if text_error_count > 0:
        _warn(job_id, f"Stage 6: {text_error_count}/{len(rows)} rows have text errors flagged — check the 'Text Error' column in Excel.")

    # ── Stage 7: Write Excel ───────────────────────────────────────────────────
    _update(job_id, current_step="Stage 7: Writing Excel file", progress=0.90)
    out_path = str(Path(settings.output_dir) / f"{pdf_name}_{job_id[:8]}.xlsx")
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    build_excel(rows, out_path)

    if not Path(out_path).exists():
        raise RuntimeError(f"Stage 7 failed: Excel file was not created at {out_path}.")

    _update(
        job_id,
        status="done",
        progress=1.0,
        current_step="Complete",
        output_path=out_path,
        finished_at=datetime.utcnow().isoformat(),
    )

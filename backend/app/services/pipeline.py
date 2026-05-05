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

from app.config import settings
from app.services.excel_builder import build_excel
from app.services.figure_extractor import extract_figures, match_figures_to_questions
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

    # ── Stage 1: Text extraction + LLM Q/A split ──────────────────────────────
    _update(job_id, current_step="Stage 1: Extracting text and splitting Q/A", progress=0.05)
    pdf_text = extract_pdf_text(pdf_path)
    llm_questions, s1_tokens = split_questions_with_llm(pdf_text)
    _add_tokens(job_id, "Split Q/A", s1_tokens)
    _update(job_id, total_questions=len(llm_questions), progress=0.20)

    # ── Stage 2: Render pages + crop question images (temp) ───────────────────
    _update(job_id, current_step="Stage 2: Rendering PDF pages to PNG")
    render_pdf_pages(pdf_path, str(Path(work_dir) / "pages"), dpi=settings.render_dpi)
    question_crops = crop_question_images(pdf_path, str(work_dir), dpi=settings.render_dpi)
    _update(job_id, progress=0.35)

    # ── Stage 3: Figure extraction + matching (temp) ──────────────────────────
    _update(job_id, current_step="Stage 3: Extracting and matching figures")
    figures = extract_figures(pdf_path, str(work_dir))

    doc = fitz.open(pdf_path)
    page_heights = {i + 1: doc[i].rect.height for i in range(len(doc))}
    doc.close()

    figures = match_figures_to_questions(figures, question_crops, page_heights)
    figure_map: dict[int, str] = {
        f.matched_question: f.file_path
        for f in figures
        if f.matched_question is not None
    }
    _update(job_id, progress=0.45)

    # ── Stage 4: Vision OCR per question crop (parallel) ─────────────────────
    _update(job_id, current_step="Stage 4: Vision OCR on question crops")
    vision_results = []
    total = len(question_crops)
    done_count = 0

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_crop = {
            executor.submit(extract_question_from_image, crop.file_path, crop.question_number): crop
            for crop in question_crops
        }
        for future in as_completed(future_to_crop):
            vr = future.result()
            vision_results.append(vr)
            _add_tokens(job_id, "Vision OCR", vr.tokens_used)
            done_count += 1
            _update(
                job_id,
                questions_done=done_count,
                progress=round(0.45 + (done_count / max(total, 1)) * 0.30, 3),
                current_step=f"Stage 4: OCR question {done_count}/{total}",
            )

    vision_results.sort(key=lambda vr: vr.question_number)

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

    # ── Stage 6: Verify + build rows ──────────────────────────────────────────
    _update(job_id, current_step="Stage 6: Verifying extraction", progress=0.80)
    rows, s6_tokens = verify_and_build_rows(vision_results, llm_questions, figure_map)
    _add_tokens(job_id, "Verify", s6_tokens)

    # ── Stage 7: Write Excel ───────────────────────────────────────────────────
    _update(job_id, current_step="Stage 7: Writing Excel file", progress=0.90)
    out_path = str(Path(settings.output_dir) / f"{pdf_name}_{job_id[:8]}.xlsx")
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    build_excel(rows, out_path)

    _update(
        job_id,
        status="done",
        progress=1.0,
        current_step="Complete",
        output_path=out_path,
        finished_at=datetime.utcnow().isoformat(),
    )

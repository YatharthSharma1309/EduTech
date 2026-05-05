"""
API Routes

POST /api/extract          — upload PDF, start background extraction, return job_id
GET  /api/jobs/{job_id}    — poll job progress
GET  /api/download/{job_id} — download the output Excel once done
"""

import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.services.pipeline import create_job, get_job, start_pipeline

router = APIRouter()


@router.post("/extract", summary="Upload a PDF and start extraction pipeline")
def extract(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    upload_dir = Path(settings.pdf_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = upload_dir / file.filename

    with open(pdf_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    job_id = create_job()
    # pdf_path is passed to pipeline; pipeline deletes it after processing
    start_pipeline(str(pdf_path), job_id)

    return {
        "job_id": job_id,
        "pdf": file.filename,
        "status": "pending",
        "message": "Pipeline started. Poll /api/jobs/{job_id} for progress.",
    }


@router.get("/jobs/{job_id}", summary="Poll extraction job progress")
def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "current_step": job.current_step,
        "total_questions": job.total_questions,
        "questions_done": job.questions_done,
        "output_path": job.output_path,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


@router.get("/download/{job_id}", summary="Download the output Excel file")
def download(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done":
        raise HTTPException(status_code=400, detail=f"Job not complete (status: {job.status})")
    if not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        path=job.output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(job.output_path).name,
    )

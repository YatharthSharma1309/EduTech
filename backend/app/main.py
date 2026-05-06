from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
import os

app = FastAPI(title="EduTech PDF Extractor", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Only persist upload dir (PDFs deleted post-processing) and output dir (Excel files)
os.makedirs(settings.pdf_upload_dir, exist_ok=True)
os.makedirs(settings.output_dir, exist_ok=True)

# Serve completed Excel files for download
app.mount("/outputs", StaticFiles(directory=settings.output_dir), name="outputs")

app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "healthy"}

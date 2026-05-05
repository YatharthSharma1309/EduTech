from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
import os

app = FastAPI(title="EduTech PDF Extractor", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(settings.pdf_upload_dir, exist_ok=True)
os.makedirs(settings.image_dir, exist_ok=True)
os.makedirs(settings.output_dir, exist_ok=True)

app.mount("/images", StaticFiles(directory=settings.image_dir), name="images")
app.mount("/outputs", StaticFiles(directory=settings.output_dir), name="outputs")

app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "healthy"}

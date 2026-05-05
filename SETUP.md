# EduTech PDF Extractor — Setup Guide

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | |
| Node.js | 18+ | |
| Ollama | 0.23.0 | https://ollama.com |

---

## 1. Pull Ollama Models

```bash
ollama pull llama3.2          # text model — splits Q/A from PDF text
ollama pull qwen2.5vl:7b      # vision model — OCR on question images
```

Make sure Ollama is running before starting the backend:
```bash
ollama serve
```

---

## 2. Backend Setup

```powershell
cd backend

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate           # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env               # Windows
# cp .env.example .env               # Mac/Linux

# Start the API server
uvicorn app.main:app --reload --port 8000
```

API available at: http://localhost:8000
Interactive docs: http://localhost:8000/docs

---

## 3. Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

Frontend available at: http://localhost:3000

---

## 4. Run an Extraction

Upload a PDF via the browser UI at http://localhost:3000, or call the API directly:

```bash
curl -X POST http://localhost:8000/api/extract \
  -F "file=@CFPQ_Maths10.pdf"
```

Poll for progress:
```bash
curl http://localhost:8000/api/jobs/{job_id}
```

Download the Excel output:
```
GET http://localhost:8000/api/download/{job_id}
```

---

## Project Structure

```
EduTech/
├── CFPQ_Maths10 (1).pdf          ← Sample exam PDF
├── SETUP.md
├── README.md
│
├── backend/
│   ├── venv/                         ← Python virtual environment (git-ignored)
│   ├── app/
│   │   ├── main.py               ← FastAPI app entry point
│   │   ├── config.py             ← Settings (Ollama URLs, dirs, DPI)
│   │   ├── api/
│   │   │   └── routes.py         ← POST /extract, GET /jobs/{id}, GET /download/{id}
│   │   └── services/
│   │       ├── pipeline.py       ← Orchestrates all 7 stages
│   │       ├── pdf_renderer.py   ← PDF pages to PNG + question crops
│   │       ├── question_splitter.py ← LLM separates Q/A from text
│   │       ├── figure_extractor.py  ← Extracts figures, matches to questions
│   │       ├── vision_service.py    ← Ollama qwen2.5vl OCR per question crop
│   │       ├── latex_converter.py   ← LaTeX to Unicode conversion
│   │       ├── excel_builder.py     ← Writes output Excel file
│   │       └── verifier.py          ← Fuzzy + LLM cross-check
│   ├── uploads/
│   │   ├── pdfs/                 ← Uploaded PDFs saved here
│   │   └── images/               ← Rendered page PNGs + question crops
│   ├── outputs/                  ← Generated Excel files
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/
    └── src/
        ├── app/
        │   ├── page.tsx          ← Main extraction UI
        │   └── layout.tsx
        ├── components/
        │   └── UploadPanel.tsx   ← Upload → progress → download Excel
        └── lib/
            └── api.ts            ← uploadPdf, pollJob, downloadUrl
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/extract` | Upload PDF, start extraction pipeline |
| GET | `/api/jobs/{job_id}` | Poll pipeline progress (0.0 to 1.0) |
| GET | `/api/download/{job_id}` | Download the output Excel file |
| GET | `/health` | Server health check |

---

## Excel Output Format

| Column | Content |
|--------|---------|
| Fig | Embedded figure image (if matched) |
| Q | Question text (Unicode, no LaTeX) |
| C1 | Choice 1 |
| C2 | Choice 2 |
| C3 | Choice 3 |
| C4 | Choice 4 |
| A | Correct answer |
| Text Error | Flagged OCR/extraction issues |
| Error Answer | Flagged answer issues |

---

## Pipeline Stages

```
PDF uploaded
  │
  ├─ Stage 1: LLM (llama3.2) reads text, splits questions from answers
  ├─ Stage 2: PyMuPDF renders pages to PNG, crops one image per question
  ├─ Stage 3: Embedded figures extracted, matched to questions by y-position
  ├─ Stage 4: Vision model (qwen2.5vl) OCRs each question crop
  ├─ Stage 5: LaTeX to Unicode conversion on all text fields
  ├─ Stage 6: Fuzzy + LLM verification, error flags written
  └─ Stage 7: Excel file written, available for download
```

---

## Environment Variables (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_TEXT_MODEL` | `llama3.2` | Model for Q/A splitting and verification |
| `OLLAMA_VISION_MODEL` | `qwen2.5vl:7b` | Vision model for question OCR |
| `PDF_UPLOAD_DIR` | `uploads/pdfs` | Where uploaded PDFs are saved |
| `IMAGE_DIR` | `uploads/images` | Where rendered PNGs are saved |
| `OUTPUT_DIR` | `outputs` | Where Excel files are saved |
| `RENDER_DPI` | `150` | PDF render resolution (higher = better OCR, slower) |

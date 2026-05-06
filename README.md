# EduTech PDF Extractor

Extracts questions, choices, figures, and answers from exam PDFs and exports them to a structured Excel file.

## How It Works

Upload a single exam PDF (questions and answers in the same file). The pipeline automatically:

1. **Splits Q/A** — LLM reads the full PDF text and separates questions from answers
2. **Renders images** — each question is cropped to its own PNG for accurate OCR
3. **Matches figures** — embedded diagrams are extracted and linked to their question by position
4. **Vision OCR** — Ollama vision model reads each question crop and extracts structured text
5. **LaTeX → Unicode** — math notation converted to readable Unicode symbols
6. **Verifies** — fuzzy + LLM cross-check between text extraction and vision OCR flags errors
7. **Exports Excel** — one row per question: Fig, Q, C1, C2, C3, C4, A, Text Error, Error Answer

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, PyMuPDF, httpx |
| LLM (text) | Ollama — qwen2.5:3b |
| LLM (vision) | Ollama — qwen2.5vl:3b |
| Output | openpyxl (Excel) |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |

## Quick Start

See [SETUP.md](SETUP.md) for full setup instructions.

```powershell
# Backend
cd backend
EduTech\Scripts\uvicorn app.main:app --reload

# Frontend
cd frontend
npm run dev
```

Open http://localhost:3000, upload a PDF, and download the Excel when done.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/extract` | Upload PDF, start extraction |
| `GET` | `/api/jobs/{id}` | Poll progress |
| `GET` | `/api/download/{id}` | Download Excel output |
| `GET` | `/health` | Health check |

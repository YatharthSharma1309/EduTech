.PHONY: help backend frontend models

help:
	@echo ""
	@echo "  EduTech PDF Extractor — available commands"
	@echo ""
	@echo "  make models     Pull required Ollama models"
	@echo "  make backend    Start the FastAPI backend (port 8000)"
	@echo "  make frontend   Start the Next.js frontend (port 3000)"
	@echo ""

models:
	ollama pull qwen2.5:3b
	ollama pull qwen2.5vl:3b

backend:
	cd backend && venv\Scripts\uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

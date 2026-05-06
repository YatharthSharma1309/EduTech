.PHONY: help setup dev build stop restart logs pull-models clean

help:
	@echo ""
	@echo "  EduTech PDF Extractor — available commands"
	@echo ""
	@echo "  make setup        Copy .env.example → .env (first-time setup)"
	@echo "  make dev          Start all services (builds if needed)"
	@echo "  make build        Rebuild Docker images"
	@echo "  make stop         Stop all services"
	@echo "  make restart      Stop then start"
	@echo "  make pull-models  Pull Ollama models into running container"
	@echo "  make logs         Tail logs from all services"
	@echo "  make clean        Remove containers, images, volumes"
	@echo ""

setup:
	@test -f .env || (cp .env.example .env && echo ".env created — edit if needed")

dev: setup
	docker compose up --build -d
	@echo ""
	@echo "  Frontend  → http://localhost:$${FRONTEND_PORT:-3000}"
	@echo "  Backend   → http://localhost:$${BACKEND_PORT:-8000}"
	@echo "  API docs  → http://localhost:$${BACKEND_PORT:-8000}/docs"
	@echo "  Ollama    → http://localhost:11434"
	@echo ""
	@echo "  Models are being pulled in the background (ollama-init)."
	@echo "  Run 'make logs' to monitor progress."

build:
	docker compose build --no-cache

stop:
	docker compose down

restart: stop dev

pull-models:
	docker compose exec ollama ollama pull llama3.2
	docker compose exec ollama ollama pull qwen2.5vl:3b

logs:
	docker compose logs -f

clean:
	docker compose down --rmi all --volumes --remove-orphans

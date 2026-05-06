FROM python:3.11-slim

WORKDIR /app

# curl is needed for the docker-compose healthcheck only
# PyMuPDF ships its own bundled MuPDF — no system libmupdf needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p uploads/pdfs outputs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

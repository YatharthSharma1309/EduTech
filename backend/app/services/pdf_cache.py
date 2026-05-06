"""
PDF Preprocessing Cache

Stores the output of Stages 1–3 (text split, question crops, figures) keyed
by the SHA-256 hash of the uploaded PDF. Re-uploads of the same file skip all
three stages and jump straight to Stage 4 (Vision OCR).

Layout on disk:
  backend/cache/
    <sha256>/
      meta.json          — LLM questions + crop metadata + page heights
      questions/         — one PNG per question crop
      figures/           — extracted figure PNGs

Cache is LRU-evicted when it exceeds MAX_ENTRIES (oldest by mtime removed).
"""

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from app.config import settings


def pdf_sha256(pdf_path: str) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry(sha: str) -> Path:
    return Path(settings.cache_dir) / sha


def is_cached(sha: str) -> bool:
    return (_entry(sha) / "meta.json").exists()


def load_cache(sha: str, work_dir: str):
    """
    Copy cached crops + figures into work_dir and reconstruct the
    service objects so the rest of the pipeline sees no difference.

    Returns (llm_questions, question_crops, q_figures, page_heights).
    """
    from app.services.pdf_renderer import QuestionCrop
    from app.services.question_splitter import ParsedQuestion

    entry = _entry(sha)
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))

    q_dir = Path(work_dir) / "questions"
    fig_dir = Path(work_dir) / "figures"
    q_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Restore question crops with work_dir-local paths
    crops = []
    for c in meta["crops"]:
        fname = Path(c["cached_filename"])
        src = entry / "questions" / fname
        dst = q_dir / fname
        shutil.copy2(src, dst)
        crops.append(QuestionCrop(
            question_number=c["question_number"],
            page_number=c["page_number"],
            file_path=str(dst),
            y_top=c["y_top"],
            y_bottom=c["y_bottom"],
        ))

    # Restore figure paths
    q_figures: dict[int, list[str]] = {}
    for q_num_str, fnames in meta["q_figures"].items():
        q_num = int(q_num_str)
        q_figures[q_num] = []
        for fname in fnames:
            src = entry / "figures" / fname
            dst = fig_dir / fname
            shutil.copy2(src, dst)
            q_figures[q_num].append(str(dst))

    llm_questions = [ParsedQuestion(**q) for q in meta["llm_questions"]]
    page_heights = {int(k): float(v) for k, v in meta["page_heights"].items()}

    # Touch the entry so LRU eviction sees it as recently used
    (entry / "meta.json").touch()

    return llm_questions, crops, q_figures, page_heights


def save_cache(sha: str, llm_questions, question_crops, q_figures: dict, page_heights: dict) -> None:
    """
    Persist Stages 1–3 output. Copies crop + figure PNGs into the cache
    directory so they survive work_dir cleanup.
    """
    _evict_if_needed()

    entry = _entry(sha)
    q_dir = entry / "questions"
    fig_dir = entry / "figures"
    q_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Save crops — store only the filename, not the full temp path
    cached_crops = []
    for crop in question_crops:
        fname = Path(crop.file_path).name
        shutil.copy2(crop.file_path, q_dir / fname)
        cached_crops.append({
            "question_number": crop.question_number,
            "page_number": crop.page_number,
            "cached_filename": fname,
            "y_top": crop.y_top,
            "y_bottom": crop.y_bottom,
        })

    # Save figures — keyed by question number, list of filenames
    cached_figures: dict[str, list[str]] = {}
    for q_num, paths in q_figures.items():
        fnames = []
        for p in paths:
            fname = Path(p).name
            shutil.copy2(p, fig_dir / fname)
            fnames.append(fname)
        cached_figures[str(q_num)] = fnames

    meta = {
        "llm_questions": [asdict(q) for q in llm_questions],
        "crops": cached_crops,
        "q_figures": cached_figures,
        "page_heights": {str(k): v for k, v in page_heights.items()},
    }
    (entry / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _evict_if_needed() -> None:
    cache_root = Path(settings.cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    entries = sorted(
        (p for p in cache_root.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    while len(entries) >= settings.cache_max_entries:
        shutil.rmtree(entries.pop(0), ignore_errors=True)

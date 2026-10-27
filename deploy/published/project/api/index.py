"""Vercel's ASGI app. No Uvicorn listener, subprocess or database at import."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "application"
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
from app.vercel_runtime import create_vercel_app

app = create_vercel_app()

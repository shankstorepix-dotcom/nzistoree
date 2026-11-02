"""Vercel Serverless WSGI Entrypoint — routes 100% of traffic through the Flask backend."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import create_app

app = create_app()

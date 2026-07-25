"""uvicorn 진입점: `uvicorn herongs.main:app --host 0.0.0.0 --port 8000`."""

from .api.app import create_app

app = create_app()

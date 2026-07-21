"""Start the Invoice Processing Automation app (backend + frontend in one process).

Usage:  python main.py          (then open http://127.0.0.1:8000)
        Set PORT in .env or the environment if 8000 is taken.
"""

import os

import uvicorn

from app import config  # noqa: F401  - loads .env before reading PORT

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"Invoice Processing Automation -> http://127.0.0.1:{port}")
    uvicorn.run("app.api:app", host="127.0.0.1", port=port)

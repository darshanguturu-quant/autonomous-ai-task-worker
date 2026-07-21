"""Project paths and environment configuration."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Runtime data: what the live app actually reads/writes. Starts empty and
# only ever contains real uploads and real run history - never fabricated
# content.
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "runs.db"

# Fabricated test fixtures (synthetic invoices + a mock vendor/PO dataset),
# used only by scripts/generate_test_data.py and the automated test suite.
# The running app (app/api.py, app/db.py at import/runtime) never reads from
# here - no fabricated data ships inside the product.
FIXTURES_DIR = ROOT / "fixtures"
FIXTURE_INVOICE_DIR = FIXTURES_DIR / "invoices"


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# Vision-capable Groq model for scanned-invoice extraction (override in .env).
# qwen3.6-27b is the vision-capable model on Groq's current lineup (verified live);
# it is a reasoning model, so vision.py hides its thinking via reasoning_format.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b")

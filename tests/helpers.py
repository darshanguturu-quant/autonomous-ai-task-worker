"""Shared test-only helpers: paths to the fabricated fixture data, and a
helper that uploads a fixture PDF through the real /api/invoices endpoint -
the only ingestion path the running app actually has. Tests exercise the
product exactly as a user would; only the input files themselves are
fabricated test data (per the case-study brief: "create your own test
inputs... make a few realistic invoice PDFs and a PO dataset")."""

from app.config import FIXTURES_DIR, FIXTURE_INVOICE_DIR

__all__ = ["FIXTURES_DIR", "FIXTURE_INVOICE_DIR", "upload_fixture"]


def upload_fixture(client, filename: str, *, defer: bool = False) -> dict:
    """POST a fixture invoice PDF to /api/invoices, exactly as a real upload
    would arrive. Returns the parsed JSON response."""
    content = (FIXTURE_INVOICE_DIR / filename).read_bytes()
    url = "/api/invoices?defer=1" if defer else "/api/invoices"
    r = client.post(url, files={"file": (filename, content, "application/pdf")})
    return r.json()

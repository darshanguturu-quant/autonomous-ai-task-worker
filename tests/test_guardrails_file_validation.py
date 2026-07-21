"""GUARDRAIL 1 - file input validation: reject bad uploads before they ever
reach extraction, and sanitize filenames before they're stored or displayed."""

import re

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.config import FIXTURE_INVOICE_DIR
from app.guardrails.file_validation import (
    MAX_UPLOAD_SIZE_BYTES,
    FileValidationError,
    sanitize_filename,
    validate_upload,
)


def test_sanitize_filename_strips_path_components():
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("..\\..\\evil.pdf") == "evil.pdf"


def test_sanitize_filename_strips_leading_dots():
    assert sanitize_filename(".hidden.pdf") == "hidden.pdf"


def test_sanitize_filename_only_produces_safe_characters():
    result = sanitize_filename("my invoice #1 (final)!.pdf")
    assert result.endswith(".pdf")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", result)


def test_validate_upload_rejects_non_pdf_extension():
    with pytest.raises(FileValidationError, match="PDF"):
        validate_upload("invoice.exe", b"%PDF-1.4 fake")


def test_validate_upload_rejects_empty_file():
    with pytest.raises(FileValidationError, match="empty"):
        validate_upload("invoice.pdf", b"")


def test_validate_upload_rejects_oversized_file():
    with pytest.raises(FileValidationError, match="exceeds"):
        validate_upload("invoice.pdf", b"%PDF-" + b"0" * (MAX_UPLOAD_SIZE_BYTES + 1))


def test_validate_upload_rejects_missing_pdf_magic_bytes():
    with pytest.raises(FileValidationError, match="valid PDF"):
        validate_upload("invoice.pdf", b"this is not really a pdf")


def test_validate_upload_accepts_a_real_pdf():
    content = (FIXTURE_INVOICE_DIR / "INV-2026-0847_acme.pdf").read_bytes()
    validate_upload("INV-2026-0847_acme.pdf", content)  # must not raise


# --- API-level integration: the endpoint rejects before a run is ever created ---

def test_api_rejects_non_pdf_upload():
    with TestClient(app) as c:
        r = c.post("/api/invoices", files={"file": ("invoice.txt", b"hello", "text/plain")})
        assert r.status_code == 400
        assert c.get("/api/runs").json() == []  # no run was created


def test_api_rejects_corrupt_pdf_before_extraction():
    with TestClient(app) as c:
        r = c.post("/api/invoices",
                   files={"file": ("invoice.pdf", b"not a real pdf", "application/pdf")})
        assert r.status_code == 400
        assert "valid PDF" in r.json()["detail"]
        assert c.get("/api/runs").json() == []


def test_api_rejects_empty_upload():
    with TestClient(app) as c:
        r = c.post("/api/invoices", files={"file": ("invoice.pdf", b"", "application/pdf")})
        assert r.status_code == 400
        assert "empty" in r.json()["detail"]


def test_api_sanitizes_filename_before_storing_and_displaying():
    with TestClient(app) as c:
        content = (FIXTURE_INVOICE_DIR / "INV-8613_meridian.pdf").read_bytes()
        r = c.post("/api/invoices",
                   files={"file": ("../../evil name!.pdf", content, "application/pdf")})
        assert r.status_code == 200
        stored_filename = c.get("/api/runs").json()[0]["filename"]
        assert "/" not in stored_filename and ".." not in stored_filename
        assert stored_filename == "evil_name_.pdf"

"""GUARDRAIL 1 - FILE INPUT VALIDATION.

Runs before a single byte of an upload reaches extraction. Three checks, in
this order: is it actually a PDF (extension + magic bytes), is it within the
size cap, is it non-empty. `validate_upload` raises with a clear, already
user-facing reason on the first check that fails.

`sanitize_filename` is applied before a filename is ever written to disk,
stored in the database, or echoed back to the client - it strips any
directory component and collapses everything outside a safe whitelist, so a
crafted filename can never be used for path traversal or markup injection in
the UI.
"""

import re
from pathlib import PurePosixPath

MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB - generous for a scanned invoice, blocks abuse
PDF_MAGIC = b"%PDF-"


class FileValidationError(Exception):
    """Raised for any upload that fails a file-layer guardrail. The message
    is already clean and safe to show directly in the UI."""


def sanitize_filename(name: str) -> str:
    """Collapse a filename to a safe basename: no directory components, no
    characters outside [A-Za-z0-9._-], no leading dots, bounded length."""
    name = PurePosixPath(name.replace("\\", "/")).name  # drop any directory part (incl. ../..)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    name = name.lstrip(".") or "upload.pdf"  # no leading dots (hidden files / bare "..")
    return name[:200]


def validate_upload(filename: str | None, content: bytes) -> None:
    """Raise FileValidationError with a clear, user-facing reason on any
    failure. Must be called before the file is written to disk or handed to
    the extraction stage."""
    if not filename or not filename.lower().endswith(".pdf"):
        raise FileValidationError("only PDF files are accepted (expected a .pdf upload)")
    if not content:
        raise FileValidationError("uploaded file is empty")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise FileValidationError(
            f"file is {len(content) / 1_048_576:.1f} MB, which exceeds the "
            f"{MAX_UPLOAD_SIZE_BYTES // 1_048_576} MB upload limit"
        )
    if not content.startswith(PDF_MAGIC):
        raise FileValidationError(
            "file does not look like a valid PDF (missing %PDF header) - it may be "
            "corrupt or mislabeled"
        )

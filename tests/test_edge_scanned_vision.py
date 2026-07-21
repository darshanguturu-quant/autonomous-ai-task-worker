"""Edge case: scanned/image-only invoice -> vision extraction path (Groq).

The live test runs only when GROQ_API_KEY is configured (it makes a real
API call). Until then it is skipped - and test_api.py separately pins that
without a key the scanned invoice fails loudly rather than silently.
"""

import pytest

from app.config import FIXTURE_INVOICE_DIR, GROQ_API_KEY
from app.pipeline.run import run_pipeline_collect

SCANNED = FIXTURE_INVOICE_DIR / "INV-3847_brightway_scanned.pdf"

requires_key = pytest.mark.skipif(
    not GROQ_API_KEY, reason="GROQ_API_KEY not set - vision path needs it"
)


@requires_key
def test_scanned_invoice_extracts_via_vision_and_approves():
    final = run_pipeline_collect(SCANNED)
    assert final["status"] == "completed", final.get("error")
    result = final["result"]

    ex = result["extract"]
    assert ex["method"] == "vision"  # the trace shows which extraction path ran
    assert ex["extraction_confidence"] > 0

    f = ex["fields"]
    assert f["invoice_number"]["value"] == "INV-3847"
    assert f["po_ref"]["value"] == "PO-7860"
    assert f["total"]["value"] == 1850.00
    assert all("vision" in f[name]["source"] for name in ("invoice_number", "total"))

    assert result["validate"]["passed"]
    assert result["match"]["po_match"]["po_number"] == "PO-7860"
    assert result["decide"]["decision"] == "auto_approve"

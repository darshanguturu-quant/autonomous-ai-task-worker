"""GUARDRAIL 3 - LLM output validation for the vision path: a Groq reply that
fails Pydantic validation twice (even after a self-correcting retry) must
degrade to a zero-confidence result that Validate/Decide route to Needs
Review ("extraction confidence low") - never an unhandled crash / 500."""

from app.config import FIXTURE_INVOICE_DIR
from app.pipeline import vision

SCANNED_PDF = FIXTURE_INVOICE_DIR / "INV-3847_brightway_scanned.pdf"


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


def test_malformed_json_after_retry_degrades_to_needs_review(monkeypatch):
    monkeypatch.setattr(vision.config, "GROQ_API_KEY", "fake-key-for-test")
    # Every call (initial + the one self-correcting retry) returns garbage.
    monkeypatch.setattr(
        vision, "_completion_with_backoff",
        lambda client, messages, pdf_name: _FakeResponse("not valid json at all"),
    )

    result = vision.extract_via_vision(SCANNED_PDF, text_chars=0)

    assert result["method"] == "vision"
    assert result["extraction_confidence"] == 0.0
    assert any("extraction confidence low" in w for w in result["warnings"])
    # every field degrades cleanly - no exception, no partial/garbage data
    assert all(f["value"] is None for f in result["fields"].values())


def test_vision_currency_is_not_defaulted_when_model_returns_null(monkeypatch):
    from app.pipeline.vision import FieldConfidence, LineItem, VisionExtraction, _to_result

    extraction = VisionExtraction(
        vendor_name="Example Vendor",
        invoice_number="INV-1",
        invoice_date="2026-10-01",
        due_date=None,
        po_ref=None,
        subtotal=100.0,
        tax=0.0,
        tax_rate=None,
        total=100.0,
        currency=None,
        line_items=[LineItem(description="Service", qty=1, unit_price=100.0, amount=100.0)],
        field_confidence=FieldConfidence(
            vendor_name=0.9, invoice_number=0.9, invoice_date=0.9, due_date=0,
            po_ref=0, subtotal=0.9, tax=0.9, total=0.9, currency=0,
        ),
    )
    result = _to_result(extraction, text_chars=0, num_pages=1, render={
        "dpi": 100, "quality": 60, "kb": 10, "estimated_tokens": 1000,
    })

    assert result["fields"]["currency"]["value"] is None
    assert result["fields"]["currency"]["confidence"] == 0.0


def test_degraded_vision_result_routes_to_needs_review_through_the_full_pipeline(monkeypatch):
    from app.pipeline import decide as decide_mod
    from app.pipeline import guardrails as guardrails_mod
    from app.pipeline import match as match_mod
    from app.pipeline import validate as validate_mod

    monkeypatch.setattr(vision.config, "GROQ_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(
        vision, "_completion_with_backoff",
        lambda client, messages, pdf_name: _FakeResponse("not valid json at all"),
    )
    extract = vision.extract_via_vision(SCANNED_PDF, text_chars=0)

    guardrails_out = guardrails_mod.screen(extract)
    validation = validate_mod.validate(extract)
    m = match_mod.match(extract)
    d = decide_mod.decide(extract, validation, m, guardrails_result=guardrails_out)

    assert not validation["passed"]  # required fields all missing
    assert d["decision"] == "needs_review"  # never a crash, never auto-approved

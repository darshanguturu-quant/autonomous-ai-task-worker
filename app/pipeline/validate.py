"""Stage 2 - VALIDATE: are the extracted fields complete and internally consistent?

Pure checks, no lookups. Output is a list of named checks with pass/fail and
a human-readable detail line each - rendered verbatim in the run view.

Validation FAILS only on missing required fields or broken arithmetic.
Low confidence does not fail validation; it is surfaced as an issue that the
Decide stage routes on (a scan extracted by vision should not "fail", it
should be decided with appropriate caution).
"""

from app.guardrails.output_bounds import check_amount_bounds

CENTS = 0.011  # float-safe tolerance for money arithmetic
REQUIRED_FIELDS = ("invoice_number", "vendor_name", "invoice_date", "total")
LOW_FIELD_CONFIDENCE = 0.60


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "passed": passed, "detail": detail}


def validate(extract_result: dict) -> dict:
    fields = extract_result["fields"]
    checks: list[dict] = []
    issues: list[str] = []

    # 1. Required fields
    for name in REQUIRED_FIELDS:
        value = fields.get(name, {}).get("value")
        checks.append(_check(
            f"required_field:{name}",
            value is not None,
            f"{name} = {value!r}" if value is not None else f"{name} is missing",
        ))

    subtotal = fields["subtotal"]["value"]
    tax = fields["tax"]["value"]
    total = fields["total"]["value"]

    # 2. Totals reconcile: subtotal + tax = total (missing tax treated as 0)
    if subtotal is not None and total is not None:
        effective_tax = tax if tax is not None else 0.0
        diff = round(abs(subtotal + effective_tax - total), 2)
        note = " (no tax line - treated as 0.00)" if tax is None else ""
        checks.append(_check(
            "totals_reconcile",
            diff <= CENTS,
            f"subtotal {subtotal:,.2f} + tax {effective_tax:,.2f} vs total {total:,.2f} "
            f"-> difference {diff:,.2f}{note}",
        ))
    else:
        checks.append(_check("totals_reconcile", False, "cannot reconcile: subtotal or total missing"))

    # 3. Line items sum to subtotal (only when both sides exist)
    items = extract_result["line_items"]
    if items and subtotal is not None:
        items_sum = round(sum(li["amount"] for li in items), 2)
        checks.append(_check(
            "line_items_sum",
            abs(items_sum - subtotal) <= CENTS,
            f"{len(items)} line items sum to {items_sum:,.2f} vs subtotal {subtotal:,.2f}",
        ))
    elif not items:
        issues.append("no line items parsed - amounts rely on the totals block only")

    # 4. Sanity bounds on extracted amounts (GUARDRAIL 3 - never trust a raw
    # number, whether it came from regex or a vision LLM call, without a
    # bounds check: no negative totals, no absurd amounts like $1B on an
    # office-supplies invoice).
    bound_issues = check_amount_bounds(fields)
    checks.append(_check(
        "amount_sanity_bounds",
        not bound_issues,
        "all amounts within sane bounds" if not bound_issues
        else "; ".join(i["reason"] for i in bound_issues),
    ))

    # 5. Confidence flags (issues, not failures)
    if extract_result["extraction_confidence"] < 0.70:
        issues.append(
            f"low overall extraction confidence ({extract_result['extraction_confidence']:.2f})"
        )
    for name, f in fields.items():
        if f["value"] is not None and f["confidence"] < LOW_FIELD_CONFIDENCE:
            issues.append(f"low confidence on {name} ({f['confidence']:.2f}, {f['source']})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "issues": issues,
        "extraction_method": extract_result["method"],
        "extraction_confidence": extract_result["extraction_confidence"],
    }

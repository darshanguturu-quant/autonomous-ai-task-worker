"""GUARDRAIL 3 - LLM / EXTRACTION OUTPUT VALIDATION (numeric sanity bounds).

Numeric fields coming out of extraction - whether regex-parsed from a text
layer or produced by the vision LLM - are sanity-bounded before the Validate
stage ever calls the document "passed". A value outside these bounds fails a
named check exactly like a missing required field, and Decide's R2 rule
routes the run to Needs Review - nothing outside these bounds can reach
Auto-Approve.

(Totals reconciling with subtotal + tax, and line items summing to the
subtotal, are separate existing checks in app/pipeline/validate.py - this
module adds the two checks that were missing: no negative amounts, no
absurdly large amounts.)
"""

MAX_REASONABLE_AMOUNT = 1_000_000.00  # far above any real PO in this dataset; a value
                                       # above this is almost certainly a parsing/extraction
                                       # error, not a real invoice - never trust it blindly

MONEY_FIELDS = ("subtotal", "tax", "total")


def check_amount_bounds(fields: dict) -> list[dict]:
    """Return one entry per money field that is negative or absurdly large.
    Empty list = every extracted amount is within sane bounds."""
    issues: list[dict] = []
    for name in MONEY_FIELDS:
        value = fields.get(name, {}).get("value")
        if value is None:
            continue
        if value < 0:
            issues.append({"field": name, "reason": f"{name} is negative (${value:,.2f})"})
        elif value > MAX_REASONABLE_AMOUNT:
            issues.append({
                "field": name,
                "reason": f"{name} of ${value:,.2f} exceeds the ${MAX_REASONABLE_AMOUNT:,.2f} "
                          "sanity bound - almost certainly a parsing/extraction error",
            })
    return issues

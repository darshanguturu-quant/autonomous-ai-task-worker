"""Stage 4 - DECIDE: deterministic rules engine -> Auto-Approve / Needs Review / Reject.

The decision is NEVER made by an LLM. Rules are evaluated in a fixed order;
the first terminal rule wins, and the full evaluation trace (every rule,
triggered or not) is part of the output so the decision is auditable.

An LLM may later rephrase the explanation for readability - it cannot change
the outcome. Until an API key is configured, the deterministic explanation
below is used as-is (it is already written in plain language).
"""

AUTO_APPROVE = "auto_approve"
NEEDS_REVIEW = "needs_review"
REJECT = "reject"

LOW_CONFIDENCE_THRESHOLD = 0.70

# GUARDRAIL 4 - DECISION ENGINE BOUNDS. Hard dollar cap on auto-approval: no
# invoice above this amount is EVER auto-approved, no matter how cleanly the
# vendor/PO/amount checks pass (rule R8, below). This is the one number to
# point to when asked "what stops a huge invoice from slipping through on a
# clean match" - change the policy, change this constant, nothing else.
AUTO_APPROVAL_MAX_AMOUNT = 25_000.00


def _find_duplicate(extract_result: dict, prior_invoices: list[dict]) -> dict | None:
    """Field-based duplicate check: same invoice number + vendor + total."""
    inv_no = extract_result["fields"]["invoice_number"]["value"]
    vendor = extract_result["fields"]["vendor_name"]["value"]
    total = extract_result["fields"]["total"]["value"]
    for prior in prior_invoices:
        if (
            prior.get("invoice_number") == inv_no
            and prior.get("vendor_name") == vendor
            and prior.get("total") == total
        ):
            return prior
    return None


def decide(
    extract_result: dict,
    validation: dict,
    match_result: dict,
    prior_invoices: list[dict] | None = None,
    guardrails_result: dict | None = None,
) -> dict:
    prior_invoices = prior_invoices or []
    guardrails_result = guardrails_result or {"flagged": False, "findings": []}
    trace: list[dict] = []
    outcome: tuple[str, str] | None = None  # (decision, reason)

    def rule(name: str, triggered: bool, decision: str | None, detail: str) -> None:
        nonlocal outcome
        trace.append({"rule": name, "triggered": triggered, "detail": detail})
        if triggered and decision and outcome is None:
            outcome = (decision, detail)

    amount = match_result.get("amount_check")
    po = match_result.get("po_match")
    vendor = match_result["vendor_match"]

    # R0 - prompt-injection screening (GUARDRAIL 2). Evaluated before every
    # other rule: a document trying to manipulate this pipeline through its
    # own text is never auto-approved, no matter how clean its other fields
    # look. `findings` comes from the static pattern scan in the Guardrails
    # stage (app/pipeline/guardrails.py) - never an LLM judgment call.
    findings = guardrails_result.get("findings", [])
    rule(
        "R0_prompt_injection_detected", guardrails_result.get("flagged", False), NEEDS_REVIEW,
        (
            "suspicious content detected in extracted text: "
            + "; ".join(
                f"\"{f['matched_text']}\" ({f['pattern']}, field {f['field']})" for f in findings
            )
        ) if findings else "no prompt-injection patterns detected in extracted text",
    )

    # R1 - duplicate invoice (field-based, against prior runs)
    dup = _find_duplicate(extract_result, prior_invoices)
    rule(
        "R1_duplicate_invoice", dup is not None, REJECT,
        f"duplicate of already-processed invoice "
        f"'{dup['invoice_number']}' (run {dup.get('run_id', '?')}, same vendor and total)"
        if dup else "no prior run with same invoice number + vendor + total",
    )

    # R2 - validation must pass (required fields present, arithmetic consistent)
    failed = [c["name"] for c in validation["checks"] if not c["passed"]]
    rule(
        "R2_validation_failed", bool(failed), NEEDS_REVIEW,
        f"validation checks failed: {', '.join(failed)}" if failed
        else "all validation checks passed",
    )

    # R3 - vendor must be known and approved
    unknown_vendor = not vendor["matched"] or not vendor.get("approved", False)
    rule(
        "R3_vendor_unknown_or_unapproved", unknown_vendor, REJECT,
        vendor["detail"] if unknown_vendor
        else f"vendor approved: {vendor['vendor_name']} ({vendor['vendor_id']})",
    )

    # R4 - a PO must be found (explicitly or via fuzzy fallback)
    no_po = po is None or not po.get("matched")
    rule(
        "R4_no_po_found", no_po, NEEDS_REVIEW,
        (po or {}).get("detail", "no PO match attempted") if no_po
        else f"PO {po['po_number']} matched ({po['match_type']})",
    )

    # R5 - low extraction confidence -> a human should look
    low_conf = extract_result["extraction_confidence"] < LOW_CONFIDENCE_THRESHOLD
    rule(
        "R5_low_extraction_confidence", low_conf, NEEDS_REVIEW,
        f"extraction confidence {extract_result['extraction_confidence']:.2f} "
        f"is below {LOW_CONFIDENCE_THRESHOLD} ({extract_result['method']} extraction)"
        if low_conf else
        f"extraction confidence {extract_result['extraction_confidence']:.2f} "
        f"({extract_result['method']} extraction)",
    )

    # R6 - fuzzy PO match (no explicit reference) always needs a human, even in
    # tolerance: paying against a guessed PO is not an automated call.
    fuzzy = bool(po and po.get("matched") and po["match_type"] == "fuzzy_vendor_amount")
    if fuzzy and amount:
        detail = (
            f"no PO reference on invoice; best candidate {po['po_number']} "
            f"(${amount['po_amount']:,.2f}) vs invoice ${amount['invoice_total']:,.2f} "
            f"-> difference ${abs(amount['difference']):,.2f} "
            f"{'within' if amount['within_tolerance'] else 'BEYOND'} "
            f"tolerance ${amount['tolerance']:,.2f}"
        )
    else:
        detail = "PO reference was explicit on the document" if po and po.get("matched") else "n/a"
    rule("R6_fuzzy_po_needs_confirmation", fuzzy, NEEDS_REVIEW, detail)

    # R7 - amount tolerance (full billing) / cumulative check (partial billing)
    if amount:
        if amount["billing_mode"] == "full":
            over = not amount["within_tolerance"]
            rule(
                "R7_amount_out_of_tolerance", over, NEEDS_REVIEW,
                f"invoice ${amount['invoice_total']:,.2f} vs PO ${amount['po_amount']:,.2f}: "
                f"difference ${abs(amount['difference']):,.2f} "
                f"{'exceeds' if over else 'within'} tolerance ${amount['tolerance']:,.2f} "
                f"({amount['tolerance_rule']})",
            )
        else:
            over_po = not amount["cumulative_within_po"]
            rule(
                "R7_cumulative_exceeds_po", over_po, NEEDS_REVIEW,
                f"partial billing against PO ${amount['po_amount']:,.2f}: prior invoices "
                f"${amount['cumulative_prior']:,.2f} + this invoice "
                f"${amount['invoice_total']:,.2f} = ${amount['cumulative_with_this_invoice']:,.2f} "
                f"{'EXCEEDS' if over_po else 'within'} PO + tolerance",
            )
    else:
        rule("R7_amount_check", po is not None and bool(po.get("matched")), NEEDS_REVIEW,
             "amount check could not run (missing total or PO)")

    # R8 - hard auto-approval dollar cap (GUARDRAIL 4). Even a textbook-clean
    # match (approved vendor, exact PO, within tolerance) never auto-approves
    # above AUTO_APPROVAL_MAX_AMOUNT - large invoices always get a human,
    # regardless of how well everything else checks out.
    total = extract_result["fields"]["total"]["value"]
    over_cap = total is not None and total > AUTO_APPROVAL_MAX_AMOUNT
    rule(
        "R8_amount_exceeds_auto_approval_cap", over_cap, NEEDS_REVIEW,
        (
            f"invoice total ${total:,.2f} exceeds the ${AUTO_APPROVAL_MAX_AMOUNT:,.2f} "
            "auto-approval cap - always routed to a human, regardless of match quality"
        ) if over_cap else
        (
            f"invoice total ${total:,.2f} is within the ${AUTO_APPROVAL_MAX_AMOUNT:,.2f} "
            "auto-approval cap"
            if total is not None else
            f"no total extracted; auto-approval cap of ${AUTO_APPROVAL_MAX_AMOUNT:,.2f} not applicable"
        ),
    )

    decision, primary_reason = outcome or (
        AUTO_APPROVE,
        "all checks passed: approved vendor, valid PO, amount within tolerance",
    )

    return {
        "decision": decision,
        "primary_reason": primary_reason,
        "rules_trace": trace,
        "explanation": _explain(decision, primary_reason, extract_result, match_result, validation),
    }


def _explain(decision: str, reason: str, extract_result: dict, match_result: dict,
             validation: dict) -> str:
    """Deterministic plain-language explanation of the rules-engine outcome."""
    f = extract_result["fields"]
    inv = f["invoice_number"]["value"] or "unknown"
    vendor = f["vendor_name"]["value"] or "unknown vendor"
    total = f["total"]["value"]
    total_s = f"${total:,.2f}" if total is not None else "an unknown amount"

    if decision == AUTO_APPROVE:
        head = f"Invoice {inv} from {vendor} for {total_s} is approved for payment."
    elif decision == NEEDS_REVIEW:
        head = f"Invoice {inv} from {vendor} for {total_s} needs a human decision."
    else:
        head = f"Invoice {inv} from {vendor} for {total_s} was rejected."

    body = f" Why: {reason}."
    issues = validation.get("issues") or []
    if issues:
        body += f" Also note: {'; '.join(issues)}."
    amount = match_result.get("amount_check")
    if amount and decision == AUTO_APPROVE:
        if amount["billing_mode"] == "partial":
            body += (
                f" This is a partial billing: ${amount['cumulative_with_this_invoice']:,.2f} "
                f"of the ${amount['po_amount']:,.2f} PO has now been invoiced."
            )
        else:
            body += (
                f" The amount is ${abs(amount['difference']):,.2f} "
                f"from the PO value, inside the ${amount['tolerance']:,.2f} tolerance."
            )
    return head + body
